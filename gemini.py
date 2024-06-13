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

"""Gemini AI methods.

Contains the methods to access Gemini AI insights, formatting of the prompts,
and returning the data.
"""

import re
import vertexai
from vertexai.generative_models import GenerativeModel
import vertexai.preview.generative_models as generative_models

def ai_insights(orignal, pre_period, unaffectedness, project_id) -> str:
  """Gets a response from Gemini AI based on the Causal Impact studies and
  validation
  tests that were run to help show insight into the overall analysis.

  Args:
    original: The original Causal Impact studie results table.
    pre_period: The pre_period validation Causal Impact studie results table.
    unaffectedness: The unaffectedness validation Causal Impact studie results
    table.
    project_id: The GCP project ID.

  Returns:
    A string response from Gemini on the analysis insights.
  """
  generation_config = {
    'max_output_tokens': 2048,
    'temperature': 1,
    'top_p': 1,
    'response_mime_type': 'application/json'
  }
  safety_settings = {
    generative_models.HarmCategory.HARM_CATEGORY_HATE_SPEECH:
    generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT:
    generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT:
    generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_HARASSMENT:
    generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
  }
  format_string = """
    Respond using JSON schema: {"type": "object", "properties": { "insight_overview": {"type": "string"},
      "overall_conclusion": {"type": "string"}
    """
  query = f"""
    Imagine the end user is not familiar with statistics, provide a summary of insights into this causal impact study and how it performed and put the text into the
      insight_overview variable. Can you call out the uplift in performance and the confidence of the analysis but do not
        worry about the underlying data or date ranges.
        {orignal}
    """
  if pre_period:
    query += f"""
    Here is a pre-period analysis to check if there is any incremental impact before the intervention took place
      which you can use to compare and put the text into the pre_period_overview variable. To give you context, a Pre-Period
        Validation test takes the pre-period from your Causal Impact analysis and does a 75/25% split of the date range as a
          new pre and post-period to confirm if there are any natural causal impact during the period before the target event happened. -
    {pre_period}
    """
    format_string += ',"pre_period_overview": {"type": "string"}'
  if unaffectedness:
    query += f"""
    Here is an unaffectedness check to see if one of the covariates used in the original analysis, when now used
      as a target event, shows any causal impact impact which you can use to compare and put the text into the unaffectedness_overview
        variable. To give you context, an Unaffectedness Validation test removes the target event from the data, and uses one of the
          covariates as a new target event to ensure there is no natural causal impact with other events over the same date period
            as your original Causal Impact analysis. -
    {unaffectedness}
    """
    format_string += ',"unaffectedness_overview": {"type": "string"}'

  query += """
  And please provide an overall conclusion considering all the tests and put it into the overall_conclusion variable.
  Only use English language.
  """
  format_string += '}} using JSON formatting and escaping \
    any control characters.'

  vertexai.init(project=project_id, location='europe-west2')
  model = GenerativeModel('gemini-1.0-pro-002')
  responses = model.generate_content(
    [query+format_string],
    generation_config=generation_config,
    safety_settings=safety_settings,
    stream=True,
  )
  final_response = ''
  for response in responses:
    final_response += response.text
  re.sub(r'\\.', '', final_response)
  return final_response
