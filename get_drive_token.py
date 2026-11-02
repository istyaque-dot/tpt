"""Run ONCE on your own computer to connect Google Drive.

    pip install google-auth-oauthlib
    python get_drive_token.py client_secret.json

A browser opens -> log in with the Gmail you want documents stored in -> Allow.
It prints client_id / client_secret / refresh_token: paste them into Streamlit secrets under [google_drive].
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

if len(sys.argv) != 2:
    print("Usage: python get_drive_token.py client_secret.json")
    sys.exit(1)

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")

print("\n----- paste this into Streamlit secrets -----\n")
print("[google_drive]")
print(f'client_id = "{client["client_id"]}"')
print(f'client_secret = "{client["client_secret"]}"')
print(f'refresh_token = "{creds.refresh_token}"')
