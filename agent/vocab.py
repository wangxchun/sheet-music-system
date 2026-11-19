"""English codes for the spreadsheet's Chinese dropdown values.

The spreadsheet stores teacher-facing labels such as 浪漫 or 3級. The agent's
database and tool interfaces use stable English codes instead.

DESIGN DECISION: translate once, at the ETL boundary, not inside prompts.
- The LLM sees Literal["romantic", ...] in the tool schema, so it cannot invent
  a value. A typo becomes a validation error rather than a silent empty result.
- Text-to-SQL is easier when the columns hold plain codes and integers.
- If the studio renames a label, only this mapping changes. A unit test fails
  if this file and tools/schema.py ever disagree.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Mapping, Tuple, get_args

from tools import schema as s

BookType = Literal["method", "collection", "single", "exam", "etudes"]
Period = Literal["baroque", "classical", "romantic", "modern", "contemporary", "pop"]
Style = Literal["etude", "sonata", "dance", "character_piece", "variations", "pop_arrangement", "duet"]

BOOK_TYPE_CODES: Dict[str, BookType] = {
    "教本": "method",
    "曲集": "collection",
    "單曲": "single",
    "考級教材": "exam",
    "練習曲集": "etudes",
}
PERIOD_CODES: Dict[str, Period] = {
    "巴洛克": "baroque",
    "古典": "classical",
    "浪漫": "romantic",
    "近代": "modern",
    "現代": "contemporary",
    "流行": "pop",
}
STYLE_CODES: Dict[str, Style] = {
    "練習曲": "etude",
    "奏鳴曲": "sonata",
    "舞曲": "dance",
    "小品": "character_piece",
    "變奏曲": "variations",
    "流行改編": "pop_arrangement",
    "四手聯彈": "duet",
}

LEVEL_MIN, LEVEL_MAX = 1, 8


def level_to_int(label: str) -> int | None:
    """'3級' -> 3; '' -> None (level not assigned yet)."""
    if not label:
        return None
    number = int(label.removesuffix("級"))
    if not LEVEL_MIN <= number <= LEVEL_MAX:
        raise ValueError(f"level out of range: {label}")
    return number


def int_to_level(level: int) -> str:
    return f"{level}級"


def reverse(mapping: Mapping[str, str]) -> Dict[str, str]:
    return {code: label for label, code in mapping.items()}


def check_consistency() -> None:
    """Raise if the mappings drift from tools/schema.py or from the Literal types."""
    pairs: List[Tuple[List[str], Mapping[str, str], Tuple[object, ...]]] = [
        (s.VOCAB[s.BOOK_TYPE], BOOK_TYPE_CODES, get_args(BookType)),
        (s.VOCAB[s.PIECE_PERIOD], PERIOD_CODES, get_args(Period)),
        (s.VOCAB[s.PIECE_STYLE], STYLE_CODES, get_args(Style)),
    ]
    for labels, mapping, codes in pairs:
        if list(mapping) != labels:
            raise AssertionError(f"mapping keys {list(mapping)} != schema {labels}")
        if list(mapping.values()) != list(codes):
            raise AssertionError(f"mapping codes {list(mapping.values())} != {codes}")
    expected_levels = [int_to_level(n) for n in range(LEVEL_MIN, LEVEL_MAX + 1)]
    if s.VOCAB[s.PIECE_LEVEL] != expected_levels:
        raise AssertionError(f"levels {s.VOCAB[s.PIECE_LEVEL]} != {expected_levels}")
