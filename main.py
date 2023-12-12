# Copyright 2023 Google LLC..
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A Flask server for running Causal Impact.

This solution runs an analysis pulling information from Google Ads and Google
Analytics. Information can be augmented by uploading a CSV file.
"""

from datetime import datetime, timedelta
import json, os, socket, struct
from causal import getCiChart, getCiObject, getCiReport, getCiSummary, getValidation
from csv_data import csv_get_date_range, csv_merge_data, get_csv_columns, get_csv_data
from flask import Flask, jsonify, redirect, render_template, request, session
from ga4 import get_ga4_account_ids, get_ga4_data, get_ga4_property_ids
from gads import get_gads_campaigns, get_gads_customer_ids, get_gads_data, get_gads_mcc_ids, process_gads_responses
from google_auth_oauthlib.flow import Flow
import numpy as np
import pandas as pd

app = Flask(__name__)
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.config['SESSION_FILE_DIR'] = '/tmp'
app.secret_key = os.environ.get('FLASK_SECRET_KEY')

def is_loopback(host):
  loopback_checker = {
      socket.AF_INET: (
          lambda x: struct.unpack('!I', socket.inet_aton(x))[0] >> (32 - 8)
          == 127
      ),
      socket.AF_INET6: lambda x: x == '::1',
  }
  for family in (socket.AF_INET, socket.AF_INET6):
    try:
      r = socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)
    except socket.gaierror:
      return False
    for family, _, _, _, sockaddr in r:
      if not loopback_checker[family](sockaddr[0]):
        return False
  return True

if is_loopback('localhost'):
  _SERVER = 'localhost'
  _PORT = 8080
  _REDIRECT_URI = f'http://{_SERVER}:{_PORT}/oauth_completed'
  
else:
  PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT')
  _REDIRECT_URI = f'https://{PROJECT_ID}.ew.r.appspot.com/oauth_completed'
  app.config['SESSION_COOKIE_SECURE'] = True
  app.config['SESSION_COOKIE_HTTPONLY'] = True
  app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
  app.config['SESSION_COOKIE_NAME'] = '__Host-causal-impact-session'

SCOPES = [
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/adwords',
]
CLIENT_SECRETS_PATH = os.getcwd() + '/client_secret.json'

flow: Flow
csv_data = {}

@app.after_request
def add_header(response):
  response.headers['X-Content-Type-Options'] = 'nosniff'
  response.headers['X-Frame-Options'] = 'SAMEORIGIN'
  response.headers['Referrer-Policy'] = 'strict-origin'
  response.headers['Strict-Transport-Security'] = (
      'max-age=31536000; includeSubDomains'
  )
  return response
 
@app.route("/_ah/warmup")
def warmup():
    """Served stub function returning no content.

    Your warmup logic can be implemented here (e.g. set up a database connection pool)

    Returns:
        An empty string, an HTTP code 200, and an empty object.
    """
    return "", 200, {}

@app.route('/')
def root():
  authed = "false"
  if 'credentials' in session:
    authed="true"
  return render_template('index.html', authed=authed)


@app.route('/oauth')
def oauth():
  if 'credentials' in session:
    return redirect('/')
  else:
    flow = create_flow()
    authorization_url = flow.authorization_url(prompt='consent')
    return redirect(authorization_url[0])


@app.route('/oauth_completed')
def oauth_complete():
  if request.args.get('code'):
    code = request.args.get('code', 0, type=str)
    flow = create_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials
    session['credentials'] = credentials.to_json()
  return redirect('/')


@app.route('/report', methods=['POST'])
def report():
  gads_responses = []
  data = json.loads(request.form.get('data_to_send', 0, type=str))
  raw_data = {}
  warnings = ''
  if 'gads' in data:
    for key in data['gads']['query']:
      gads_responses.append(
          get_gads_data(
              data['gads']['mcc_id'],
              key,
              data['gads']['query'][key],
              data['from_date'],
              data['to_date'],
          )
      )
    raw_data = process_gads_responses(gads_responses, data['gads']['metrics'])

  if 'ga4' in data:
    raw_data = get_ga4_data(
        data['ga4']['property'],
        data['from_date'],
        data['to_date'],
        data['ga4']['metrics'],
        raw_data,
    )

  if 'csv' in data:
    csv_data = session['csv_data']
    raw_data = csv_merge_data(csv_data, data['csv'], raw_data)
  if raw_data:
    idx = pd.date_range(data['from_date'], data['to_date'])
    df = pd.DataFrame.from_dict(raw_data).transpose()
    df.replace(np.NaN, 0, inplace=True)
    df = df.apply(pd.to_numeric, errors='ignore')

    df.index = pd.DatetimeIndex(df.index)
    df = df.reindex(idx, fill_value=0)  # fills in any blank dates
    df = df[
        [data['target_event']]
        + [c for c in df if c not in [data['target_event']]]
    ]  # Puts target event as first column

    if 0 in df.values:
      warnings = (
          'Some values have 0 in them which are from your data or where dates'
          ' were missing and were filled in automatically'
      )

    from_d = datetime.strptime(data['from_date'], '%Y-%m-%d')
    to_d = datetime.strptime(data['to_date'], '%Y-%m-%d')
    event_d = datetime.strptime(data['event_date'], '%Y-%m-%d')

    pre_delta = (event_d - from_d).days
    post_delta = (to_d - event_d).days

    pre_period = [0, pre_delta - 1]
    post_period = [pre_delta, pre_delta + post_delta]

    impact = getCiObject(df, pre_period, post_period)

    return render_template(
        'report.html',
        summary=getCiSummary(impact),
        chart=getCiChart(impact),
        report=getCiReport(impact),
        raw_data=df.to_html(),
        warnings=warnings,
        validation=getValidation(df)
    )
  else:
    return render_template(
        'report.html',
        summary='No data in datasources!',
        chart='No data in datasources!',
        report='No data in datasources!',
        warnings='No data in datasources!',
        validation='No data in datasouces!'
    )

@app.route('/_get_gads_mcc_ids')
def _get_gads_mcc_ids():
  try:
    mcc_ids = get_gads_mcc_ids()
    return jsonify(result=mcc_ids)
  except:
    print('Error code 1')
    return jsonify(result='error')


@app.route('/_get_gads_customer_ids')
def _get_gads_customer_ids():
  try:
    mcc_id = request.args.get('mcc_id', 0, type=str)
    customer_ids = get_gads_customer_ids(mcc_id)
    return jsonify(result=customer_ids)
  except:
    print('Error code 2')
    return jsonify(result='error')


@app.route('/_get_gads_campaigns')
def _get_gads_campaigns():
  try:
    mcc_id = request.args.get('mcc_id', 0, type=str)
    customer_id = request.args.get('customer_id', 0, type=str)
    campaigns = get_gads_campaigns(mcc_id, customer_id)
    return jsonify(result=campaigns)
  except:
    print('Error code 3')
    return jsonify(result='error')


@app.route('/_get_ga4_account_ids')
def _get_ga4_account_ids():
  account_ids = get_ga4_account_ids()
  return jsonify(result=account_ids)


@app.route('/_get_ga4_property_ids')
def _get_ga4_property_ids():
  account_id = request.args.get('account_id', 0, type=str)
  property_ids = get_ga4_property_ids(account_id)
  return jsonify(result=property_ids)


@app.route('/upload_csv', methods=['GET', 'POST'])
def upload_file():
  if request.method == 'POST':
    csv_settings = []
    f = request.files['file']
    csv_data = get_csv_data(f)

    csv_columns, csv_date_column = get_csv_columns(csv_data)
    if not csv_date_column:
      csv_settings.append('error')
      csv_settings.append(
          "'date' column not found. Add 'date' heading and use date format"
          " 'yyyy-mm-dd' in the values"
      )

    else:
      start_date, end_date = csv_get_date_range(csv_data, csv_date_column)
      if _validate_date(start_date) and _validate_date(end_date):
        csv_settings.append('ok')
        csv_settings.append(csv_date_column)
        csv_settings.append(csv_columns)
        csv_settings.append(start_date)
        csv_settings.append(end_date)
        session['csv_data'] = csv_data
      else:
        csv_settings.append('error')
        csv_settings.append(
            "'date' column found but some data does not match 'yyyy-mm-dd'"
            ' format'
        )
    return jsonify(result=csv_settings)


def _validate_date(date_text):
  try:
    if date_text != datetime.strptime(date_text, '%Y-%m-%d').strftime(
        '%Y-%m-%d'
    ):
      raise ValueError
    return True
  except ValueError:
    return False


def create_flow():
  with open(CLIENT_SECRETS_PATH, 'r') as json_file:
    client_config = json.load(json_file)
  global flow
  flow = Flow.from_client_config(client_config=client_config, scopes=SCOPES)
  flow.redirect_uri = _REDIRECT_URI
  return flow


if __name__ == '__main__':
  app.run(host='127.0.0.1', port=8080, debug=True)
