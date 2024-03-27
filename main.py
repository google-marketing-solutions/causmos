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
from causal import getCiChart, getCiObject, getCiReport, getCiSummary, getValidation, getDfMatrix
from csv_data import csv_get_date_range, csv_merge_data, get_csv_columns, get_csv_data, bm_merge_data
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session
from ga4 import get_ga4_account_ids, get_ga4_data, get_ga4_property_ids
from gads import get_gads_campaigns, get_gads_customer_ids, get_gads_data, get_gads_mcc_ids, process_gads_responses
from fs_storage import set_value_session, get_value_session, delete_field
from gsheet_data import get_raw_gsheet_data
from slides_api import create_slide
from google_auth_oauthlib.flow import Flow
import numpy as np
import pandas as pd
import re
from uuid import uuid4
import logging
from project_secrets import get_secret

app = Flask(__name__)

app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.secret_key = get_secret('flask_secret_key')
PROJECT_ID = ""

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
  _MAIN_URL = f'http://{_SERVER}:{_PORT}'
  _REDIRECT_URI = f'{_MAIN_URL}/oauth_completed'
  
else:
  PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT')
  _MAIN_URL = f'https://{PROJECT_ID}.ew.r.appspot.com'
  _REDIRECT_URI = f'{_MAIN_URL}/oauth_completed'
  app.config['SESSION_COOKIE_SECURE'] = True
  app.config['SESSION_COOKIE_HTTPONLY'] = True
  app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
  app.config['SESSION_COOKIE_NAME'] = '__Host-causal-impact-session'

SCOPES = [
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/adwords',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/presentations',
    'https://www.googleapis.com/auth/drive'
]

flow: Flow
csv_data = {}
custom_inc = ""
if 'CUSTOM_INCLUDES' in os.environ:
  custom_inc = os.environ.get('CUSTOM_INCLUDES')

@app.route('/favicon.ico')
def fav():
    return send_from_directory(os.path.join(app.root_path, 'static'),'favicon.ico')

def check_session_id():
  if 'session_id' in session:
    return True
  else:
    return False
  
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

@app.route("/_create_slide")
def _create_slide():
    if request.args.get('client_name'):
      client_name = request.args.get('client_name', 0, type=str)
      slide_template_id = request.args.get('temp_id', 0, type=str)
      prepend = request.args.get('prepend', 0, type=is_it_true)
      return jsonify(result=create_slide(get_session_id(), slide_template_id, client_name, prepend, _MAIN_URL))   
    else:
      return jsonify(result="No client name")

def is_it_true(value):
  return value.lower() == 'true'

@app.route("/_ah/warmup")
def warmup():
    return "", 200, {}

@app.route('/sessionExpired')
def sessionExpired():
  session.clear()
  return render_template('sessionExpired.html', custom_inc=custom_inc)

@app.route('/')
def root():
  authed = "false"
  auth_analytics="false"
  auth_adwords="false"
  auth_sheets="false"
  auth_slides="false"
  creds = get_value_session(get_session_id(), 'credentials')
  if creds:
    authed="true"
  analytics = get_value_session(get_session_id(), 'analytics')
  if analytics:
    auth_analytics="true"
  adwords = get_value_session(get_session_id(), 'adwords')
  if adwords:
    auth_adwords = "true"
  sheets = get_value_session(get_session_id(), 'sheets')
  if sheets:
    auth_sheets = "true"
  slides = get_value_session(get_session_id(), 'slides')
  if slides:
    auth_slides = "true"
  
  return render_template('index.html', authed=authed, auth_analytics=auth_analytics, auth_adwords=auth_adwords, auth_sheets=auth_sheets, auth_slides=auth_slides, project_id=PROJECT_ID, custom_inc=custom_inc, bm_name=os.environ.get('BM_DATASOURCE'))


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
    if 'spreadsheets' in scope:
      set_value_session(get_session_id(), 'sheets', 'true')
    if 'presentations' in scope:
      set_value_session(get_session_id(), 'slides', 'true')
    
    scope = scope.split(" ")
    flow = create_flow(scope)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    set_value_session(get_session_id(), 'credentials', credentials.to_json())
  return redirect('/')


