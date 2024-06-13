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

"""BigQuery data access methods.

Contains the methods for accessing daya in BigQuery
"""

import json
import logging
from google.cloud import bigquery
from google.oauth2.credentials import Credentials
from flask import session
from fs_storage import get_value_session


def _get_raw_bq_data(bq_full_location) -> dict:
    """Gets the raw data from the BigQuery location

  Args:
    bq_full_location: The full location of the BigQuery bucket in the
    format project_id.dataset_name.table_name

  Returns:
    The BigQuery data in a dictionary format
  """
    try:
      creds_info = json.loads(get_value_session(
      session['session_id'], 'credentials'))
    except ValueError as e:
      logging.exception(e)

    creds = Credentials.from_authorized_user_info(creds_info)

    client = bigquery.Client(credentials=creds)
    query = f"""
select * from `{bq_full_location}` LIMIT 10000
"""
    query_job = client.query(query)
    final_bq_data = []
    for row in query_job:
        formatted_row = {}
        for key in row.keys():
            formatted_row[key] = row[key]
            final_bq_data.append(formatted_row)

    return final_bq_data