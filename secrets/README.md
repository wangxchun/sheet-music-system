# secrets/

存放 Google 授權檔。這個資料夾除了本說明以外，全部被 `.gitignore` 排除，不會上傳到 GitHub。

| 檔案 | 來源 |
|---|---|
| `google_oauth_client.json` | 從 Google Cloud Console 下載的 OAuth 用戶端（桌面應用程式） |
| `google_token.json` | 第一次執行 `tools/setup_google_sheet.py` 登入後自動產生 |

設定步驟見 `docs/08_API與金鑰設定.md`。