@app.route('/report', methods=['POST'])
def report():
  auth_slides="false"
  slides = get_value_session(get_session_id(), 'slides')
  if slides:
    auth_slides = "true"
  gads_responses = []
  if request.form.get('data_to_send') and check_session_id():
    data = json.loads(request.form.get('data_to_send', 0, type=str))
    raw_data = {}
    credibility = 1-(int(data['credibility'])/100)
    warnings = ''
    if 'gads' in data:
      for key in data['gads']['query']:
        try:
          gads_responses.append(
              get_gads_data(
                  data['gads']['mcc_id'],
                  key,
                  data['gads']['query'][key],
                  data['from_date'],
                  data['to_date']
              )
          )
        except ValueError as e:
          logging.exception(e)
          session.clear()
          return redirect('sessionExpired', custom_inc=custom_inc) 
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
        csv_data = get_raw_gsheet_data(get_value_session(get_session_id(), 'sheet_id'))
      else:
        csv_data = get_value_session(get_session_id(), 'csv_data')
      raw_data = csv_merge_data(csv_data, data['csv'], raw_data)
    
    if 'bm' in data:
      bm_data = get_raw_gsheet_data(get_value_session(get_session_id(), 'bm_sheet_id'), 'Data Breakdown')
      raw_data = bm_merge_data(bm_data, data['bm'], raw_data)

    if raw_data:    
      idx = pd.date_range(data['from_date'], data['to_date'])
      df = pd.DataFrame.from_dict(raw_data).transpose()
      if data['target_event'] in df.columns:
        df.replace(np.NaN, 0, inplace=True)
        df.replace('', 0, inplace=True)
        df.index = pd.DatetimeIndex(df.index)
        df = df.sort_index()
        df = df.apply(pd.to_numeric)
        df = df[
            [data['target_event']]
            + [c for c in df if c not in [data['target_event']]]
        ]  # Puts target event as first column

        if 0 in df.values:
          warnings = (
              'Some values have 0 in them which are from your data or where dates'
              ' were missing and were filled in automatically'
          )

        try:
          from_d = df.index.get_loc(data['from_date'])
          to_d = df.index.get_loc(data['to_date'])
          event_d = df.index.get_loc(data['event_date'])
        except KeyError:
          return render_template(
          'report.html',
          custom_inc=custom_inc,
          summary='-',
          chart="-",
          report="-",
          raw_data="-",
          warnings="One of your selected dates does not exist in your data set!",
          validation="-",
          v1_validation_chart="-",
          v1_summary="-",
          v2_validation_chart="-",
          v2_summary="-",
          v3_matrix="-",
          slide_template="-",
          auth_slides="false"
      )

        pre_period = [from_d, event_d-1]
        post_period = [event_d, to_d]
        try:
          impact = getCiObject(df, pre_period, post_period, credibility)
        except ValueError as e:
          logging.log(e)
          return render_template(
          'report.html',
          custom_inc=custom_inc,
          summary='-',
          chart="-",
          report="-",
          raw_data="-",
          warnings=f"Error: There was an error with generating the Causal Impact charts",
          validation="-",
          v1_validation_chart="-",
          v1_summary="-",
          v2_validation_chart="-",
          v2_summary="-",
          v3_matrix="-",
          slide_template="-",
          auth_slides="false")
        
        org_summary=getCiSummary(impact, credibility)
        image_name = get_value_session(get_session_id(), 'image_name')
        if not image_name:
          image_name = str(uuid4())+".png"
        set_value_session(get_session_id(), 'image_name', image_name)
        org_chart = getCiChart(impact=impact, img=True, image_name=image_name)
        org_chart = org_chart.replace("var spec", "main_spec").replace(" spec,", " main_spec,")
        org_report=getCiReport(impact, credibility)
        org_cov = (', ').join(df.columns[1:])

        dfhtml = df.to_html().replace("<th>", "<th class='full-table-border'>").replace("<tr>", "<tr class='full-table-border'>")
        df_val = getValidation(df)

        #Matrix Validation (v3)
        v3_matrix="-"
        if data['matrix_validation']==True:
          v3_matrix = getDfMatrix(df)

        #Pre-Period validation (v1)
        v1_validation_chart="-"
        v1_summary="-"
        pre_delta = event_d - from_d
        if pre_delta > 4 and data['pre_period_validation']==True:
          v1_quarter = math.floor(pre_delta / 4)

          v1_pre_period = [from_d, from_d+(v1_quarter*3) -1]
          v1_post_period = [from_d + (v1_quarter*3), event_d-1]

          impact = getCiObject(df, v1_pre_period, v1_post_period, credibility)
          v1_validation_chart = getCiChart(impact=impact, div="vis_v1")
          v1_summary = getCiSummary(impact, credibility)

        #Unaffectedness Validation (v2)
        v2_validation_chart="-"
        v2_summary="-"

        if data['unaffectedness_validation']==True:
          df = df[
            [data['unaffectedness_option']]
            + [c for c in df if c not in [data['unaffectedness_option']]]
          ]
          df.drop(data['target_event'], axis=1, inplace=True)
          
          impact = getCiObject(df, pre_period, post_period, credibility)
          v2_validation_chart = getCiChart(impact=impact, div="vis_v2")
          v2_summary = getCiSummary(impact, credibility)
        
        pval = re.search(r"p:\s+([0-9]+\.[0-9]+)", org_summary[13][0])

        delete_field(get_session_id(), 'output_data')
        if len(org_summary[7])==3:
          tot_inc = org_summary[7][2].split(" ")[0]
        else:
          tot_inc = org_summary[7][1].split(")")[1].split(" ")[0]
        save_summary = ""
        for x in org_summary:
          save_summary += ("\t").join(x)
          save_summary += "\n"

        output_data = {
          'from_date': data['from_date'],
          'to_date': data['to_date'],
          'event_date': data['event_date'],
          'target_event': data['target_event'],
          'covariates': org_cov,
          'p_value': pval.group(1),
          'tot_inc': tot_inc,
          'rel_eff': org_summary[10][2].split(" ")[0],
          'image_name': image_name,
          'summary': save_summary,
          'report': org_report.replace('\n\n', '|').replace('\n', ' ').replace("|", "\n\n")
        }
        set_value_session(get_session_id(), 'output_data', output_data)

        slide_temp = ""
        if 'SLIDE_TEMPLATE' in os.environ:
          slide_temp = os.environ.get('SLIDE_TEMPLATE')

        return render_template(
            'report.html',
            custom_inc=custom_inc,
            summary=org_summary,
            chart=org_chart,
            report=org_report.replace('\n\n', '<br><br>'),
            raw_data=dfhtml,
            warnings=warnings,
            validation=df_val,
            v1_validation_chart=v1_validation_chart,
            v1_summary=v1_summary,
            v2_validation_chart=v2_validation_chart,
            v2_summary=v2_summary,
            v3_matrix=v3_matrix,
            slide_template=slide_temp,
            auth_slides=auth_slides
        )
      else:
        return render_template(
          'report.html',
          custom_inc=custom_inc,
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
          v3_matrix="-",
          slide_template="-",
          auth_slides="false"
      )
    else:
      return render_template(
          'report.html',
          custom_inc=custom_inc,
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
          v3_matrix="-",
          slide_template="-",
          auth_slides="false"
      )  
  else:
    session.clear()
    return redirect('sessionExpired', custom_inc=custom_inc)

