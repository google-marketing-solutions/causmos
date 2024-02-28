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


import datetime
import re
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from fs_storage import get_value_session
from flask import session
from fs_storage import get_value_session
import json, os
import logging
from project_secrets import get_secret

def create_slide(session_id="", slide_id=os.environ.get('SLIDE_TEMPLATE'), client_name="", prepend=False, main_url=""):
    try:
        creds_info = json.loads(get_value_session(session['session_id'], 'credentials'))
    except ValueError as e:
        logging.exception(e)
    creds = Credentials.from_authorized_user_info(creds_info)
    slides_service = build('slides', 'v1', credentials=creds)
    drive_service  = build('drive',  'v3', credentials=creds)

    body = {"name": f"{client_name} - Causal Impact Insights"}
    try:
        drive_response = (
            drive_service.files().copy(fileId=slide_id, body=body).execute()
        )
        slide_copy_id = drive_response.get("id")
    except ValueError as e:
        logging.exception(e)
        return "Error creating copy of slides"
    
    request_data = get_value_session(session_id, 'output_data')

    target_event = request_data['target_event']
    covariates = request_data['covariates']
    if prepend:
        target_event = re.sub(r'^.*?_', '', target_event)
        covariates = ", ".join([re.sub(r'^.*?_', '', cov) for cov in covariates.split(",")])

    to_replace = [
        ['CLIENT_NAME', client_name], 
        ['DATE', datetime.date.today().strftime("%d-%m-%Y")],
        ['TARGET_EVENT', target_event],
        ['COVARIATES', covariates],
        ['PREPERIOD-START', request_data['from_date']],
        ['PREPERIOD-END', (datetime.datetime.strptime(request_data['event_date'], "%Y-%m-%d") - datetime.timedelta(days=1)).strftime("%Y-%m-%d")],
        ['POSTPERIOD-START', request_data['event_date']],
        ['POSTPERIOD-END', request_data['to_date']],
        ['P_VALUE', request_data['p_value']],
        ['INCR_ACTIONS', request_data['tot_inc']],
        ['RELATIVE_EFFECT', request_data['rel_eff']],
        ['SUMMARY', request_data['summary']],
        ['REPORT', request_data['report']]
    ]
    requests = []
    for label in to_replace:
        requests.append({
            'replaceAllText': {
                'replaceText': label[1],
                'containsText': {
                    'matchCase': False,
                    'text': f'{{{{{label[0]}}}}}'
                }
            }
        })

    page_id = ""
    final_element = ""
    presentation = (slides_service.presentations().get(presentationId=slide_copy_id).execute())
    slides = presentation.get("slides")
    for slide in slides:
        elements = slide.get('pageElements')
        if elements:
            for element in elements:
                if element.get("description") == "CHART":
                    page_id = slide['objectId']
                    final_element = element
                    break;  
    
    add_img = {
            "createImage": {
            "objectId": "my_id",
            "url": f"https://storage.googleapis.com/{get_secret('image_bucket')}/{request_data['image_name']}",
            "elementProperties": {
                "pageObjectId": page_id,
                'size': {
                        
                },
                'transform': {
                    
                },
            },
        }
    }
    add_img['createImage']['elementProperties']['size'] = final_element['size']
    add_img['createImage']['elementProperties']['transform'] = final_element['transform']
    requests.append(add_img)
    try:
        response = slides_service.presentations().batchUpdate(
            body={'requests': requests},
            presentationId=slide_copy_id
        ).execute()
    except ValueError as e:
        logging.exception(e)
        return "Slides error"

    return slide_copy_id
    
    