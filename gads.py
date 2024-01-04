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

import json, os
import textwrap
from flask import session
from google.ads.googleads.client import GoogleAdsClient
from fs_storage import get_value_session


def get_gads_client(mcc_id: str) -> GoogleAdsClient:
  main_creds = json.loads(get_value_session(session['session_id'], 'credentials'))
  creds = {
      "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
      "refresh_token": main_creds["refresh_token"],
      "client_id": main_creds["client_id"],
      "client_secret": main_creds["client_secret"],
      "use_proto_plus": True,
  }

  google_ads_client = GoogleAdsClient.load_from_dict(creds)
  if mcc_id:
    google_ads_client.login_customer_id = mcc_id

  return google_ads_client


def get_gads_data(mcc_id: str, customer_id: str, campaign_ids: list, date_from: str, date_to: str) -> dict:
  client = get_gads_client(mcc_id)
  ga_service = client.get_service("GoogleAdsService", version="v14")
  camp_filter = ""
  if not customer_id + "-0" in campaign_ids[0]:
    camp_filter = "AND campaign.id IN (" + (",").join(campaign_ids) + ")"

  query = textwrap.dedent(f"""
    SELECT segments.date, metrics.impressions, metrics.clicks, metrics.video_views, metrics.cost_micros, metrics.conversions, metrics.view_through_conversions FROM campaign
    WHERE segments.date BETWEEN '{date_from}' AND '{date_to}' {camp_filter}
    ORDER BY segments.date ASC
    """)

  response = ga_service.search_stream(customer_id=customer_id, query=query)
  response.service_reference = ga_service
  return response


def process_gads_responses(responses, metrics: list):
  final_d = {}
  counter = 0
  for response in responses:
    for batch in response:
      for row in batch.results:
        if row.segments.date in final_d:
          counter += 1
          final_d[row.segments.date].update(
              {
                  "gads_impressions": (
                      final_d[row.segments.date]["gads_impressions"]
                      + row.metrics.impressions
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_clicks": (
                      final_d[row.segments.date]["gads_clicks"]
                      + row.metrics.clicks
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_video_views": (
                      final_d[row.segments.date]["gads_video_views"]
                      + row.metrics.video_views
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_cost_micros": (
                      final_d[row.segments.date]["gads_cost_micros"]
                      + row.metrics.cost_micros
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_conversions": (
                      final_d[row.segments.date]["gads_conversions"]
                      + row.metrics.conversions
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_view_through_conversions": (
                      final_d[row.segments.date][
                          "gads_view_through_conversions"
                      ]
                      + row.metrics.view_through_conversions
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_ctr": (
                      final_d[row.segments.date]["gads_clicks"]
                      + row.metrics.clicks
                      and (
                          final_d[row.segments.date]["gads_clicks"]
                          + row.metrics.clicks
                      )
                      / (
                          final_d[row.segments.date]["gads_impressions"]
                          + row.metrics.impressions
                      )
                      or 0
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_average_cpc": (
                      final_d[row.segments.date]["gads_clicks"]
                      + row.metrics.clicks
                      and (
                          final_d[row.segments.date]["gads_cost_micros"]
                          + row.metrics.cost_micros
                      )
                      / (
                          final_d[row.segments.date]["gads_clicks"]
                          + row.metrics.clicks
                      )
                      or 0
                  )
              }
          )
          final_d[row.segments.date].update(
              {
                  "gads_average_cost": (
                      final_d[row.segments.date]["gads_cost_micros"]
                      and (
                          final_d[row.segments.date]["gads_cost_micros"]
                          + row.metrics.cost_micros
                      )
                      / counter
                      or 0
                  )
              }
          )
        else:
          final_d[row.segments.date] = {
              "gads_impressions": row.metrics.impressions,
              "gads_clicks": row.metrics.clicks,
              "gads_video_views": row.metrics.video_views,
              "gads_cost_micros": row.metrics.cost_micros,
              "gads_conversions": row.metrics.conversions,
              "gads_view_through_conversions": (
                  row.metrics.view_through_conversions
              ),
              "gads_ctr": (
                  row.metrics.impressions
                  and row.metrics.clicks / row.metrics.impressions
                  or 0
              ),
              "gads_average_cpc": (
                  row.metrics.clicks
                  and row.metrics.cost_micros / row.metrics.clicks
                  or 0
              ),
              "gads_average_cost": row.metrics.cost_micros,
          }

  for key in final_d:
    for metric in final_d[key].copy():
      if not metric[5 : len(metric)] in metrics:
        final_d[key].pop(metric)

  return final_d


def get_gads_campaigns(mcc_id: str, customer_id: str) -> list:
  client = get_gads_client(mcc_id)
  campaigns = []
  query = textwrap.dedent("""
    SELECT
        campaign.id,
        campaign.name 
    FROM campaign
    """)

  ga_service = client.get_service("GoogleAdsService", version="v14")

  response = ga_service.search(customer_id=customer_id, query=query)

  for googleads_row in response:
    campaign = googleads_row.campaign
    campaigns.append([campaign.name, campaign.id])

  return campaigns


def get_gads_customer_ids(mcc_id: str) -> list:
  client = get_gads_client(mcc_id)
  all_customer_ids = []
  query = textwrap.dedent("""
    SELECT
        customer_client.descriptive_name,
        customer_client.id
    FROM customer_client
    WHERE customer_client.level <= 1 AND customer_client.manager = FALSE
    """)

  ga_service = client.get_service("GoogleAdsService", version="v14")

  response = ga_service.search(customer_id=mcc_id, query=query)

  for googleads_row in response:
    customer_client = googleads_row.customer_client
    all_customer_ids.append(
        [customer_client.descriptive_name, customer_client.id]
    )

  return all_customer_ids


def get_gads_mcc_ids() -> list:
  client = get_gads_client("")
  all_mcc_ids = []
  customer_service = client.get_service("CustomerService")

  accessible_customers = customer_service.list_accessible_customers()
  resource_names = accessible_customers.resource_names
  for resource_name in resource_names:
    all_mcc_ids.append(resource_name.split("/")[1])

  return all_mcc_ids
