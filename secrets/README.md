# secrets/

Holds the Google credential files. Everything in this folder except this README is excluded by `.gitignore` and never pushed to GitHub.

| File | Source |
|---|---|
| `google_oauth_client.json` | OAuth client (desktop app) downloaded from Google Cloud Console |
| `google_token.json` | Created automatically after the first sign-in with `tools/setup_google_sheet.py` |

Setup steps are in `docs/08_api_and_credentials.md`.
