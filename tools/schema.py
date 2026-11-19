"""Single source of truth for the catalogue layout.

The spreadsheet template, the validator and the AI extraction tool all import
these definitions, so a column renamed here changes everywhere at once.
Every string a teacher sees in the spreadsheet (sheet names, column names,
dropdown values, search-page text) is deliberately kept in Traditional Chinese.
The code, comments and docs are in English.
"""

import re

BOOK_SHEET = "書籍"
PIECE_SHEET = "曲目"
VOCAB_SHEET = "選項"
GUIDE_SHEET = "使用說明"

# --- Books: one row per physical book or PDF -------------------------------
BOOK_ID = "書籍編號"
BOOK_TITLE = "書名"
BOOK_SERIES = "系列/出版社"
BOOK_TYPE = "類型"
BOOK_LOCATION = "位置"
BOOK_LINK = "檔案連結"
BOOK_NOTES = "備註"

BOOK_COLUMNS = [BOOK_ID, BOOK_TITLE, BOOK_SERIES, BOOK_TYPE, BOOK_LOCATION, BOOK_LINK, BOOK_NOTES]
BOOK_REQUIRED = [BOOK_ID, BOOK_TITLE, BOOK_TYPE]

# --- Pieces: one row per piece inside a book --------------------------------
PIECE_ID = "曲目編號"
PIECE_BOOK_ID = "書籍編號"
PIECE_TITLE = "曲名"
PIECE_COMPOSER = "作曲家"
PIECE_PAGE = "頁碼"
PIECE_LEVEL = "程度"
PIECE_EXAM = "考級"
PIECE_PERIOD = "時期"
PIECE_STYLE = "風格"
PIECE_TECHNIQUE = "技巧重點"
PIECE_AUDIO = "示範音檔"
PIECE_NOTES = "備註"
# Filled by spreadsheet formulas from the books sheet; never typed by hand.
PIECE_BOOK_TITLE = "書名（自動）"
PIECE_BOOK_LOCATION = "位置（自動）"

PIECE_INPUT_COLUMNS = [
    PIECE_ID, PIECE_BOOK_ID, PIECE_TITLE, PIECE_COMPOSER, PIECE_PAGE, PIECE_LEVEL,
    PIECE_EXAM, PIECE_PERIOD, PIECE_STYLE, PIECE_TECHNIQUE, PIECE_AUDIO, PIECE_NOTES,
]
PIECE_DERIVED_COLUMNS = [PIECE_BOOK_TITLE, PIECE_BOOK_LOCATION]
PIECE_COLUMNS = PIECE_INPUT_COLUMNS + PIECE_DERIVED_COLUMNS
PIECE_REQUIRED = [PIECE_ID, PIECE_BOOK_ID, PIECE_TITLE, PIECE_COMPOSER, PIECE_PAGE]

# --- Controlled vocabularies (the dropdown lists) ---------------------------
# Studio staff may edit these lists in the options sheet; these are the defaults.
VOCAB = {
    BOOK_TYPE: ["教本", "曲集", "單曲", "考級教材", "練習曲集"],
    PIECE_LEVEL: [f"{n}級" for n in range(1, 9)],
    PIECE_PERIOD: ["巴洛克", "古典", "浪漫", "近代", "現代", "流行"],
    PIECE_STYLE: ["練習曲", "奏鳴曲", "舞曲", "小品", "變奏曲", "流行改編", "四手聯彈"],
}

# (sheet, column) pairs whose values must come from VOCAB.
VOCAB_FIELDS = [
    (BOOK_SHEET, BOOK_TYPE),
    (PIECE_SHEET, PIECE_LEVEL),
    (PIECE_SHEET, PIECE_PERIOD),
    (PIECE_SHEET, PIECE_STYLE),
]

# Physical location code: cabinet letter - shelf number - position, e.g. A-2-05.
LOCATION_PATTERN = re.compile(r"^[A-Z]-\d+-\d{2}$")
BOOK_ID_PATTERN = re.compile(r"^B(\d{4})$")
PIECE_ID_PATTERN = re.compile(r"^P(\d{5})$")


# --- Search sheet (Google Sheets only: FILTER/CHOOSECOLS do not exist in .xlsx) ---
SEARCH_SHEET = "搜尋"
SEARCH_LABEL = "請輸入關鍵字："
# Columns shown in the results, in display order.
SEARCH_COLUMNS = [
    PIECE_TITLE, PIECE_COMPOSER, PIECE_BOOK_TITLE, PIECE_PAGE,
    PIECE_BOOK_LOCATION, PIECE_LEVEL, PIECE_AUDIO,
]
# Columns the keyword is matched against.
SEARCH_MATCH_COLUMNS = [PIECE_TITLE, PIECE_COMPOSER, PIECE_BOOK_TITLE, PIECE_TECHNIQUE]


def column_letter(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def search_formula() -> str:
    """Formula for cell A3 of the search sheet; the keyword is typed in B1."""
    last = column_letter(len(PIECE_COLUMNS))
    picks = ",".join(str(PIECE_COLUMNS.index(c) + 1) for c in SEARCH_COLUMNS)
    haystack = '&" "&'.join(
        f"{PIECE_SHEET}!{column_letter(PIECE_COLUMNS.index(c) + 1)}2:{column_letter(PIECE_COLUMNS.index(c) + 1)}"
        for c in SEARCH_MATCH_COLUMNS
    )
    return (
        f'=IF($B$1="","",IFERROR(FILTER(CHOOSECOLS({PIECE_SHEET}!A2:{last},{picks}),'
        f'ISNUMBER(SEARCH($B$1,{haystack}))),"找不到符合的曲目"))'
    )


def book_id(n: int) -> str:
    return f"B{n:04d}"


def piece_id(n: int) -> str:
    return f"P{n:05d}"
