
# ONE-TIME LOCAL SETUP — run this on your own machine, never in Actions.
# Produces YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN for GitHub Secrets.

import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# 1. Go to https://console.cloud.google.com
#    - Create project -> Enable "YouTube Data API v3"
#    - OAuth consent screen: set to PRODUCTION (not "Testing"!) and add
#      yourself as a test user. Testing mode refresh tokens die after 7 days.
#    - Create OAuth Client ID: type "Desktop app"
#    - Download the JSON, save it next to this file as client_secret.json
flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0)

print("Put these three values into GitHub Secrets (repo -> Settings -> Secrets):")
print()
print("YT_CLIENT_ID =", creds.client_id)
print("YT_CLIENT_SECRET =", creds.client_secret)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
