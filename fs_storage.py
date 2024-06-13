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

"""Firestore storage methods and access.

Contains the methods for accessing the Firestore properties and
individual values.
"""

from firebase_admin import credentials, firestore
import firebase_admin

cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred)
db = firestore.Client()

SESSION_NAME = 'sessions'


def get_value_session(session_id: str, name: str) -> any:
  """Gets the value stored from the session based on the name of the value.

  Args:
    session_id: The ID of the session for the user.
    name: The name of the session value to return.

  Returns:
    The session value.
  """
  cs_ref = db.collection(SESSION_NAME).document(session_id)
  if cs_ref.get().exists:
    if name in cs_ref.get().to_dict():
      return cs_ref.get().to_dict()[name]
    return None


def set_value_session(session_id: str, name: str, value: any):
  """Sets the name-value pair into the session storage.

  Args:
    session_id: The ID of the session for the user.
    name: The name of the session value to return.
    value: The value to store in the session name.
  """
  doc_ref = db.collection(SESSION_NAME).document(session_id)
  doc_ref.set({name: value,
               'last_updated': firestore.SERVER_TIMESTAMP}, merge=True)


def delete_field(session_id: str, field: str):
  """Deletes a session field from the session storage.

  Args:
    session_id: The ID of the session for the user.
    field: The name of the session value to delete from storage.
  """
  doc_ref = db.collection(SESSION_NAME).document(session_id)
  doc_ref.update({field: firestore.DELETE_FIELD})