@app.route('/_get_gads_mcc_ids')
def _get_gads_mcc_ids():
  try:
    return jsonify(result=get_gads_mcc_ids())
  except ValueError as e:
    logging.exception(e)
    return jsonify(result='error')


@app.route('/_get_gads_customer_ids')
def _get_gads_customer_ids():
  try:
    mcc_id = request.args.get('mcc_id', 0, type=str)
    return jsonify(result=get_gads_customer_ids(mcc_id))
  except ValueError as e:
    logging.exception(e)
    return jsonify(result='error')


@app.route('/_get_gads_campaigns')
def _get_gads_campaigns():
  try:
    return jsonify(result=get_gads_campaigns(request.args.get('mcc_id', 0, type=str), request.args.get('customer_id', 0, type=str)))
  except ValueError as e:
    logging.exception(e)
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

  final_gsheet = get_raw_gsheet_data(sheet_id)
  if final_gsheet[0]!="error":
    return jsonify(result=getCsvSettings(final_gsheet, "gsheet"))
  else:
    return jsonify(result=final_gsheet)
  
def getCsvSettings(csv_data: dict, format: str) -> dict:
  csv_settings = []
  try:
    csv_columns, csv_date_column, string_columns = get_csv_columns(csv_data)
  except ValueError as e:
     csv_settings.append('error')
     csv_settings.append(f'Error - There is an error reading the sheet. Please check format and try again.')
     return csv_settings
  if not csv_date_column:
    csv_settings.append('error')
    csv_settings.append(
        "'date' column not found. Add 'date' heading and use date format"
        " 'yyyy-mm-dd' in the values"
    )

  else:
    start_date, end_date = csv_get_date_range(csv_data, csv_date_column, False)
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

