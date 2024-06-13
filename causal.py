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

"""Causal impact library.

Contains all the Causal Impact methods for creating a Causal Impact
report, summary and charts.
"""

import re
import causalimpact
from google.cloud import storage
from matplotlib.colors import LinearSegmentedColormap
from project_secrets import get_secret

_TEMP_FOLDER = "/tmp/"


def get_causal_impact_object(
  df, pre_period: list, post_period: list, credibility: float
) -> list:
  """Gets a Causal Impact object for analysis.

  Args:
    df: The data for the model in dataframe format.
    pre_period: The index range of the pre-period data.
    post_period: The index range of the post-period data.
    credibility: The confidence level the model needs to run with.

  Returns:
    The causal impact object output as a list.
  """
  return causalimpact.fit_causalimpact(
    data=df, pre_period=pre_period, post_period=post_period, alpha=credibility
  )


def get_causal_impact_summary(impact: list, credibility: float) -> list:
  """Creates a summary text of the created Causal Impact model.

  Args:
    impact: The Casual Impact object from the created model.
    credibility: The confidence level the model needs to run with.

  Returns:
    The modelled data output as a list.
  """
  summary = causalimpact.summary(impact, output_format="summary", alpha=credibility)
  summary = re.sub("  +", "|", summary)
  output = [r.split("|") for r in [r for r in summary.split("\n")]]
  if len(output[4]) == 2:
    tmp_ = output[4][1].split(")", 1)
    output[4][1] = tmp_[0] + ")"
    output[4].append(tmp_[1])
  if len(output[5]) == 2:
    tmp_ = output[5][1].split("]", 1)
    output[5][1] = tmp_[0] + "]"
    output[5].append(tmp_[1])
  if len(output[7]) == 2:
    tmp_ = output[7][1].split(")", 1)
    output[7][1] = tmp_[0] + ")"
    output[7].append(tmp_[1])
  if len(output[8]) == 2:
    tmp_ = output[8][1].split("]", 1)
    output[8][1] = tmp_[0] + "]"
    output[8].append(tmp_[1])
  return output


def get_causal_impact_chart(impact, div="vis", store_img=False, image_name="") -> str:
  """Gets a HTML Chart output of the created Causal Impact model.

  Args:
    impact: The Casual Impact object from the created model.
    div: Unique ID for each individual HTML div for multiple runs of the model.
    store_img: Boolean to check if the image needs to be saved for slide output.
    image_name: The unique ID for the image name to be stored in GCP.

  Returns:
    The HTML output of the Casual Impact charts.
  """
  ci = causalimpact.plot(impact, static_plot=False, chart_width=800)
  if store_img:
    ci.save(_TEMP_FOLDER + image_name, engine="vl-convert")
    storage_client = storage.Client()
    bucket = storage_client.bucket(get_secret("image_bucket"))
    blob = bucket.blob(image_name)
    blob.cache_control = "private"
    blob.upload_from_filename(_TEMP_FOLDER + image_name)
  return ci.to_html().replace("vis", div)


def get_causal_impact_report(impact, credibility: float) -> str:
  """Gets a detailed report of the Causal Impact model.

  Args:
    impact: The Casual Impact object from the created model.
    credibility: The confidence level the model needs to run with.

  Returns:
    The text report of the Causal Impact model.
  """
  return causalimpact.summary(impact, output_format="report", alpha=credibility)


def get_df_matrix(df) -> str:
  """Gets a matrix output of the covariates and target event.

  Args:
    df: The data for the model in dataframe format.

  Returns:
    The matrix table in string format.
  """
  df_matrix = df[df.columns[0:9]].corr(method="pearson", numeric_only=False)
  df_matrix = df_matrix.abs()
  segments = [(0, "green"), (1, "white")]
  cmap = LinearSegmentedColormap.from_list("", segments)
  df_matrix = df_matrix.style.background_gradient(
    cmap=cmap, low=1, high=0, axis=None)

  return df_matrix.to_html().replace(
    "<table", '<table class="bordered-table opp"')


def get_validation(df) -> list:
  """Creates a summary of the data in the dataframe to validate its
  ranges and input.

  Args:
    df: The data for the model in dataframe format.

  Returns:
    The data validation table.
  """
  validation = str(df.describe())
  validation = re.sub("  +", "|", validation)
  return [r.split("|") for r in [r for r in validation.split("\n")]]
