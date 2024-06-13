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

"""Project Secret access.

Contains all the methods for access the secret keys in the GCP
Project Secret Manager.
"""

import logging
import os
from google.cloud import secretmanager

def get_secret(secret_id) -> str:
  """Gets the client secret value from a provided ID.

  Args:
    secret_id: The name of the secret to retrieve.

  Returns:
    Secret value as a string.
  """
  client = secretmanager.SecretManagerServiceClient()
  project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
  name = client.secret_path(project_id, secret_id)
  name = f'{name}/versions/latest'
  try:
    response = client.access_secret_version(request={'name': name})
    secret = response.payload.data.decode('UTF-8')
  except Exception as e:
    logging.exception(e)
    return None
  return secret
