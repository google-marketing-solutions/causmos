# Copyright 2024 Google LLC.
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

"""Google Sheets methods.

Contains the methods for accessing Google Sheets, extracting the data,
metircs and dimensions.
"""

import json
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from flask import session
from fs_storage import get_value_session


def get_raw_gsheet_data(sheet_id, sheet_name='', gid=0) -> tuple[
  list, list, str]:
  """Gets the raw data from the Google sheets specified by the user.

  Args:
    sheet_id: The ID of the Google sheet to retrieve.
    sheet_name: The name of the specific tab to use, if specified.
    gid: Alternative to sheet name, if the user provides a tab ID (gid) in the
    URL.

  Returns:
    The raw sheet data, a list of all tabs in the sheet and the tab being used.
  """
  sheet_err = ['error']
  try:
    creds_info = json.loads(get_value_session(
      session['session_id'], 'credentials'))
  except ValueError as e:
    logging.exception(e)
    sheet_err.append(
      f'Sheet does not exist or is invalid - Make sure the \
        tab \'{sheet_name}\' exists'
    )
    return sheet_err, 'error'

  creds = Credentials.from_authorized_user_info(creds_info)
  service = build('sheets', 'v4', credentials=creds)
  # Call the Sheets API
  sheet = service.spreadsheets()
  sheets = sheet.get(spreadsheetId=sheet_id).execute().get('sheets', [])
  sheet_names = [sheet['properties']['title'] for sheet in sheets]
  if sheet_name:
    sheet_range = f"'{sheet_name}'!A:ZZ"
  elif gid > 0:
    sheet_name = [
      sheet['properties']['title']
      for sheet in sheets
      if sheet['properties']['sheetId'] == gid
    ][0]
    sheet_range = f"'{sheet_name}'!A:ZZ"
  else:
    sheet_name = ''
    sheet_range = 'A:ZZ'
  try:
    result = sheet.values().get(spreadsheetId=sheet_id,
                      range=sheet_range).execute()
    values = result.get('values', [])
    final_gsheet = []
    headers = values.pop(0)
    header_count = len(headers)
    for row in values:
      temp_data = {}
      row_add = header_count - len(row)
      if row_add != 0:
        for x in range(row_add):
          row.append('0')
      for inx, item in enumerate(headers):
        if row[inx] == '':
          row[inx] = '0'
        temp_data[item] = row[inx].replace(',', '')
      final_gsheet.append(temp_data)
  except Exception as e:
    logging.exception(e)
    sheet_err.append(
      f'Sheet does not exist or is invalid - Make sure the \
         tab \'{sheet_name}\' exists'
    )
    return sheet_err, 'error', ''
  return final_gsheet, sheet_names, sheet_name
