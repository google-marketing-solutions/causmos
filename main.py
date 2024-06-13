# Copyright 2024 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A Flask server for running Causal Impact.

This solution runs an analysis pulling information from Google Ads and Google
Analytics. Information can be augmented by uploading a CSV file.
"""

from datetime import datetime, timedelta
import json
import os
import socket
import struct
import math
import logging
import numpy as np
import pandas as pd
import re
from google_auth_oauthlib.flow import Flow
from uuid import uuid4
from causal import (
  get_causal_impact_chart,
  get_causal_impact_object,
  get_causal_impact_report,
  get_causal_impact_summary,
  get_validation,
  get_df_matrix,
)
from csv_data import (
  csv_get_date_range,
  csv_merge_data,
  get_csv_columns_by_type,
  get_csv_data,
)
from flask import (
  Flask,
  jsonify,
  redirect,
  render_template,
  request,
  send_from_directory,
  session,
)
from bigquery_data import _get_raw_bq_data
from fs_storage import set_value_session, get_value_session, delete_field
from gsheet_data import get_raw_gsheet_data
from slides_api import create_slide
from project_secrets import get_secret
from ga4 import get_ga4_account_ids, get_ga4_data, get_ga4_property_ids
from gads import get_gads_campaigns, get_gads_customer_ids, get_gads_data, get_gads_mcc_ids, process_gads_responses


app = Flask(__name__)

app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.secret_key = get_secret('flask_secret_key')
PROJECT_ID = '' #can set for local testing


def is_loopback(host) -> bool:
  """Localhost check.

  Args:
    host: The URL of the server.

  Returns:
    Boolean 'true' if localhost, 'false' if not.
  """
  loopback_checker = {
    socket.AF_INET: (
      lambda x: struct.unpack('!I', socket.inet_aton(x))[0] >> (32 - 8) == 127
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
  if 'google.com' in PROJECT_ID:
    _MAIN_URL = 'https://causmos.googleplex.com'
  else:
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
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/bigquery'
]

flow: Flow
csv_data = {}


@app.route('/favicon.ico')
def fav() -> send_from_directory:
  """Returns the fav icon.

  Returns:
    Fav icon.
  """
  return send_from_directory(os.path.join(app.root_path,
          'static'), 'favicon.ico')


@app.route('/error')
def error_page(error_msg) -> render_template:
  """Returns the error page template.

  Args:
    error_msg: The message to display on the error page.

  Returns:
    Error page template.
  """
  return render_template('error.html', error_msg=error_msg)


def check_session_id() -> bool:
  """Checks if a session already exists.

  Returns:
    Boolean 'true' if session exists, 'false' if not.
  """
  if 'session_id' in session:
    return True
  else:
    return False


def get_session_id() -> str:
  """Returns the session ID for session storage access.

  Returns:
    Session ID as a string.
  """
  if 'session_id' in session:
    return session['session_id']
  else:
    session['session_id'] = str(uuid4())
    return session['session_id']


@app.after_request
def add_header(response) -> any:
  """Adds properties to the header response for security.

  Args:
    response: The HTTP response to be added to.

  Returns:
    The modified response with additional header elements.
  """
  response.headers['X-Content-Type-Options'] = 'nosniff'
  response.headers['X-Frame-Options'] = 'SAMEORIGIN'
  response.headers['Referrer-Policy'] = 'strict-origin'
  response.headers['Strict-Transport-Security'] = (
    'max-age=31536000; includeSubDomains'
  )
  return response


@app.route('/_create_slide')
def _create_slide() -> jsonify:
  """Provides a route to create the slides from the slide template.

  Returns:
    The slide ID of the newly generate slide deck.
  """
  if request.args.get('client_name'):
    client_name = request.args.get('client_name', 0, type=str)
    slide_template_id = request.args.get('temp_id', 0, type=str)
    prepend = request.args.get('prepend', 0, type=is_it_true)
    return jsonify(
      result=create_slide(
        get_session_id(), slide_template_id, client_name, prepend
      )
    )
  else:
    return jsonify(result='No client name')


def is_it_true(value) -> bool:
  """Used to lowercase the true value

  Args:
    value: The value to convert to boolean

  Returns:
    The boolean of the value
  """
  return value.lower() == 'true'


@app.route('/_ah/warmup')
def warmup():
  """Warmup method for keeping the instance alive in GCP.

  Returns:
    A simple response to keep the instances alive in GCP.
  """
  return '', 200, {}


@app.route('/sessionExpired')
def session_expired() -> render_template:
  """Renders the session expired template if the session has expired.

  Returns:
    The session expired template.
  """
  session.clear()
  return render_template('sessionExpired.html')


@app.route('/')
def root() -> render_template:
  """The main route and index of the application. This method checks the users
  credentials, what they have allowed and renders the template with the
  correct properties.

  Returns:
    The main page application.
  """
  creds = get_value_session(get_session_id(), 'credentials')
  analytics = get_value_session(get_session_id(), 'analytics')
  adwords = get_value_session(get_session_id(), 'adwords')
  sheets = get_value_session(get_session_id(), 'sheets')
  slides = get_value_session(get_session_id(), 'slides')
  authed = 'true' if creds else 'false'
  auth_analytics = 'true' if analytics else 'false'
  auth_adwords = 'true' if adwords else 'false'
  auth_sheets = 'true' if sheets else 'false'
  auth_slides = 'true' if slides else 'false'

  return render_template(
    'index.html',
    authed=authed,
    auth_analytics=auth_analytics,
    auth_adwords=auth_adwords,
    auth_sheets=auth_sheets,
    auth_slides=auth_slides,
    bq_name=os.environ.get('bq_DATASOURCE'),
  )


@app.route('/oauth')
def oauth() -> redirect:
  """Creates the flow for authentication and redirects to the Google
  authentication page.

  Returns:
    The authentication page for Google authentication.
  """
  flow = create_flow(SCOPES)
  authorization_url = flow.authorization_url(prompt='consent')
  return redirect(authorization_url[0])


@app.route('/oauth_completed')
def oauth_complete() -> redirect:
  """Once authentication is completed, this method will return the user back to
  the application and set the session properties for what the user allowed.

  Returns:
    Returns the user to the main application page.
  """
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

    scope = scope.split(' ')
    flow = create_flow(scope)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    set_value_session(get_session_id(), 'credentials', credentials.to_json())
  return redirect('/')


@app.route('/report', methods=['POST'])
def report() -> render_template:
  """Retrieves all the data from the datasources, merges it and runs it through
  the causal impact library. Once completed, it then renders the report
  template and passes all the relevant data to the report page.

  Returns:
    The report template with all the data for the report page.
  """
  auth_slides = 'false'
  slides = get_value_session(get_session_id(), 'slides')
  if slides:
    auth_slides = 'true'
  if request.form.get('data_to_send') and check_session_id():
    data = json.loads(request.form.get('data_to_send', 0, type=str))

    print(data)
    raw_data = {}
    gads_responses = []
    credibility = 1 - (int(data['credibility']) / 100)
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
          return redirect('sessionExpired') 
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
      if data['csv_format'] == 'gsheet':
        csv_data = get_raw_gsheet_data(
          get_value_session(get_session_id(), 'sheet_id'),
          get_value_session(get_session_id(), 'gs_tab'),
        )[0]
      else:
        csv_data = get_value_session(get_session_id(), 'csv_data')
      raw_data = csv_merge_data(csv_data, data['csv'], raw_data, 'csv')

    if 'bq' in data:
      bq_data = _get_raw_bq_data(
        get_value_session(get_session_id(), 'bq_full_location'))
      raw_data = csv_merge_data(bq_data, data['bq'], raw_data, 'bq')

    if raw_data:
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
            'error.html',
            error_msg='One of your selected dates does not exist \
            in your data set! If using anything that is not daily data (weekly, \
            monthly etc.), you must select a date that exists in your dataset',
          )

        pre_period = [from_d, event_d - 1]
        post_period = [event_d, to_d]
        try:
          impact = get_causal_impact_object(
            df, pre_period, post_period, credibility
          )
        except ValueError as e:
          logging.exception(e)
          return render_template(
            'error.html',
            error_msg='There was an error with generating the Causal \
              Impact charts. Please try again.',
          )

        org_summary = get_causal_impact_summary(impact, credibility)
        image_name = get_value_session(get_session_id(), 'image_name')
        if not image_name:
          image_name = str(uuid4()) + '.png'
        set_value_session(get_session_id(), 'image_name', image_name)
        org_chart = get_causal_impact_chart(
          impact=impact, store_img=True, image_name=image_name
        )
        org_chart = org_chart.replace('var spec', 'main_spec').replace(
          ' spec,', ' main_spec,'
        )
        org_report = get_causal_impact_report(impact, credibility)
        org_cov = (', ').join(df.columns[1:])

        dfhtml = df.to_html().replace('<th>',
                    '<th class="full-table-border">').replace('<tr>', '<tr class="full-table-border">')
        df_val = get_validation(df)

        # Matrix Validation (v3)
        v3_matrix = ''
        if data['matrix_validation']:
          v3_matrix = get_df_matrix(df)

        # Pre-Period validation (v1)
        v1_validation_chart = '-'
        v1_summary = ''
        pre_delta = event_d - from_d
        if pre_delta > 4 and data['pre_period_validation']:
          v1_quarter = math.floor(pre_delta / 4)

          v1_pre_period = [from_d, from_d + (v1_quarter * 3) - 1]
          v1_post_period = [from_d + (v1_quarter * 3), event_d - 1]

          impact = get_causal_impact_object(
            df, v1_pre_period, v1_post_period, credibility
          )
          v1_validation_chart = get_causal_impact_chart(
            impact=impact, div='vis_v1'
          )
          v1_summary = get_causal_impact_summary(impact, credibility)

        # Unaffectedness Validation (v2)
        v2_validation_chart = '-'
        v2_summary = ''

        if data['unaffectedness_validation']:
          df = df[
            [data['unaffectedness_option']]
            + [c for c in df if c not in [data['unaffectedness_option']]]
          ]
          df.drop(data['target_event'], axis=1, inplace=True)

          impact = get_causal_impact_object(
            df, pre_period, post_period, credibility
          )
          v2_validation_chart = get_causal_impact_chart(
            impact=impact, div='vis_v2'
          )
          v2_summary = get_causal_impact_summary(impact, credibility)

        pval = re.search(r'p:\s+([0-9]+\.[0-9]+)', org_summary[13][0])

        delete_field(get_session_id(), 'output_data')
        if len(org_summary[7]) == 3:
          tot_inc = org_summary[7][2].split(' ')[0]
        else:
          tot_inc = org_summary[7][1].split(')')[1].split(' ')[0]
        save_summary = ''
        for x in org_summary:
          save_summary += ('\t').join(x)
          save_summary += '\n'

        # Tags for overview
        main_test=''
        pre_test=''
        unaff_test=''
        main_abs_eff = float(org_summary[7][2].strip().split(' ')[0])
        main_ci = [
          float(re.sub(r'[^\d\-.]', '', x))
          for x in org_summary[8][2].strip('[]').split(',')
        ]

        total_score = 1
        tag_msg = ''
        lift = ''
        if main_abs_eff > 0:
          lift = 'Uplift'
        else:
          lift = 'Downlift'

        save_v1_summary = ''
        pre_abs_eff = 0.0
        pre_ci = [0.0, 0.0]
        if v1_summary:
          if len(v1_summary[7]) > 2:
            pre_abs_eff = float((v1_summary[7][2].strip().split(' ')[0]))
          if len(v1_summary[8]) > 2:
            pre_ci = [
              float(re.sub(r'[^\d\-.]', '', x))
              for x in v1_summary[8][2].strip('[]').split(',')
            ]
          if (pre_ci[1] > 0 and pre_abs_eff <= 0) or \
          (pre_ci[0] < 0 and pre_abs_eff > 0):
            total_score += 3
            pre_test = 'Pre-period  \
                        validation doesn not show any causal \
                        impact before the intervention date'
            tag_msg += f'<span class="success"> \
                        <span class="material-symbols-outlined"> \
                        add_circle</span></span> {pre_test}<br>'
          else:
            pre_test = 'Pre-period validation shows causal impact  \
            which means there was an impact before the intervention date'
            tag_msg += f'<span class="negative"><span \
                class="material-symbols-outlined">do_not_disturb_on \
              </span></span> {pre_test}<br>'
          for x in v1_summary:
            save_v1_summary += ('\t').join(x)
            save_v1_summary += '\n'
        else:
          tag_msg += '<span class="negative"><span class="material-symbols-outlined">do_not_disturb_on</span> \
            </span> No Pre-period validation is reducing your score. \
                Consider running a Pre-preiod validation \
              to improve your score and validate your results<br>'

        save_v2_summary = ''
        unaff_abs_eff = 0.0
        unaff_ci = [0.0, 0.0]
        if v2_summary:
          if len(v2_summary[7]) > 2:
            unaff_abs_eff = float((v2_summary[7][2].strip().split(' ')[0]))
          if len(v2_summary[8]) > 2:
            unaff_ci = [
              float(re.sub(r'[^\d\-.]', '', x))
              for x in v2_summary[8][2].strip('[]').split(',')
            ]
          if (unaff_ci[1] > 0 and unaff_abs_eff <= 0) or \
          (unaff_ci[0] < 0 and unaff_abs_eff > 0):
            total_score += 3
            unaff_test = f'Unaffectedness validation shows your covariate \
            {data["unaffectedness_option"]} has no causal impact'
            tag_msg += f'<span class="success"><span \
              class="material-symbols-outlined">add_circle</span> \
              </span> {unaff_test}<br>'
          else:
            unaff_test = f'Unaffectedness validation shows your covariate \
              {data["unaffectedness_option"]} \
                was impacted by the event'
            tag_msg += f'<span class="negative"><span \
              class="material-symbols-outlined">do_not_disturb_on</span> \
              </span> {unaff_test}<br>'
          for x in v2_summary:
            save_v2_summary += ('\t').join(x)
            save_v2_summary += '\n'
        else:
          tag_msg += '<span class="negative"><span \
            class="material-symbols-outlined">do_not_disturb_on</span> \
            </span> No Unaffectedness validation is reducing your score. \
            Consider running an Unaffectedness \
            validation to improve your score and validate your results<br>'

        if main_ci[0] > 0 and lift == 'Uplift':
          total_score += 3
          main_test = 'Main test shows a significant uplift based on your \
            parameters'
          tag_msg += f'<span class="success"><span \
            class="material-symbols-outlined">add_circle</span></span> \
            {main_test}<br>'
        elif main_ci[1] < 0 and lift == 'Downlift':
          total_score += 3
          main_test = 'Main test shows a significant downlift based on your \
            parameters'
          tag_msg += f'<span class="success"><span \
            class="material-symbols-outlined">add_circle</span></span> \
            {main_test}<br>'
        else:
          total_score = 1
          main_test = 'Main test does not show a significant result'
          tag_msg += f'<span class="negative"><span \
            class="material-symbols-outlined">do_not_disturb_on</span> \
            </span> {main_test}<br>'

        output_data = {
          'from_date': data['from_date'],
          'to_date': data['to_date'],
          'event_date': data['event_date'],
          'target_event': data['target_event'],
          'covariates': org_cov,
          'p_value': pval.group(1),
          'tot_inc': tot_inc,
          'rel_eff': org_summary[10][2].split(' ')[0],
          'image_name': image_name,
          'summary': save_summary,
          'report': org_report.replace('\n\n', '|')
          .replace('\n', ' ')
          .replace('|', '\n\n'),
          'pre_period': save_v1_summary,
          'unaffectedness': save_v2_summary,
          'main_test': main_test,
          'pre_test': pre_test,
          'unaff_test': main_test
        }
        set_value_session(get_session_id(), 'output_data', output_data)

        slide_temp = ''
        if 'SLIDE_TEMPLATE' in os.environ:
          slide_temp = os.environ.get('SLIDE_TEMPLATE')

        return render_template(
          'report.html',
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
          auth_slides=auth_slides,
          lift=lift,
          total_score=total_score,
          tag_msg=tag_msg,
        )
      else:
        return render_template(
          'error.html',
          error_msg='Target event does not exist in data which is very \
          strange! If you have changed your datasource, make sure you re-select your target event from \
          the drop down',
        )

    else:
      return render_template(
        'error.html',
        error_msg='No data in datasources! The dates you have selected \
        have no data in the accounts you have selected. Try another date or \
        another account',
      )
  else:
    session.clear()
    return redirect('sessionExpired')


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
def upload_file() -> jsonify:
  """Uploads the CSV file to the server and stores the data in a temporary
  session.

  Returns:
    List of headers the CSV has for use as covariates, target events along with
    the available dates.
  """
  if request.method == 'POST':
    csv_data = get_csv_data(request.files['file'])
    set_value_session(get_session_id(), 'csv_data', csv_data)
    return jsonify(result=_get_csv_settings(csv_data, 'csv'))


@app.route('/_get_gs_data')
def _get_gs_data() -> jsonify:
  """Gets the headers, dates and available options from the Google sheets data
  for selection in the causal impact setup.

  Returns:
    List of headers the Google sheet has for use as covariates, target events
    along with the available dates.
  """
  sheet_id = request.args.get('gs_url', 0, type=str)
  gs_tab = request.args.get('gs_tab', 0, type=str)
  gid = request.args.get('gid', 0, type=int)
  if 'https://' in sheet_id:
    sheet_id = sheet_id.split('/')[5]
  set_value_session(get_session_id(), 'sheet_id', sheet_id)

  final_gsheet, sheets, sheet_name = get_raw_gsheet_data(sheet_id, gs_tab, gid)
  set_value_session(get_session_id(), 'gs_tab', sheet_name)

  if len(final_gsheet) == 0:
    res = []
    res.append('error')
    res.append(
      'No valid data in current tab. Please try selecting another tab or \
        upload a new sheet'
    )
    res.append('sheets')
    res.append(sheets)
    return jsonify(result=res)
  elif final_gsheet[0] != 'error':
    res = _get_csv_settings(final_gsheet, 'gsheet')
    res.append('sheets')
    res.append(sheets)
    res.append(sheet_name)
    return jsonify(result=res)
  else:
    return jsonify(result=final_gsheet)


def _get_csv_settings(csv_data: dict, format: str) -> dict:
  """Gets the CSV settings for running the analysis.

  Args:
    csv_data: The raw CSV data to extract settings from.
    format: The format of the CSV as CSV or gSheets.

  Returns:
    Dictionary of CSV settings.
  """
  csv_settings = []
  try:
    csv_columns, csv_date_column, string_columns = get_csv_columns_by_type(
      csv_data)
  except ValueError as e:
    logging.exception(e)
    csv_settings.append('error')
    csv_settings.append(
      'Error - There is an error reading the sheet. Please check format and \
        try again.'
    )
    return csv_settings
  if not csv_date_column:
    csv_settings.append('error')
    csv_settings.append(
      'A \'date\' column not found. Add \'date\' heading and use date format \
      \'yyyy-mm-dd\' in the values or try another tab'
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
        '\'date\' column found but some data does not match \
        \'yyyy-mm-dd\' format'
      )
  return csv_settings


@app.route('/_get_bq_data')
def _get_bq_data() -> jsonify:
  """Gets the headers, dates and available options from the BigQuery data
  for selection in the causal impact setup using the BQ data format.

  Returns:
    List of headers the Google sheet has for use as covariates, target events
    along with the available dates.
  """
  bq_project_id = request.args.get('bq_project_id', 0, type=str)
  bq_dataset = request.args.get('bq_dataset', 0, type=str)
  bq_table = request.args.get('bq_table', 0, type=str)
  final_bq_data = []
  try:
    bq_full_location = f'{bq_project_id}.{bq_dataset}.{bq_table}'
    set_value_session(get_session_id(), 'bq_full_location', bq_full_location)

    final_bq_data = _get_raw_bq_data(bq_full_location)
  except Exception as e:
    final_bq_data = ['error', 'Cannot find table. Check you have entered your project ID, Dataset and Table name correctly and try again']

  if final_bq_data[0] != 'error':
    return jsonify(result=_get_bq_settings(final_bq_data))
  else:
    return jsonify(result=final_bq_data)


def _get_bq_settings(bq_data: dict) -> dict:
  """Gets the BiqQuery settings for running the analysis.

  Args:
    bq_data: The raw BigQuery data to extract settings from.

  Returns:
    Dictionary of BQ settings.
  """
  bq_settings = []
  try:
    bq_columns, bq_date_column, string_columns = get_csv_columns_by_type(
      bq_data)
  except ValueError as e:
    logging.exception(e)
    bq_settings.append('error')
    bq_settings.append(
      'Error - There is an error reading the BQ bucket. Please check format and \
        try again.'
    )
    return bq_settings
  if not bq_date_column:
    bq_settings.append('error')
    bq_settings.append(
      'A \'date\' column not found. Add \'date\' heading and use date format \
      \'yyyy-mm-dd\' in the values or try another tab'
    )
  else:
    start_date, end_date = csv_get_date_range(bq_data, bq_date_column, False)
    if _validate_date(start_date) and _validate_date(end_date):
      bq_settings.append('ok')
      bq_settings.append(bq_date_column)
      bq_settings.append(bq_columns)
      bq_settings.append(start_date)
      bq_settings.append(end_date)
    else:
      bq_settings.append('error')
      bq_settings.append(
        '\'date\' column found but some data does not match \
        \'yyyy-mm-dd\' format'
      )
  return bq_settings

def _validate_date(date_text: str) -> bool:
  """Validates that a string is in the correct date format.

  Args:
    date_text: The date in string format for validating.

  Returns:
    Boolean of 'true' if the date format is valid and 'false' if it is not.
  """
  try:
    if date_text != datetime.strptime(date_text,
          '%Y-%m-%d').strftime('%Y-%m-%d'):
      raise ValueError
    return True
  except ValueError:
    return False


def create_flow(scope) -> Flow:
  """Creates a Flow object for user authentication with Google services.

  Args:
    scope: The scope the user has allowed.

  Returns:
    Flow object with all the relevant scopes and approvals.
  """
  client_config = json.loads(get_secret('client_secret'))
  global flow
  flow = Flow.from_client_config(client_config=client_config, scopes=scope)
  flow.redirect_uri = _REDIRECT_URI
  return flow


if __name__ == '__main__':
  app.run(host='127.0.0.1', port=8080, debug=True)
