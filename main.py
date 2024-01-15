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
import math
from causal import getCiChart, getCiObject, getCiReport, getCiSummary, getValidation
from csv_data import csv_get_date_range, csv_merge_data, get_csv_columns, get_csv_data
from flask import Flask, jsonify, redirect, render_template, request, session
from ga4 import get_ga4_account_ids, get_ga4_data, get_ga4_property_ids
from gads import get_gads_campaigns, get_gads_customer_ids, get_gads_data, get_gads_mcc_ids, process_gads_responses
from fs_storage import set_value_session, get_value_session
from google_auth_oauthlib.flow import Flow
import numpy as np
import pandas as pd
from uuid import uuid4
import gspread

app = Flask(__name__)

app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
PROJECT_ID = "causal-impact-insights"

def is_loopback(host) -> bool:
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
    #'https://www.googleapis.com/auth/spreadsheets.readonly'
]
CLIENT_SECRETS_PATH = os.getcwd() + '/client_secret.json'

flow: Flow
csv_data = {}

def get_session_id() -> str:
  if 'session_id' in session:
    return session['session_id']
  else:
    session['session_id'] = str(uuid4())
    return session['session_id']

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
    return "", 200, {}

@app.route('/sessionExpired')
def sessionExpired():
  return render_template('sessionExpired.html')

@app.route('/')
def root():
  authed = "false"
  auth_analytics="false"
  auth_adwords="false"
  creds = get_value_session(get_session_id(), 'credentials')
  if creds:
    authed="true"
  analytics = get_value_session(get_session_id(), 'analytics')
  if analytics:
    auth_analytics="true"
  adwords = get_value_session(get_session_id(), 'adwords')
  if adwords:
    auth_adwords = "true"
  
  return render_template('index.html', authed=authed, auth_analytics=auth_analytics, auth_adwords=auth_adwords, project_id=PROJECT_ID)


@app.route('/oauth')
def oauth():
  flow = create_flow(SCOPES)
  authorization_url = flow.authorization_url(prompt='consent')
  return redirect(authorization_url[0])


@app.route('/oauth_completed')
def oauth_complete():
  if request.args.get('code'):
    code = request.args.get('code', 0, type=str)
    scope = request.args.get('scope', 0, type=str)
    
    if 'analytics' in scope:
      set_value_session(get_session_id(), 'analytics', 'true')
      
    if 'adwords' in scope:
      set_value_session(get_session_id(), 'adwords', 'true')

    scope = scope.split(" ")
    flow = create_flow(scope)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    set_value_session(get_session_id(), 'credentials', credentials.to_json())
  return redirect('/')


@app.route('/report', methods=['POST'])
def report():
  gads_responses = []
  if request.form.get('data_to_send'):
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
      if(data['csv_format']=="gsheet"):
        csv_data = _get_gsheet_data(get_value_session(get_session_id(), 'sheet_id'))
      else:
        csv_data = get_value_session(get_session_id(), 'csv_data')
      raw_data = csv_merge_data(csv_data, data['csv'], raw_data)
    
    if raw_data:    
      idx = pd.date_range(data['from_date'], data['to_date'])
      df = pd.DataFrame.from_dict(raw_data).transpose()
      if data['target_event'] in df.columns:
        df.replace(np.NaN, 0, inplace=True)
        df.replace('', 0, inplace=True)
        df = df.apply(pd.to_numeric, errors='ignore')

        print(df)

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
        org_summary=getCiSummary(impact)
        org_chart=getCiChart(impact)
        org_report=getCiReport(impact)

        df_val = getValidation(df)
        dfhtml = df.to_html().replace("<th>", "<th class='full-table-border'>")
        dfhtml = dfhtml.replace("<tr>", "<tr class='full-table-border'>")

        #Pre-Period validation (v1)
        v1_validation_chart="-"
        v1_summary="-"
        if pre_delta > 4 and data['pre_period_validation']==True:
          v1_post_delta = math.floor(pre_delta / 4)
          v1_pre_delta = pre_delta - v1_post_delta

          v1_pre_period = [0, v1_pre_delta - 1]
          v1_post_period = [v1_pre_delta, v1_pre_delta + v1_post_delta]

          impact = getCiObject(df, v1_pre_period, v1_post_period)
          v1_validation_chart = getCiChart(impact, "vis_v1")
          v1_summary = getCiSummary(impact)

        #Uneffectiveness Validation (v2)
        v2_validation_chart="-"
        v2_summary="-"

        if data['uneffectiveness_validation']==True:
          df = df[
            [data['uneffectiveness_option']]
            + [c for c in df if c not in [data['uneffectiveness_option']]]
          ]
          df.drop(data['target_event'], axis=1, inplace=True)
          
          impact = getCiObject(df, pre_period, post_period)
          v2_validation_chart = getCiChart(impact, "vis_v2")
          v2_summary = getCiSummary(impact)

        return render_template(
            'report.html',
            summary=org_summary,
            chart=org_chart,
            report=org_report,
            raw_data=dfhtml,
            warnings=warnings,
            validation=df_val,
            v1_validation_chart=v1_validation_chart,
            v1_summary=v1_summary,
            v2_validation_chart=v2_validation_chart,
            v2_summary=v2_summary,
        )
      else:
        return render_template(
          'report.html',
          summary='-',
          chart="-",
          report="-",
          raw_data="-",
          warnings="Target event does not exist in data!",
          validation="-",
          v1_validation_chart="-",
          v1_summary="-",
          v2_validation_chart="-",
          v2_summary="-",
      )
    else:
      return render_template(
          'report.html',
          summary='-',
          chart="-",
          report="-",
          raw_data="-",
          warnings="No data in datasources!",
          validation="-",
          v1_validation_chart="-",
          v1_summary="-",
          v2_validation_chart="-",
          v2_summary="-",
      )
    
  else:
    return redirect('sessionExpired')

