# 08 API 與金鑰設定

| 項目 | 內容 |
|---|---|
| 對象 | 建檔人員、系統建置人員 |
| 文件版本 | v1.0 |

本專案有兩個工具需要外部服務的授權：

| 工具 | 外部服務 | 授權方式 | 存放位置 |
|---|---|---|---|
| `tools/extract_toc.py` | Claude API | API 金鑰 | `.env` |
| `tools/setup_google_sheet.py` | Google Drive、Google Sheets API | OAuth 登入 | `secrets/` |

## 1. 隱私原則

- **金鑰不寫進程式碼，也不放進 git。** `.env` 與 `secrets/` 都列在 `.gitignore`，上傳 GitHub 時會自動排除。
- **金鑰不要貼在對話、Email 或文件裡。** 只直接寫進本機的 `.env` 檔案。
- **客戶資料不進 git。** 目錄頁照片（`input/toc_photos/`）與擷取結果（`output/`）也列在 `.gitignore`。
- 上傳前用 `git status` 確認清單裡沒有 `.env`、`secrets/` 底下的檔案或照片。

## 2. Claude API 金鑰

1. 到 Claude 開發者平台（platform.claude.com）登入，在 API keys 頁面建立一把新金鑰。
2. 在專案根目錄複製設定範本：

   ```bash
   cp .env.example .env
   ```

3. 用文字編輯器開啟 `.env`，在 `ANTHROPIC_API_KEY=` 後面貼上金鑰，存檔。
4. 限制檔案權限，只有自己能讀：

   ```bash
   chmod 600 .env
   ```

5. 確認設定生效（不會顯示金鑰內容）：

   ```bash
   python3 -c "import sys; sys.path.insert(0,'tools'); import config, os; config.load_env(); print('已設定' if os.environ.get('ANTHROPIC_API_KEY') else '未設定')"
   ```

**另一種方式：** 安裝 Anthropic 的 `ant` 命令列工具並執行 `ant auth login`，就不需要 `.env`。

**費用控管：** 建議在開發者平台為這把金鑰設定每月用量上限。

## 3. Google 授權

自動建置程式以 OAuth 登入教室的 Google 帳號，權限範圍是 `drive.file`：**只能存取這支程式自己建立的檔案**，看不到帳號裡的其他檔案。

### 3.1 建立 OAuth 用戶端（只需做一次）

1. 開啟 Google Cloud Console（console.cloud.google.com），建立新專案，例如「piano-catalog」。
2. 「API 和服務」→「程式庫」，啟用 **Google Drive API** 與 **Google Sheets API**。
3. 「API 和服務」→「OAuth 同意畫面」：
   - 使用者類型選「外部」。
   - 填寫應用程式名稱與聯絡 Email。
   - 在「測試使用者」加入要登入的 Google 帳號。
4. 「API 和服務」→「憑證」→「建立憑證」→「OAuth 用戶端 ID」，應用程式類型選 **「電腦版應用程式」**。
5. 下載 JSON 檔，改名為 `google_oauth_client.json`，放進專案的 `secrets/` 資料夾。

### 3.2 執行自動建置

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt

python tools/setup_google_sheet.py --share teacher1@gmail.com teacher2@gmail.com
```

第一次執行會開啟瀏覽器要求登入並授權。授權後產生 `secrets/google_token.json`，之後不需要再登入。

程式會：
1. 上傳範本並轉換成 Google 試算表。
2. 建立搜尋頁。
3. 讀回計算結果，驗證自動欄位、搜尋頁與下拉選單都正常。
4. 將試算表共用給老師（使用 `--share` 時）。

每次執行都會建立一份新的試算表。驗證全部通過時，結尾會顯示「0 項失敗」與試算表連結。

### 3.3 撤銷授權

不再需要時：
1. 刪除 `secrets/google_token.json`。
2. 到 Google 帳號的「安全性」→「第三方應用程式存取權」移除這個應用程式。

## 4. 金鑰外洩時

1. 立即到對應平台撤銷（刪除）該金鑰或 OAuth 用戶端。
2. 建立新的金鑰，更新 `.env` 或 `secrets/`。
3. 如果金鑰曾被 commit 進 git，即使之後刪除，歷史記錄裡仍然存在，必須視為已外洩並撤銷。
