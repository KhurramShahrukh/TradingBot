"""
get_gmail_token.py — Run ONCE on your local machine to generate Gmail OAuth2 tokens.

Steps:
  1. Follow the Google Cloud Console setup guide (see README or chat instructions).
  2. Download credentials.json into this project folder.
  3. Run:  python get_gmail_token.py
  4. Copy the URL printed in the terminal and open it in your browser.
  5. Log in with khurramshahrukh18@gmail.com, click Allow, then come back to the terminal.
  6. Copy the three values printed at the end into your .env file.

This script is only needed once. The refresh token never expires unless you
revoke access in your Google account settings.
"""

import json
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("ERROR: google-auth-oauthlib is not installed.")
    print("Run:  pip install google-auth-oauthlib")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"

if not CREDENTIALS_FILE.exists():
    print("ERROR: credentials.json not found in the project folder.")
    print("Download it from Google Cloud Console:")
    print("  APIs & Services → Credentials → OAuth 2.0 Client → Download JSON")
    print("  Rename the downloaded file to credentials.json and place it here.")
    sys.exit(1)

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)

print("\n" + "=" * 60)
print("ACTION REQUIRED:")
print("=" * 60)
print("1. Copy the URL below and open it in your browser")
print("2. Log in with khurramshahrukh18@gmail.com and click Allow")
print("3. You'll be redirected to a page that may show an error")
print("   — that's fine. Copy the FULL URL from the address bar")
print("   and paste it below when prompted.")
print("=" * 60 + "\n")

creds = flow.run_local_server(port=0, open_browser=False)

print("\n" + "=" * 60)
print("SUCCESS — add these three lines to your .env file:")
print("=" * 60)
print(f"GMAIL_CLIENT_ID={creds.client_id}")
print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
print("=" * 60)
print("\nAlso add to the server .env via:")
print("  ssh -i ~/.ssh/id_ed25519_digitalocean root@167.71.228.187 \\")
print(f"  \"sed -i 's/^GMAIL_CLIENT_ID=.*/GMAIL_CLIENT_ID={creds.client_id}/' /opt/tradingbot/.env\"")