@app.route('/_get_gads_mcc_ids')
def _get_gads_mcc_ids():
  try:
    return jsonify(result=get_gads_mcc_ids())
  except:
    print('Error code 1')
    return jsonify(result='error')


@app.route('/_get_gads_customer_ids')
def _get_gads_customer_ids():
  try:
    mcc_id = request.args.get('mcc_id', 0, type=str)
    return jsonify(result=get_gads_customer_ids(mcc_id))
  except:
    print('Error code 2')
    return jsonify(result='error')


@app.route('/_get_gads_campaigns')
def _get_gads_campaigns():
  try:
    return jsonify(result=get_gads_campaigns(request.args.get('mcc_id', 0, type=str), request.args.get('customer_id', 0, type=str)))
  except:
    print('Error code 3')
    return jsonify(result='error')


@app.route('/_get_ga4_account_ids')
def _get_ga4_account_ids():
  return jsonify(result=get_ga4_account_ids())


@app.route('/_get_ga4_property_ids')
def _get_ga4_property_ids():
  return jsonify(result=get_ga4_property_ids(request.args.get('account_id', 0, type=str)))


@app.route('/upload_csv', methods=['GET', 'POST'])
def upload_file():
  if request.method == 'POST':
    csv_data = get_csv_data(request.files['file'])
    set_value_session(get_session_id(), 'csv_data', csv_data)
    return jsonify(result=getCsvSettings(csv_data, "csv"))

@app.route('/_get_gs_data')
def _get_gs_data():
  csv_settings = []
  sheet_id = request.args.get('gs_url', 0, type=str)
  if "https://" in sheet_id:
    sheet_id = sheet_id.split("/")[5]
  set_value_session(get_session_id(), 'sheet_id', sheet_id)

  final_gsheet = _get_gsheet_data(sheet_id)
  if final_gsheet[0]!="error":
    return jsonify(result=getCsvSettings(final_gsheet, "gsheet"))
  else:
    return jsonify(result=final_gsheet)
  

def _get_gsheet_data(sheet_id):
  sheet_err=['error']
  try:
    gc = gspread.service_account(filename='service_account.json')
    worksheet = gc.open_by_key(sheet_id).get_worksheet(0)
    final_gsheet = []
    values = worksheet.get_values()
    headers = values.pop(0)
    for row in values:
        temp_data = {}
        for inx, item in enumerate(headers):
            temp_data[item] = row[inx].replace(",", "")
        final_gsheet.append(temp_data)
    return final_gsheet
  except:
    sheet_err.append('Requires access to sheet or sheet has data without headers')
    return sheet_err
  
def getCsvSettings(csv_data: dict, format: str) -> dict:
  csv_settings = []
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
      csv_settings.append(format)
    else:
      csv_settings.append('error')
      csv_settings.append(
          "'date' column found but some data does not match 'yyyy-mm-dd' format'"
      )
  return csv_settings


def _validate_date(date_text: str) -> bool:
  try:
    if date_text != datetime.strptime(date_text, '%Y-%m-%d').strftime(
        '%Y-%m-%d'
    ):
      raise ValueError
    return True
  except ValueError:
    return False


def create_flow(scope) -> Flow:
  with open(CLIENT_SECRETS_PATH, 'r') as json_file:
    client_config = json.load(json_file)
  global flow
  flow = Flow.from_client_config(client_config=client_config, scopes=scope)
  flow.redirect_uri = _REDIRECT_URI
  return flow


if __name__ == '__main__':
  app.run(host='127.0.0.1', port=8080, debug=True)
