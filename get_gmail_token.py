"""
get_gmail_token.py — Run ONCE on your local machine to generate Gmail OAuth2 tokens.

Steps:
  1. Follow the Google Cloud Console setup guide (see README or chat instructions).
  2. Download credentials.json into this project folder.
  3. Run:  python get_gmail_token.py
  4. A browser window will open — log in with khurramshahrukh18@gmail.com and allow access.
  5. Copy the three values printed at the end into your .env file.

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

print("Opening browser for Google login...")
print("Log in with khurramshahrukh18@gmail.com and click Allow.\n")

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
creds = flow.run_local_server(port=0)

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
