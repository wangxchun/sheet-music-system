# 02 System Design

| Item | Details |
|---|---|
| Client | ○○ Piano Studio |
| Document version | v1.0 |
| Date | 19/03/2026 |

The spreadsheet's interface is in Traditional Chinese for the teachers. Sheet names, column names and dropdown values are quoted below exactly as they appear, with an English gloss.

## 1. Architecture

```text
      Shelves (with location labels)        Google Drive (PDF materials)
              │                                      │
              ▼                                      ▼
   ┌──────────────── Google Sheets: piano catalogue ─────────────────┐
   │  Books ──(book ID)──► Pieces ──► Search sheet / filter views     │
   │                         ▲                                       │
   │                 Options (dropdown lists)                        │
   └─────────────────────────────────────────────────────────────────┘
              ▲                                      │
   Cataloguing tools (AI extraction, checks)   Teachers search on phone or computer
```

| Component | Purpose | Users |
|---|---|---|
| Google Sheets catalogue | Three sheets (books, pieces, options) plus a search sheet | All teachers |
| Google Drive folder | Stores PDF materials and teacher-recorded demonstrations | All teachers |
| Shelf location labels | Link a location in the catalogue to the physical book | All teachers |
| AI extraction tool `tools/extract_toc.py` | Extracts titles, composers and page numbers from contents-page photos | Cataloguing staff |
| Data-check tool `tools/validate_catalog.py` | Finds missing, duplicated and malformed data | Cataloguing staff, admin |
| Template generator `tools/build_template.py` | Generates the catalogue template | Cataloguing staff |

## 2. Tool choice

| Candidate | Pros | Cons | Decision |
|---|---|---|---|
| **Google Sheets + Drive** | Free; most people know it; good mobile app; exports to CSV, so the data is not locked in | Plain interface; relationships need formulas | **Chosen** |
| Airtable | Relational tables, friendly interface | The free plan caps the number of records, which piece-level data may exceed; paid in the long run | Upgrade option if the budget grows |
| Notion databases | Attractive; can hold teaching notes | Free plan limits collaboration; filtering slows down with large data | Not chosen |
| Sheet-music apps | Convenient for reading scores on a tablet | Designed for individuals, not shared use; cannot hold paper materials | Not chosen |
| Custom-built system | Fully tailored | Nobody to maintain it (violates C2) | Not chosen |

Pricing and free-plan limits change over time. Check the providers' current plans before signing.

## 3. Data model

### 3.1 Books sheet (`書籍`)

| Column | Meaning | Description | Example | Required |
|---|---|---|---|---|
| 書籍編號 | Book ID | B plus four digits, assigned in order and never reused | B0001 | Yes |
| 書名 | Title | Title as printed on the cover | 布爾格繆勒 25 首練習曲 Op. 100 | Yes |
| 系列/出版社 | Series / publisher | | Schirmer | No |
| 類型 | Type | Dropdown: 教本 (method book), 曲集 (collection), 單曲 (single piece), 考級教材 (exam material), 練習曲集 (études) | 練習曲集 | Yes |
| 位置 | Location | Cabinet-shelf-position; see 3.4 | A-2-05 | Required for paper books |
| 檔案連結 | File link | Google Drive link | | Required for PDFs |
| 備註 | Notes | | Cover damaged | No |

### 3.2 Pieces sheet (`曲目`)

| Column | Meaning | Description | Example | Required |
|---|---|---|---|---|
| 曲目編號 | Piece ID | P plus five digits, assigned in order and never reused | P00002 | Yes |
| 書籍編號 | Book ID | Refers to the books sheet | B0001 | Yes |
| 曲名 | Title | As printed in the book, in the original language | Arabesque (Op. 100 No. 2) | Yes |
| 作曲家 | Composer | | Burgmüller | Yes |
| 頁碼 | Page | Starting page | 4 | Yes |
| 程度 | Level | Dropdown: 1級–8級 (grades 1–8), the studio's own scale | 3級 | Phase 2 |
| 考級 | Exam grade | Matching exam board and grade | | No |
| 時期 | Period | Dropdown | 浪漫 (Romantic) | Phase 2 |
| 風格 | Style | Dropdown | 練習曲 (étude) | Phase 2 |
| 技巧重點 | Technical focus | Free text | 快速音群、斷奏 (fast passages, staccato) | No |
| 示範音檔 | Demo recording | Link to a recording | | Phase 3 |
| 備註 | Notes | | | No |
| 書名（自動） | Book title (auto) | Looked up from the book ID; not typed | | — |
| 位置（自動） | Location (auto) | Looked up from the book ID; not typed | | — |

### 3.3 Options sheet (`選項`)

Lists every dropdown value. To add an option, add it to this sheet and the dropdowns update automatically. The data-check tool reads the same sheet, so values such as 初級, 初階 and 1級 (three ways of saying "beginner") cannot be mixed and break the filters.

### 3.4 Shelf location codes

The format is **cabinet-shelf-position**. For example, `A-2-05` means cabinet A, shelf 2, fifth book.

1. Label each cabinet A, B, C… and each shelf 1, 2, 3….
2. Put the full code on the spine of each book.
3. When returning a book, put it back where the spine code says.

The catalogue tells teachers where a book is; the shelf labels make sure the book is really there when they look. Both are needed.

## 4. Ways to search

| Method | When to use it | How |
|---|---|---|
| Search sheet | You know part of the title, composer or book title | Type a keyword in cell B1 of the search sheet; the book, page and location are listed below |
| Filter views | Choosing pieces by level, period or style | Apply a preset filter view on the pieces sheet |
| In-app search | Quick lookup on a phone | The Find feature in the Google Sheets app |

The search formula and how to set up filter views are in `04_admin_manual.md`.

## 5. Cataloguing process

See `05_cataloguing_workflow.md` for details. In summary:

```text
Photograph contents pages → AI extracts titles, composers, pages → review against the book
→ fill in type and location → paste into the catalogue → data check shows 0 errors
→ label the spine and shelve
```

AI extraction uses text recognition, not music-score recognition. Contents pages are printed text, which is recognised reliably, but foreign-language titles and page numbers can still be misread, so every row must be reviewed by a person.

## 6. Demonstration recording options

| Option | How | Cost | Risk | Best for |
|---|---|---|---|---|
| A. Link existing recordings | Paste a link to a performance on a public platform into the demo recording column | Low | Tempo or interpretation may not suit beginners; links can break | Common classical pieces |
| B. Teacher recordings | Record on a phone, save to the Drive demo-recordings folder, paste the link into the catalogue | Medium | Recording quality varies | Method-book études, pieces with no existing recording |
| C. Generate audio from scores | Convert the score with music-recognition software, then export audio | High | One misread note makes the recording wrong | Clearly printed pieces with no recording, where a teacher is willing to check each one |

**Options A and B are recommended.** Use option C only when necessary, and a teacher must listen to each generated recording before it goes to students. Option C has the extra benefit of slower playback and separate hands. If the studio needs that, pilot 5 pieces first and measure how long corrections take before scaling up.

## 7. Permissions and data security

| Role | Permissions |
|---|---|
| Owner | Owner: can edit and manage sharing |
| Teachers | Editors: can search, add and edit |
| Students and parents | No access to the catalogue; only individual recording links are shared |

- The catalogue holds only bibliographic data, no student personal data.
- Google Sheets keeps a version history, so accidental deletions can be restored.
- Export a CSV backup every month; see `04_admin_manual.md`.
