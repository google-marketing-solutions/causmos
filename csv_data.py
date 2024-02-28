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
from datetime import datetime
import logging
import pandas as pd

def get_csv_data(file) -> dict:
  try:
    fstring = file.read().decode('utf8')
    return [
        {k: v.replace(",", "") for k, v in row.items()}
        for row in csv.DictReader(fstring.splitlines(), skipinitialspace=True, quoting=csv.QUOTE_ALL)
    ]
  except ValueError as e:
    logging.exception(e)
    err = {'error':f'Error: {e}'}
    return err

def get_csv_columns(data: dict):
  keys_list = list(data[0].keys())
  date_column = ''
  string_columns = []
  for key in keys_list:
    if 'date' in key.lower():
      date_column = key
      keys_list.remove(key)
      break
  for rows in data:
    for key in keys_list:
      if key != date_column:
        if rows.get(key)=='':
          rows.update({key: "0"})
        if not rows.get(key).replace(".", "").isnumeric():
          string_columns.append(key)
          keys_list.remove(key)
  return keys_list, date_column, string_columns

def csv_get_date_range(data: dict, date_column: str, convert: bool):
  date_list = []
  for item in data:
    if date_column in item:
      if convert:
        date_obj = datetime.strptime(item[date_column], "%b %d %Y")
        item_to_add = date_obj.strftime("%Y-%m-%d")
      else:
        item_to_add = item[date_column]
      date_list.append(item_to_add)
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


def bm_merge_data(bm_data:dict, bm_settings: dict, raw_data:dict):

  df = pd.DataFrame.from_dict(bm_data)

  values_to_extract = list(set([val[1] for val in bm_settings['metrics']]))
  df[values_to_extract] = df[values_to_extract].apply(pd.to_numeric)

  for key in bm_settings['filters']:
    df = df.loc[(df[key].isin(bm_settings['filters'][key]))]

  fields = [bm_settings['date_column'], bm_settings['cov']]
  fields.extend(values_to_extract)
  summed_data = df[fields].groupby([bm_settings['date_column'], bm_settings['cov']])[values_to_extract].sum()
  summed_data = summed_data.reset_index()

  key_dict = summed_data.to_dict('records')
 
  for item in key_dict:
    for pairs in bm_settings['metrics']:
      if get_date_from_str(item[bm_settings['date_column']]) in raw_data:
        if pairs[0] == item[bm_settings['cov']]:
          raw_data[get_date_from_str(item[bm_settings['date_column']])].update(
            {f"bm_{pairs[0]}[{pairs[1]}]": item[pairs[1]]}
          )
      else:
        if pairs[0] == item[bm_settings['cov']]:
          raw_data[get_date_from_str(item[bm_settings['date_column']])] = (
            {f"bm_{pairs[0]}[{pairs[1]}]": item[pairs[1]]}
          )
  return raw_data

def get_date_from_str(date):
  return datetime.strptime(date, "%b %d %Y").strftime("%Y-%m-%d")