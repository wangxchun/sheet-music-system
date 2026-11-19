# 04 Admin Manual

| Item | Details |
|---|---|
| Audience | Studio owner |
| Document version | v1.0 |

This manual covers the initial setup of the system and routine maintenance.

The spreadsheet's interface is in Traditional Chinese for the teachers. Sheet names, column names and values you need to type are quoted exactly as they appear, with an English gloss. Google menu names are given in English; they appear in whatever language your Google account uses.

## 1. Initial setup

There are two ways to set it up:

| Method | Best for | How |
|---|---|---|
| Automatic | Cataloguing staff running it on a computer | `tools/setup_google_sheet.py` does 1.1, 1.2 and 1.4 and verifies the formulas; see `08_api_and_credentials.md` |
| Manual | No code | Follow steps 1.1–1.5 below |

Either way, do 1.3 (filter views) and 1.5 (protect the lookup columns) by hand afterwards.

### 1.1 Import the catalogue template

1. Sign in to the studio's Google account and open Google Drive.
2. Create a folder named `鋼琴教材目錄` (piano catalogue), with two subfolders: `PDF 教材` (PDF materials) and `示範音檔` (demo recordings).
3. Upload `system/piano_catalog.xlsx` to the `鋼琴教材目錄` folder.
4. Right-click the file → **Open with** → **Google Sheets**.
5. Once it opens, choose **File** → **Save as Google Sheets**. Use this Google Sheets version from now on.

After importing, check the following:

| Check | Expected result |
|---|---|
| Tabs | `使用說明` (guide), `書籍` (books), `曲目` (pieces), `選項` (options) |
| `程度` (level) column in the pieces sheet | Clicking a cell shows a dropdown of 1級–8級 |
| `書名（自動）` (book title, auto) in row 2 of the pieces sheet | Shows `布爾格繆勒 25 首練習曲 Op. 100` |
| `位置（自動）` (location, auto) in row 2 of the pieces sheet | Shows `A-2-05` |

### 1.2 Create the search sheet

1. Add a new tab at the far left and name it `搜尋` (search).
2. In A1, type `請輸入關鍵字：` ("enter a keyword:"). Leave B1 empty; it is the input cell.
3. In A2 to G2, type these column headings in order: `曲名`, `作曲家`, `書名`, `頁碼`, `位置`, `程度`, `示範音檔` (title, composer, book title, page, location, level, demo recording).
4. Paste this formula into A3:

```text
=IF($B$1="","",IFERROR(FILTER(CHOOSECOLS(曲目!A2:N,3,4,13,5,14,6,11),ISNUMBER(SEARCH($B$1,曲目!C2:C&" "&曲目!D2:D&" "&曲目!M2:M&" "&曲目!J2:J))),"找不到符合的曲目"))
```

5. Type `Burgmüller` in B1 and check that A3 shows the sample piece La Candeur (Op. 100 No. 1), page 2, location A-2-05.

The formula searches the title, composer, book title and technical focus at once, and ignores case. When nothing matches, it shows `找不到符合的曲目` ("no matching pieces").

### 1.3 Create filter views

On the pieces sheet, choose **Data** → **Create filter view** and set up a few common views:

| View name | Condition |
|---|---|
| `初級曲目` (beginner) | `程度` is 1級, 2級 or 3級 |
| `中級曲目` (intermediate) | `程度` is 4級 or 5級 |
| `巴洛克` (Baroque) | `時期` (period) is 巴洛克 |
| `有示範音檔` (has recording) | `示範音檔` is not empty |

A filter view does not change what other teachers see, so it is safe to use.

### 1.4 Sharing

1. Click **Share** at the top right → add the three teachers' Google accounts as **Editor**.
2. Keep **General access** set to **Restricted**. Do not set it to "Anyone with the link".
3. Ask the teachers to install the Google Sheets app on their phones and star the catalogue so it is easy to find.

### 1.5 Protect the lookup columns

1. On the pieces sheet, select columns M and N (the automatic book title and location columns).
2. Right-click → **Protect range** → set it to **Only you** can edit.

This stops teachers from accidentally overwriting the formulas.

## 2. Routine maintenance

### 2.1 Add a book (about 5 minutes)

1. Add a row at the bottom of the books sheet. The book ID continues from the last one (if the last is B0215, the new one is B0216).
2. Fill in the title, type and location. For a PDF, put the file in the `PDF 教材` folder and paste its link.
3. Photograph the contents page and have the AI tool extract the pieces (see section 4, "Adding a few books", of `05_cataloguing_workflow.md`). Check the result against the book, then paste it into the pieces sheet.
4. Piece IDs continue from the last one.
5. Put a location label on the spine and shelve the book.

### 2.2 Add a dropdown option

Go to the options sheet and add the new value at the bottom of the matching column. The new option appears in the pieces sheet's dropdown automatically.

**Do not change or delete options that are already in use.** Pieces that already have that value would become invalid. To rename an option, first use **Find and replace** to change every old value in the pieces sheet.

### 2.3 Monthly check (about 10 minutes)

1. Export a backup: switch to each of the books, pieces and options sheets in turn, choose **File** → **Download** → **Comma-separated values (.csv)**, and save the files to a computer or to a `備份` (backup) folder in Drive, with the date in the file name.
2. Run the data check (needs a computer with Python 3.9 or later; see 2.4).
3. If there are errors, use the row numbers in the report to fix them in the spreadsheet.

### 2.4 Run the data-check tool

```bash
python3 tools/validate_catalog.py books.csv pieces.csv options.csv
```

| Output | Meaning |
|---|---|
| `0 error(s)` | The data is fine |
| `[ERROR] 曲目 row 15 …` | Row 15 of the pieces sheet needs fixing |
| `[WARNING] … no 程度 (level) yet` | Doesn't affect use; fill it in when you have time |

The tool checks required columns, ID format and duplicates, whether each piece's book exists, whether dropdown values are valid, page-number format, location format, and whether the same piece is entered twice in the same book.

### 2.5 If data is deleted by mistake

Choose **File** → **Version history** → **See version history**, find the version from before the deletion, and restore it.

## 3. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `書名（自動）` shows `找不到書籍` ("book not found") | The book ID is mistyped, or the book has not been added to the books sheet yet |
| A dropdown shows a red warning | The value is not in the options sheet; choose from the dropdown instead |
| The search sheet shows `找不到符合的曲目` ("no matching pieces") | Try another keyword, such as just the composer or part of the title |
| The search formula shows an error | Check that the column order in the pieces sheet has not changed; it must stay fixed |
| The book is not at the location in the catalogue | It may be on loan or misplaced; return it by its spine code |