@app.route('/_get_bm_metrics')
def _get_bm_metrics():
  bm_covariates = request.args.get('bm_covariates', 0, type=str)
  final_bm_sheet = get_raw_gsheet_data(get_value_session(get_session_id(), 'bm_sheet_id'), 'Data Breakdown')
  metrics = set(val[bm_covariates] for val in final_bm_sheet if bm_covariates in val)
  return jsonify(result=list(metrics))


@app.route('/_get_bm_data')
def _get_bm_data():
  bm_settings = []
  sheet_id = request.args.get('bm_url', 0, type=str)
  if "https://" in sheet_id:
    sheet_id = sheet_id.split("/")[5]
  set_value_session(get_session_id(), 'bm_sheet_id', sheet_id)

  final_bm_sheet = get_raw_gsheet_data(sheet_id, 'Data Breakdown')

  if final_bm_sheet[0]!="error":
    return jsonify(result=getBmSettings(final_bm_sheet))
  else:
    return jsonify(result=final_bm_sheet)
  
def getBmSettings(bm_data: dict) -> dict:
  bm_settings = []
  bm_columns, bm_date_column, bm_string_columns = get_csv_columns(bm_data)
  bm_metrics = {}
  if len(bm_string_columns) > 0:
    bm_metrics = set(val[bm_string_columns[0]] for val in bm_data if bm_string_columns[0] in val)
  
  if not bm_date_column:
    bm_settings.append('error')
    bm_settings.append(
        "'date' column not found. Add 'date' heading and use date format"
        " 'yyyy-mm-dd' in the values"
    )

  else:
    start_date, end_date = csv_get_date_range(bm_data, bm_date_column, True)
    if _validate_date(start_date) and _validate_date(end_date):
      bm_settings.append('ok')
      bm_settings.append(bm_date_column)
      bm_settings.append(bm_columns)
      bm_settings.append(bm_string_columns)
      bm_settings.append(start_date)
      bm_settings.append(end_date)
      bm_settings.append(list(bm_metrics))
    else:
      bm_settings.append('error')
      bm_settings.append(
          "'date' column found but some data does not match 'yyyy-mm-dd' format'"
      )
  return bm_settings
  

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
  client_config = json.loads(get_secret('client_secret'))  
  global flow
  flow = Flow.from_client_config(client_config=client_config, scopes=scope)
  flow.redirect_uri = _REDIRECT_URI
  return flow


if __name__ == '__main__':
  app.run(host='127.0.0.1', port=8080, debug=True)
