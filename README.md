# 鋼琴教材目錄建置：交付文件

| 項目 | 內容 |
|---|---|
| 客戶 | ○○鋼琴教室 |
| 專案 | 鋼琴教材目錄建置 |
| 版本 | v1.0 |
| 交付日期 | 29/04/2026 |

## 專案摘要

教室約 300 份教材以紙本為主，老師找一首曲子需要數分鐘。本專案建立一份可用手機查詢的雲端教材目錄，記錄每一首曲子在哪本書、第幾頁、哪個書櫃，並支援依程度、時期、風格篩選，以及連結示範音檔。

系統以 Google 試算表為核心，不需要開發軟體，也不需要工程人員維護。建檔時以 AI 從目錄頁照片擷取曲目，再經人工校對與自動檢查，確保資料正確。

## 交付內容

```text
piano-studio-catalog/
├── README.md                 本文件
├── docs/
│   ├── 01_需求分析.md        需求拆解、限制條件、驗收指標
│   ├── 02_系統設計.md        架構、工具選擇、資料結構、音檔方案、權限
│   ├── 03_專案計畫.md        時程、各階段工作、工時估算、風險
│   ├── 04_管理者手冊.md      初次建置、搜尋頁、篩選檢視、日常維護
│   ├── 05_建檔作業流程.md    拍攝、AI 擷取、校對、檢查、上架
│   ├── 06_老師使用說明.md    一頁版操作說明，可列印
│   ├── 07_驗收報告.md        導入前後量測與簽署
│   └── 08_API與金鑰設定.md   Claude API、Google 授權、隱私原則
├── system/
│   └── 鋼琴教材目錄.xlsx     目錄範本，匯入 Google 試算表使用（由 build_template.py 產生，不納入版本控制）
├── tools/
│   ├── schema.py             欄位與搜尋公式定義（所有工具共用）
│   ├── config.py             讀取 .env 與 secrets/
│   ├── build_template.py     產生目錄範本
│   ├── setup_google_sheet.py 自動建立 Google 試算表並驗證公式
│   ├── validate_catalog.py   資料檢查
│   ├── extract_toc.py        以 Claude 擷取目錄頁
│   └── requirements.txt
├── tests/
│   └── test_tools.py         工具的自動測試
├── sample/                   範例資料（書籍、曲目、選項）
├── input/toc_photos/         待擷取的目錄頁照片（不進 git）
├── output/                   AI 擷取結果（不進 git）
├── secrets/                  Google 授權檔（不進 git）
├── .env.example              金鑰設定範本；實際金鑰寫在 .env（不進 git）
└── .gitignore
```

## 隱私

API 金鑰、Google 授權檔、目錄頁照片與擷取結果都不會進入 git。設定方式與注意事項見《08 API 與金鑰設定》。

## 依角色閱讀

| 角色 | 先看 |
|---|---|
| 負責人 | `docs/01`、`docs/04`、`docs/07` |
| 老師 | `docs/06` |
| 建檔人員 | `docs/05`、`docs/08`、`docs/02` 第 3 節 |

## 快速開始

**產生範本**：`system/鋼琴教材目錄.xlsx` 不納入版本控制，首次使用前請先執行 `python3 tools/build_template.py` 產生（需安裝 `openpyxl`）。

**建置目錄**：依《04 管理者手冊》第 1 節，將 `system/鋼琴教材目錄.xlsx` 匯入 Google 試算表，並建立搜尋頁與篩選檢視。

**工具環境**：

| 工具 | 需求 |
|---|---|
| `validate_catalog.py` | Python 3.9 以上，不需安裝套件 |
| `build_template.py` | Python 3.9 以上，`openpyxl` |
| `extract_toc.py` | Python 3.10 以上，`anthropic`，Claude API 金鑰 |
| `setup_google_sheet.py` | Python 3.10 以上，Google API 套件，Google OAuth 用戶端 |

```bash
# 重新產生目錄範本
python3 tools/build_template.py

# 檢查目錄資料
python3 tools/validate_catalog.py sample/書籍.csv sample/曲目.csv sample/選項.csv

# 自動建立 Google 試算表並驗證（見 docs/08）
python3.11 tools/setup_google_sheet.py

# AI 擷取目錄頁（見 docs/05、docs/08）
python3.11 tools/extract_toc.py input/toc_photos --out output/

# 執行測試（不會呼叫 API）
python3 -m unittest discover -s tests -v
```

## 欄位變更

所有欄位名稱與下拉選項定義在 `tools/schema.py`。修改後執行 `build_template.py` 重新產生範本，並執行測試確認範例資料仍然一致。
