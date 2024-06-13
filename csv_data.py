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

"""CSV data formatting and extracting.

Contains all the CSV functions for reading the data and extracting
the metrics and dimensions.
"""

import csv
from datetime import datetime
import logging
import pandas as pd


def get_csv_data(file) -> dict:
  """Gets the data from an uploaded CSV file.

  Args:
    file: The file of the CSV file.

  Returns:
    The data from the CSV data as a dictionary.
  """
  try:
    fstring = file.read().decode("utf8")
    return [
      {k: v.replace(",", "") for k, v in row.items()}
      for row in csv.DictReader(
        fstring.splitlines(), skipinitialspace=True, quoting=csv.QUOTE_ALL
      )
    ]
  except ValueError as e:
    logging.exception(e)
    err = {"error": f"Error: {e}"}
    return err


def get_csv_columns_by_type(data: dict) -> tuple[list, str, list]:
  """Gets the CSV or Sheet columns data and returns a list of values for the
  date column,
  the numerical columns and the text based columns.

  Args:
    data: The raw CSV data from the file upload or reading of the Google sheet.

  Returns:
    List of dates, list of numerical columns and list of text based columns as
    a Tuple.
  """
  keys_list = list(data[0].keys())
  date_column = ""
  string_columns = []
  for key in keys_list:
    if "date" in key.lower():
      date_column = key
      keys_list.remove(key)
      break
  for rows in data:
    for key in keys_list:
      if key != date_column:
        if rows.get(key) == "":
          rows.update({key: "0"})
        if not str(rows.get(key)).replace(".", "").isnumeric():
          string_columns.append(key)
          keys_list.remove(key)
  return keys_list, date_column, string_columns


def csv_get_date_range(data: dict, date_column: str,
                       convert: bool) -> tuple[str, str]:
  """Gets the range of the dates for the start of and end of date values.

  Args:
    data: The raw CSV data from the file upload or reading of the Google sheet.
    date_column: The column the dates are in.
    convert: Converts date format from Connect Benchmarks to standard format if
    true.

  Returns:
    Returns the minimum and maximum date.
  """
  date_list = []
  for item in data:
    if date_column in item:
      if convert:
        date_obj = datetime.strptime(item[date_column], "%b %d %Y")
        item_to_add = date_obj.strftime("%Y-%m-%d")
      else:
        item_to_add = item[date_column]
      date_list.append(item_to_add)
  return str(min(date_list)), str(max(date_list))


def csv_merge_data(csv_data: dict, csv_settings: dict, raw_data: dict, pre_tag: str) -> dict:
  """Merges the CSV and Google sheets data with the raw data object.

  Args:
    csv_data: The raw CSV data from the file upload or reading of the Google
    sheet.
    csv_settings: The settings that have been defined by the user (date ranges,
    event date, target event etc.).
    raw_data: The overall raw data from other datasources to be merged with the
    CSV/sheet data.

  Returns:
      The raw data with all CSV/sheet data merged.
  """
  for item in csv_data:
    if item[csv_settings["date_column"]] in raw_data:
      for col in csv_settings["metrics"]:
        raw_data[item[csv_settings["date_column"]]].update(
          {f"{pre_tag}_{col}": item[col]}
        )
    else:
      for col in csv_settings["metrics"]:
        if item[csv_settings["date_column"]] in raw_data:
          raw_data[item[csv_settings["date_column"]]].update(
            {f"{pre_tag}_{col}": item[col]}
          )
        else:
          raw_data[item[csv_settings["date_column"]]] = {
            f"{pre_tag}_{col}": item[col]
          }
  return raw_data


def get_date_from_str(date) -> str:
  """Converts the Connect Benchmark date format to the yyyy-mm-dd.

  Args:
    date: CB date in the MMM dd yyyy format.

  Returns:
    The date in the yyyy-mm-dd format.
  """
  return datetime.strptime(date, "%b %d %Y").strftime("%Y-%m-%d")
