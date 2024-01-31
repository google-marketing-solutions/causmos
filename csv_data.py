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

import csv

def get_csv_data(file) -> dict:
  try:
    fstring = file.read().decode('utf8')
    return [
        {k: v.replace(",", "") for k, v in row.items()}
        for row in csv.DictReader(fstring.splitlines(), skipinitialspace=True, quoting=csv.QUOTE_ALL)
    ]
  except:
    return "{'error':'File format isn't in CSV or some columsn misaligned. Checked file and try again.'}"


def get_csv_columns(data: dict):
  keys_list = list(data[0].keys())
  date_column = ''
  for key in keys_list:
    if 'date' in key.lower():
      date_column = key
      break
  return keys_list, date_column


def csv_get_date_range(data: dict, date_column: str):
  date_list = []
  for item in data:
    if date_column in item:
      date_list.append(item[date_column])
  return min(date_list), max(date_list)


def csv_merge_data(csv_data: dict, csv_settings: dict, raw_data: dict) -> dict:
  for item in csv_data:
    if item[csv_settings['date_column']] in raw_data:
      for col in csv_settings['metrics']:
        raw_data[item[csv_settings['date_column']]].update(
            {f'csv_{col}': item[col]}
        )
    else:
      for col in csv_settings['metrics']:
        if item[csv_settings['date_column']] in raw_data:
          raw_data[item[csv_settings['date_column']]].update(
              {f'csv_{col}': item[col]}
          )
        else:
          raw_data[item[csv_settings['date_column']]] = {
              f'csv_{col}': item[col]
          }

  return raw_data
