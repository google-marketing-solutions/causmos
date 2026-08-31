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

Contains the methods for accessing data in BigQuery.
"""

import json
import logging
import re
from google.cloud import bigquery
from google.oauth2.credentials import Credentials
from flask import session
from fs_storage import get_value_session

_ROW_LIMIT = 10000

# BigQuery identifiers are limited to letters, numbers, underscores and
# dashes. Anything else cannot be a valid project, dataset or table name and
# is rejected before it reaches the query string.
_BQ_IDENTIFIER = re.compile(r'^[\w-]+$', re.UNICODE)


def _validate_bq_location(bq_full_location: str) -> str:
  """Validates a fully qualified BigQuery table location.

  BigQuery query parameters can only stand in for values, never for
  identifiers, so the table name has to be part of the query text. This
  check makes sure only a well formed project.dataset.table can get there.

  Args:
    bq_full_location: The location in project_id.dataset_name.table_name
    format.

  Returns:
    The validated location.

  Raises:
    ValueError: If the location is not three valid identifiers.
  """
  parts = bq_full_location.split('.')
  if len(parts) != 3 or not all(_BQ_IDENTIFIER.match(p) for p in parts):
    raise ValueError(
      'Invalid BigQuery location. Expected project_id.dataset_name.table_name'
    )
  return bq_full_location


def _get_raw_bq_data(bq_full_location) -> dict:
  """Gets the raw data from the BigQuery location.

  Args:
    bq_full_location: The full location of the BigQuery table in the
    format project_id.dataset_name.table_name

  Returns:
    The BigQuery data in a dictionary format.

  Raises:
    ValueError: If the location is invalid or the session credentials
    cannot be read.
  """
  bq_full_location = _validate_bq_location(bq_full_location)

  try:
    creds_info = json.loads(
      get_value_session(session['session_id'], 'credentials'))
  except (ValueError, TypeError) as e:
    logging.exception(e)
    raise ValueError('Could not read the session credentials') from e

  creds = Credentials.from_authorized_user_info(creds_info)

  client = bigquery.Client(credentials=creds)
  query = f'select * from `{bq_full_location}` LIMIT {_ROW_LIMIT}'
  query_job = client.query(query)
  final_bq_data = []
  for row in query_job:
    formatted_row = {}
    for key in row.keys():
      formatted_row[key] = row[key]
    final_bq_data.append(formatted_row)

  return final_bq_data
