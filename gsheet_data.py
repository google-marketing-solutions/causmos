from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json
from fs_storage import get_value_session
from flask import session

def get_raw_gsheet_data(sheet_id):
  sheet_err=['error']
  try:
    creds_info = json.loads(get_value_session(session['session_id'], 'credentials'))
    creds = Credentials.from_authorized_user_info(creds_info)
    service = build("sheets", "v4", credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()
    result = (
        sheet.values()
        .get(spreadsheetId=sheet_id, range="A:ZZ")
        .execute()
    )
    values = result.get("values", [])
    final_gsheet = []

    headers = values.pop(0)
    for row in values:
        temp_data = {}
        for inx, item in enumerate(headers):
            temp_data[item] = row[inx]
        final_gsheet.append(temp_data)
       
    return final_gsheet

  except:
    sheet_err.append('Requires access to sheet or sheet has data without headers')
    return sheet_err


