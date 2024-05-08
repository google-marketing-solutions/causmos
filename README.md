# Causmos: Causal Impact for Google Ads & Analytics Reporting

### What is Causmos?

Causal Impact compares the observed values for a KPI after an intervention occurs to the predicted values for the same KPI assuming that the intervention did not occur. The difference between observed and predicted is the true impact (causal effect) of an intervention.

Causmos is an open-source web app that streamlines the process of running a Causal Impact analysis.

The Causmos solution is a Web App on Google Cloud App Engine that uses the logged in user's credentials to connect to Google Ads, Google Analytics, and Google Sheets. A CSV upload option is provided should a user need to add additional data.

![Causmos One Pager](https://services.google.com/fh/files/helpcenter/causmos-one-pager.png)


### Installation

1. Prepare Google Cloud project and check that billing is enabled

2. Create [OAuth Client ID Credentials](https://console.cloud.google.com/apis/credentials) and download the JSON file (you may need to create the Consent screen first).

3. Clone the repo in cloud console using the following command:
```
git clone https://github.com/google-marketing-solutions/causmos.git
```

4. Once cloned, modify your SLIDE_TEMPLATE variable in the app.yaml if you want a default slide template for exporting. This should be the Google Slide ID (the ID after the /d/ in the URL)

5. Run the install.sh in your cloud console using the following command. This will enable the APIs, enable app engine, install the app and update any current users to IAP. This can take up to 10 minutes, so please wait until it has finished running. 
```
chmod u+x install.sh
./install.sh
```

6. Once installed, add the following secret keys to your project Secret Manager:
    - client_secret - Upload your client_secret.json file to this secret
    - flask_secret_key - The secret key for your Flask instance (random security key). For more info, visit [Flask Security Key page](https://flask.palletsprojects.com/en/2.3.x/config/#SECRET_KEY)
    - developer_token - The developer token found in the [API Center](https://ads.google.com/aw/apicenter) of your Google Ads account
    - image_bucket - A publicly viewable folder. Must add allUsers as **Storage Object Viewer** and your service account as a **Storage Object User**

7. You can grant users access in IAM settings in Cloud and granting them the role **IAP-secured Web App User**. Required even for project owners/editors! If you want to open the application to anyone and not use IAP, you can disable IAP under the [Identity-Aware Proxy](https://pantheon.corp.google.com/security/iap) settings in Cloud by unchecking it. 

8. Finally, grant your service account the role **Secret Manager Secret Accessor** . You can also check that they also have **Firestore Service Agent** and **Firebase Rules System** (which should have been done by the install script)
---

**Please note: this is not an officially supported Google product.**
