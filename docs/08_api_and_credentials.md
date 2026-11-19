# 08 API and Credentials Setup

| Item | Details |
|---|---|
| Audience | Cataloguing staff, system setup staff |
| Document version | v1.0 |

Two tools in this project need authorisation for external services:

| Tool | External service | Authorisation | Stored in |
|---|---|---|---|
| `tools/extract_toc.py` | Claude API | API key | `.env` |
| `tools/setup_google_sheet.py` | Google Drive and Google Sheets APIs | OAuth sign-in | `secrets/` |

## 1. Privacy rules

- **Keys never go in the code or in git.** `.env` and `secrets/` are listed in `.gitignore`, so they are excluded when pushing to GitHub.
- **Never paste keys into chats, emails or documents.** Write them only into the local `.env` file.
- **Client data never goes in git.** Contents-page photos (`input/toc_photos/`) and extraction results (`output/`) are also listed in `.gitignore`.
- Before pushing, run `git status` and make sure no `.env`, nothing under `secrets/`, and no photos are listed.

## 2. Claude API key

1. Sign in to the Claude Developer Platform (platform.claude.com) and create a new key on the API keys page.
2. Copy the settings template at the project root:

   ```bash
   cp .env.example .env
   ```

3. Open `.env` in a text editor, paste the key after `ANTHROPIC_API_KEY=`, and save.
4. Restrict the file so only you can read it:

   ```bash
   chmod 600 .env
   ```

5. Confirm the key is picked up (the key itself is not printed):

   ```bash
   python3 -c "import sys; sys.path.insert(0,'tools'); import config, os; config.load_env(); print('set' if os.environ.get('ANTHROPIC_API_KEY') else 'not set')"
   ```

**Alternative:** install Anthropic's `ant` command-line tool and run `ant auth login`; then `.env` is not needed.

**Cost control:** set a monthly spending limit for this key on the developer platform.

## 3. Google authorisation

The setup tool signs in to the studio's Google account with OAuth, using the `drive.file` scope: **it can only access files it created itself** and cannot see anything else in the account.

### 3.1 Create an OAuth client (once)

1. Open Google Cloud Console (console.cloud.google.com) and create a new project, for example `piano-catalog`.
2. **APIs & Services** → **Library**: enable the **Google Drive API** and the **Google Sheets API**.
3. **APIs & Services** → **OAuth consent screen**:
   - Choose **External** as the user type.
   - Fill in the app name and a contact email.
   - Under **Test users**, add the Google account that will sign in.
4. **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID**, with application type **Desktop app**.
5. Download the JSON file, rename it `google_oauth_client.json`, and put it in the project's `secrets/` folder.

### 3.2 Run the automatic setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt

python tools/setup_google_sheet.py --share teacher1@gmail.com teacher2@gmail.com
```

The first run opens a browser to sign in and grant access. This creates `secrets/google_token.json`, so you won't need to sign in again.

The tool will:
1. Upload the template and convert it to a Google Sheet.
2. Create the search sheet.
3. Read the computed values back to verify that the lookup columns, the search sheet and the dropdowns work.
4. Share the spreadsheet with the teachers (with `--share`).

Every run creates a new spreadsheet. If all checks pass, it ends with `0 check(s) failed` and the spreadsheet link.

### 3.3 Revoke access

When it is no longer needed:
1. Delete `secrets/google_token.json`.
2. In the Google account, go to **Security** → **Third-party apps with account access** and remove the app.

## 4. If a key leaks

1. Revoke (delete) the key or OAuth client on the relevant platform immediately.
2. Create a new one and update `.env` or `secrets/`.
3. If a key was ever committed to git, it remains in the history even after it is deleted. Treat it as leaked and revoke it.
