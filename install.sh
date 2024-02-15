# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This is the main installation script for Product DSA in GCP environment.
# It installs a GAE Web App (using install-web.sh) and
# grant the GAE service account additional roles required for executing setup.
# Setup itself is executed from within the application (or via setup.sh).

COLOR='\033[0;36m' # Cyan
RED='\033[0;31m' # Red Color
NC='\033[0m' # No Color

PROJECT_ID=$(gcloud config get-value project 2> /dev/null)
PROJECT_TITLE='Causal Impact Insights'
USER_EMAIL=$(gcloud config get-value account 2> /dev/null)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID | grep projectNumber | sed "s/.* '//;s/'//g")
SERVICE_ACCOUNT=$PROJECT_ID@appspot.gserviceaccount.com
GAE_LOCATION=europe-west
FIRESTORE_SA='firebase-service-account@firebase-sa-management.iam.gserviceaccount.com'

# check the billing
BILLING_ENABLED=$(gcloud beta billing projects describe $PROJECT_ID --format="csv(billingEnabled)" | tail -n 1)
if [[ "$BILLING_ENABLED" = 'False' ]]
then
  echo -e "${RED}The project $PROJECT_ID does not have a billing enabled. Please activate billing${NC}"
  exit
fi

echo -e "${COLOR}Enabling APIs...${NC}"
gcloud services enable appengine.googleapis.com
gcloud services enable iap.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com
gcloud services enable iamcredentials.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable googleads.googleapis.com
gcloud services enable analyticsadmin.googleapis.com
gcloud services enable analyticsdata.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable sheets.googleapis.com
gcloud services enable slides.googleapis.com
gcloud services enable drive.googleapis.com

gcloud app create --region $GAE_LOCATION

cp app.yaml app.yaml

echo -e "${COLOR}Deploying app to GAE...${NC}"
# next command often fails in new projects with "NOT_FOUND: Unable to retrieve P4SA" error, just wait and run again afterwards
gcloud app deploy -q

# Grant GAE service account with the Service Account Token Creator role so it could create GCS signed urls
gcloud projects add-iam-policy-binding $PROJECT_ID --member=serviceAccount:$SERVICE_ACCOUNT --role=roles/iam.serviceAccountTokenCreator

# create IAP
echo -e "${COLOR}Creating oauth brand (consent screen) for IAP...${NC}"
gcloud iap oauth-brands create --application_title="$PROJECT_TITLE" --support_email=$USER_EMAIL

# create OAuth client for IAP
echo -e "${COLOR}Creating OAuth client for IAP...${NC}"
# TODO: ideally we need to parse the response from the previous command to get brand full name
gcloud iap oauth-clients create projects/$PROJECT_NUMBER/brands/$PROJECT_NUMBER --display_name=iap \
  --format=json 2> /dev/null |\
  python3 -c "import sys, json; res=json.load(sys.stdin); i = res['name'].rfind('/'); print(res['name'][i+1:]); print(res['secret'])" \
  > .oauth
# Now in .oauth file we have two line, first client id, second is client secret
lines=()
while IFS= read -r line; do lines+=("$line"); done < .oauth
IAP_CLIENT_ID=${lines[0]}
IAP_CLIENT_SECRET=${lines[1]}

TOKEN=$(gcloud auth print-access-token)

echo -e "${COLOR}Enabling IAP for App Engine...${NC}"
curl -X PATCH -H "Content-Type: application/json" \
 -H "Authorization: Bearer $TOKEN" \
 --data "{\"iap\": {\"enabled\": true, \"oauth2ClientId\": \"$IAP_CLIENT_ID\", \"oauth2ClientSecret\": \"$IAP_CLIENT_SECRET\"} }" \
 "https://appengine.googleapis.com/v1/apps/$PROJECT_ID?alt=json&update_mask=iap"

# Grant access to the current user
echo -e "${COLOR}Granting user $USER_EMAIL access to the app through IAP...${NC}"
gcloud iap web add-iam-policy-binding --resource-type=app-engine --member="user:$USER_EMAIL" --role='roles/iap.httpsResourceAccessor'

echo -e "${COLOR}Creating Firestore database...${NC}"
gcloud firestore databases create --location=eur3

echo -e "${COLOR}Granting service account access...${NC}"
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$FIRESTORE_SA" \
    --role="roles/firebase.managementServiceAgent"

USER_DOMAIN=$(echo $USER_EMAIL | sed 's/^.*@\(.*\)/\1/')
if [ "$USER_DOMAIN" != "gmail.com" ]; then
  gcloud alpha iap web add-iam-policy-binding --resource-type=app-engine --member="domain:$USER_DOMAIN" --role='roles/iap.httpsResourceAccessor'
fi


echo -e "\n${COLOR}Done! Please verify the install at https://$PROJECT_ID.ew.r.appspot.com${NC}"