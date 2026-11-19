# 05 Cataloguing Workflow

| Item | Details |
|---|---|
| Audience | Cataloguing staff |
| Document version | v1.0 |

The spreadsheet's interface is in Traditional Chinese for the teachers. Column names and values are quoted exactly as they appear, with an English gloss.

## 1. Overview

```text
1 Batch by shelf → 2 Photograph contents pages → 3 AI extraction → 4 Human review
→ 5 Paste into the catalogue → 6 Data check → 7 Label and shelve
```

Each batch covers one shelf. Finish a batch and pass the check before starting the next, so errors don't pile up.

## 2. Photographing contents pages

| Situation | What to photograph |
|---|---|
| Collection with a contents page | Every contents page |
| Collection without a contents page | The first page of each piece; or type the pieces in by hand |
| Single piece | The first page |
| PDF material | Use the PDF's contents pages directly; no photo needed |

**Photo tips**
- Use good light and avoid glare and shadows.
- Fill the frame with the page; text should be sharp and straight.
- JPG, PNG, WEBP and PDF are supported.

**File layout**

```text
input/toc_photos/
    B0001_burgmuller_25_etudes.jpg     one photo = one book
    B0003_clementi_sonatinas/          one folder = one book
        01.jpg                         pages are processed in file-name order
        02.jpg
```

The file or folder name is recorded in the notes column of the extraction results, so reviewers can match rows to the physical book.

## 3. AI extraction (bulk cataloguing)

### 3.1 Setup (once)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
```

Set up the Claude API key in `.env` at the project root; see section 2 of `08_api_and_credentials.md`.

### 3.2 Run

First export the current books and pieces sheets from the catalogue as CSV, so new IDs continue from the existing ones:

```bash
python tools/extract_toc.py input/toc_photos \
    --catalog-books books.csv --catalog-pieces pieces.csv --out output/
```

It produces two files:

| File | Contents |
|---|---|
| `output/extracted_books.csv` | One row per book; `類型` (type) and `位置` (location) are left blank for the reviewer |
| `output/extracted_pieces.csv` | One row per piece; `備註` (notes) says `AI 擷取，待校對` ("AI-extracted, to be reviewed") or `AI 不確定，請特別確認` ("AI unsure, check carefully") |

If one book fails, the tool carries on with the others and lists the books to redo at the end.

### 3.3 Cost

Each book is one Claude API call; the cost depends on the number of pages. Record the actual cost of the 20 pilot books, estimate the total for full cataloguing from that, and include it in the quote.

## 4. AI extraction (adding a few books)

When the studio adds one or two books, there is no need to run the tool. Use Claude or another AI chat tool directly:

1. Upload the contents-page photo.
2. Paste this instruction:

```text
This is the contents page of a piano collection. List every piece in the
order printed, as a table with the columns: title, composer, page.
Keep titles in their original language with opus numbers. If anything is
hard to read, mark it "unsure"; do not guess.
```

3. Check the result against the book, then paste it into the pieces sheet.

## 5. Human review (required)

Check every row against the physical book. The AI most often gets these wrong:

| Common error | How to check |
|---|---|
| Misspelt foreign titles, such as missing accents | Compare letter by letter |
| Page number off by a digit | Turn to the page |
| A section heading listed as a piece | Delete rows that are not pieces |
| Blank composer | Fill it in from the cover or the piece's page |

While reviewing, also:
- Books sheet: fill in `類型` (type) and `位置` (location).
- Pieces sheet: for each reviewed row, delete `AI 擷取，待校對` from `備註` (notes).

## 6. Paste into the catalogue and check

1. Paste the reviewed CSV rows at the bottom of the catalogue's books and pieces sheets. In the pieces sheet, paste only up to the `備註` (notes) column; do not overwrite the lookup columns.
2. Export all three sheets as CSV and run the data check:

```bash
python3 tools/validate_catalog.py books.csv pieces.csv options.csv
```

3. Fix every error before starting the next batch. Warnings can wait until the tagging phase.

## 7. Label and shelve

1. Put a location label on the spine, for example `A-2-05`.
2. Shelve the books in code order.
3. Spot-check 3 pieces: look them up on the search sheet and confirm you can find the book by its location.

## 8. Progress log

| Batch | Shelf | Books | Pieces | Time spent | Check result | Completed |
|---|---|---|---|---|---|---|
| 1 | A-1 | | | | | |
| 2 | A-2 | | | | | |
| 3 | A-3 | | | | | |
