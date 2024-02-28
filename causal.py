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

import re
from uuid import uuid4
import causalimpact
from google.cloud import storage
from matplotlib.colors import LinearSegmentedColormap
from project_secrets import get_secret

_TEMP_FOLDER = "/tmp/"

def getCiObject(df, pre_period: list, post_period: list, credibility: float):
  return causalimpact.fit_causalimpact(data=df, pre_period=pre_period, post_period=post_period,  alpha=credibility)

def getCiSummary(impact, credibility: float) -> list:
  summary = causalimpact.summary(impact, output_format='summary', alpha=credibility)
  summary = re.sub('  +', '|', summary)
  return [r.split('|') for r in [r for r in summary.split('\n')]]

def getCiChart(impact, div="vis", img=False, image_name=""):
  ci = causalimpact.plot(impact, static_plot=False, chart_width=800)
  if img:
    ci.save(_TEMP_FOLDER+image_name, engine="vl-convert")
    storage_client = storage.Client()
    bucket = storage_client.bucket(get_secret('image_bucket'))
    blob = bucket.blob(image_name)
    blob.cache_control="private"
    blob.upload_from_filename(_TEMP_FOLDER+image_name)
  return ci.to_html().replace("vis", div)

def getCiReport(impact, credibility: float) -> str:
  return causalimpact.summary(impact, output_format='report',  alpha=credibility)

def getDfMatrix(df) -> str:
  df_matrix = df[df.columns[0:9]].corr(method='pearson', numeric_only=False)
  df_matrix = df_matrix.abs()
  segments = [(0, 'green'), (1, 'white')]
  cmap = LinearSegmentedColormap.from_list("", segments)
  df_matrix = df_matrix.style.background_gradient(cmap=cmap, low=1, high=0, axis=None)

  return df_matrix.to_html().replace('<table', '<table class="bordered-table opp"') #.replace('<thead', '<thead class="full-table-border opp"').replace("<tbody", "<tbody class='full-table-border opp'")

def getValidation(df) -> list:
  validation=str(df.describe())
  validation = re.sub('  +', '|', validation)
  return [r.split('|') for r in [r for r in validation.split('\n')]]
