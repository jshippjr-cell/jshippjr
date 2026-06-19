#!/usr/bin/env python3
"""Mint a Gmail OAuth refresh token for Chordential triage (Phase B1).

Run this ONCE on your own machine (it opens a browser). It prints the three
values you paste into Render: client id, client secret, and the refresh token.

Prereqs:
  1. In Google Cloud Console, enable the Gmail API and create an OAuth client
     of type "Desktop app". Download its JSON ("client_secret_….json").
  2. pip install google-auth-oauthlib

Usage:
  python scripts/mint_gmail_token.py /path/to/client_secret_xxx.json

The scope is gmail.modify (read messages + change labels). The token is yours;
it is never sent anywhere by this script — it's printed to your terminal only.
"""
import sys

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    client_json = sys.argv[1]

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Run:  pip install google-auth-oauthlib")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(client_json, SCOPES)
    # offline + consent forces Google to return a *refresh* token (not just a
    # short-lived access token).
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent",
        authorization_prompt_message="Opening your browser to authorize Gmail access…",
    )

    if not creds.refresh_token:
        print("\nNo refresh token returned. Re-run — and if you've authorized "
              "this app before, revoke it at https://myaccount.google.com/permissions "
              "first so Google issues a fresh refresh token.")
        return 1

    print("\n" + "=" * 64)
    print("Paste these into Render (mark the secret ones as secret):\n")
    print(f"CHORDENTIAL_GMAIL_CLIENT_ID={creds.client_id}")
    print(f"CHORDENTIAL_GMAIL_CLIENT_SECRET={creds.client_secret}")
    print(f"CHORDENTIAL_GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
