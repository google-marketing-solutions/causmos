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

from datetime import datetime
import json
from flask import session
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from fs_storage import get_value_session


def get_analytics_client():
  creds_info = json.loads()
  creds = Credentials.from_authorized_user_info(creds_info)
  analytics = build('analyticsdata', 'v1beta', credentials=creds)

  return analytics


def get_analytics_admin_client():
  creds_info = json.loads(get_value_session(session['session_id'], 'credentials'))
  creds = Credentials.from_authorized_user_info(creds_info)
  analytics_admin = build('analyticsadmin', 'v1beta', credentials=creds)
  return analytics_admin


def get_ga4_account_ids() -> list:
  analytics_admin = get_analytics_admin_client()
  response = analytics_admin.accounts().list().execute()
  account_id_list = []
  for account in response['accounts']:
    account_id_list.append(
        [((account['name']).split('/'))[1], account['displayName']]
    )

  return account_id_list


def get_ga4_property_ids(account_id) -> list:
  analytics_admin = get_analytics_admin_client()
  response = (
      analytics_admin.properties()
      .list(filter='parent:accounts/' + account_id)
      .execute()
  )
  property_id_list = []
  for properties in response['properties']:
    property_id_list.append(
        [((properties['name']).split('/'))[1], properties['displayName']]
    )

  return property_id_list


def get_ga4_data(property_id, date_from, date_to, items, raw_data):
  analytics = get_analytics_client()
  request = {
      'requests': [{
          'dateRanges': [{'startDate': date_from, 'endDate': date_to}],
          'dimensions': [{'name': 'date'}],
          'metrics': [{'name': name} for name in items],
          'limit': 100000,
          'order_bys': [{'dimension': {'dimensionName': 'date'}}],
      }]
  }

  response = (
      analytics.properties()
      .batchRunReports(property='properties/' + property_id, body=request)
      .execute()
  )
  headers = []
  for report in response.get('reports', []):
    for metHeaders in report.get('metricHeaders', []):
      headers.append(metHeaders.get('name'))
    for row in report.get('rows', []):
      for date in row.get('dimensionValues'):
        date = datetime.strptime(date.get('value'), '%Y%m%d').strftime(
            '%Y-%m-%d'
        )
      for idx, val in enumerate(row.get('metricValues')):
        if date in raw_data:
          raw_data[date].update({f'ga4_{headers[idx]}': val.get('value')})
        else:
          raw_data[date] = {f'ga4_{headers[idx]}': val.get('value')}

  return raw_data
