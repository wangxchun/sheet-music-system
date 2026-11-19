"""Tests for the catalogue tools. No network access, no Claude API calls.

Run from the project root:
    python3 -m unittest discover -s tests -v
"""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import schema as s  # noqa: E402
import validate_catalog as v  # noqa: E402
from extract_toc import BookSource, Extraction, collect_sources, next_number, to_rows  # noqa: E402

SAMPLE = ROOT / "sample"


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.books = read_csv(SAMPLE / "書籍.csv")
        self.pieces = read_csv(SAMPLE / "曲目.csv")

    def run_validator(self):
        write_csv(self.tmp / "b.csv", s.BOOK_COLUMNS, self.books)
        write_csv(self.tmp / "p.csv", s.PIECE_COLUMNS, self.pieces)
        return v.validate(self.tmp / "b.csv", self.tmp / "p.csv", SAMPLE / "選項.csv")

    def assert_one_error_containing(self, text):
        report = self.run_validator()
        self.assertEqual(len(report.errors), 1, report.errors)
        self.assertIn(text, report.errors[0])

    def test_sample_is_clean(self):
        report = self.run_validator()
        self.assertEqual(report.errors, [])
        self.assertEqual((report.n_books, report.n_pieces), (3, 6))
        self.assertEqual(len(report.warnings), 1)  # P00006 has no level yet

    def test_blank_formula_rows_are_skipped(self):
        blank = {c: "" for c in s.PIECE_COLUMNS}
        self.pieces += [blank] * 50
        report = self.run_validator()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.n_pieces, 6)

    def test_unknown_book(self):
        self.pieces[0][s.PIECE_BOOK_ID] = "B0099"
        self.assert_one_error_containing("B0099")

    def test_value_not_in_vocab(self):
        self.pieces[0][s.PIECE_LEVEL] = "初級"
        self.assert_one_error_containing("初級")

    def test_missing_required_cell(self):
        self.pieces[0][s.PIECE_COMPOSER] = ""
        self.assert_one_error_containing(s.PIECE_COMPOSER)

    def test_duplicate_id(self):
        self.pieces[1][s.PIECE_ID] = self.pieces[0][s.PIECE_ID]
        self.assert_one_error_containing("重複")

    def test_bad_id_format(self):
        self.books[0][s.BOOK_ID] = "1"
        for piece in self.pieces:
            if piece[s.PIECE_BOOK_ID] == "B0001":
                piece[s.PIECE_BOOK_ID] = "1"
        self.assert_one_error_containing("格式不對")

    def test_same_title_twice_in_one_book(self):
        self.pieces[1][s.PIECE_TITLE] = "  la candeur  (op. 100 no. 1)"
        self.assert_one_error_containing("同一首曲子")

    def test_same_title_by_different_composers_is_allowed(self):
        # Found on a real contents page: Haydn's "C major" and Mozart's "C major".
        self.pieces[1][s.PIECE_TITLE] = self.pieces[0][s.PIECE_TITLE]
        self.pieces[1][s.PIECE_COMPOSER] = "Mozart"
        report = self.run_validator()
        self.assertEqual(report.errors, [])

    def test_page_must_be_positive_integer(self):
        self.pieces[0][s.PIECE_PAGE] = "2a"
        self.assert_one_error_containing("頁碼")

    def test_book_needs_location_or_link(self):
        self.books[0][s.BOOK_LOCATION] = ""
        self.assert_one_error_containing("位置")

    def test_location_format(self):
        self.books[0][s.BOOK_LOCATION] = "A2"
        self.assert_one_error_containing("A-2-05")

    def test_missing_column_stops_early(self):
        columns = [c for c in s.BOOK_COLUMNS if c != s.BOOK_TYPE]
        write_csv(self.tmp / "b.csv", columns, [{c: r[c] for c in columns} for r in self.books])
        write_csv(self.tmp / "p.csv", s.PIECE_COLUMNS, self.pieces)
        report = v.validate(self.tmp / "b.csv", self.tmp / "p.csv", SAMPLE / "選項.csv")
        self.assertEqual(len(report.errors), 1)
        self.assertIn(s.BOOK_TYPE, report.errors[0])

    def test_cli_exit_codes(self):
        script = str(ROOT / "tools" / "validate_catalog.py")
        ok = subprocess.run(
            [sys.executable, script, str(SAMPLE / "書籍.csv"), str(SAMPLE / "曲目.csv"), str(SAMPLE / "選項.csv")],
            capture_output=True,
        )
        self.assertEqual(ok.returncode, 0)
        self.pieces[0][s.PIECE_LEVEL] = "初級"
        write_csv(self.tmp / "b.csv", s.BOOK_COLUMNS, self.books)
        write_csv(self.tmp / "p.csv", s.PIECE_COLUMNS, self.pieces)
        bad = subprocess.run(
            [sys.executable, script, str(self.tmp / "b.csv"), str(self.tmp / "p.csv"), str(SAMPLE / "選項.csv")],
            capture_output=True,
        )
        self.assertEqual(bad.returncode, 1)


class SampleConsistencyTests(unittest.TestCase):
    def test_vocab_sample_matches_schema(self):
        rows = read_csv(SAMPLE / "選項.csv")
        for field_name, values in s.VOCAB.items():
            self.assertEqual([r[field_name] for r in rows if r[field_name]], values)

    def test_sample_headers_match_schema(self):
        self.assertEqual(list(read_csv(SAMPLE / "書籍.csv")[0]), s.BOOK_COLUMNS)
        self.assertEqual(list(read_csv(SAMPLE / "曲目.csv")[0]), s.PIECE_COLUMNS)


class ExtractionHelperTests(unittest.TestCase):
    def test_next_number(self):
        self.assertEqual(next_number([], s.BOOK_ID_PATTERN), 1)
        self.assertEqual(next_number(["B0001", "B0007", "", "x", "B0003"], s.BOOK_ID_PATTERN), 8)
        self.assertEqual(next_number(["P00009"], s.PIECE_ID_PATTERN), 10)

    def test_collect_sources(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "single.jpg").write_bytes(b"x")
        (tmp / "notes.txt").write_text("ignored")
        (tmp / ".DS_Store").write_bytes(b"x")
        book = tmp / "two_pages"
        book.mkdir()
        (book / "02.png").write_bytes(b"x")
        (book / "01.png").write_bytes(b"x")
        (tmp / "empty").mkdir()
        sources = collect_sources(tmp)
        self.assertEqual([src.name for src in sources], ["single.jpg", "two_pages"])
        self.assertEqual([p.name for p in sources[1].pages], ["01.png", "02.png"])

    def test_to_rows_numbers_and_notes(self):
        data = {
            "book_title": "Sonatinas Op. 36",
            "series": "",
            "pieces": [
                {"title": " Sonatina No. 1 ", "composer": "Clementi", "page": "p. 2", "unsure": False},
                {"title": "Sonatina No. 2", "composer": "Clementi", "page": "", "unsure": True},
            ],
        }
        empty = {"book_title": "", "series": "", "pieces": []}
        books, pieces = to_rows(
            [Extraction(BookSource("op36", []), data), Extraction(BookSource("cover.jpg", []), empty)], 4, 10
        )
        self.assertEqual([b[s.BOOK_ID] for b in books], ["B0004", "B0005"])
        self.assertEqual(books[1][s.BOOK_TITLE], "cover.jpg")  # falls back to the file name
        self.assertEqual(books[0][s.BOOK_TYPE], "")              # left for the reviewer
        self.assertEqual([p[s.PIECE_ID] for p in pieces], ["P00010", "P00011"])
        self.assertEqual(pieces[0][s.PIECE_TITLE], "Sonatina No. 1")
        self.assertEqual(pieces[0][s.PIECE_PAGE], "2")
        self.assertIn("不確定", pieces[1][s.PIECE_NOTES])
        self.assertEqual(set(pieces[0]), set(s.PIECE_INPUT_COLUMNS))


class ConfigAndPrivacyTests(unittest.TestCase):
    def test_parse_env(self):
        import config

        text = '# comment\n\nANTHROPIC_API_KEY="abc"\nexport OTHER=x=y\nEMPTY=\nnot a line\n'
        self.assertEqual(config.parse_env(text), {"ANTHROPIC_API_KEY": "abc", "OTHER": "x=y", "EMPTY": ""})

    def test_load_env_does_not_override_shell(self):
        import os
        import config

        env = Path(tempfile.mkdtemp()) / ".env"
        env.write_text("PIANO_TEST_A=from_file\nPIANO_TEST_B=from_file\n")
        os.environ["PIANO_TEST_A"] = "from_shell"
        os.environ.pop("PIANO_TEST_B", None)
        try:
            config.load_env(env)
            self.assertEqual(os.environ["PIANO_TEST_A"], "from_shell")
            self.assertEqual(os.environ["PIANO_TEST_B"], "from_file")
        finally:
            os.environ.pop("PIANO_TEST_A", None)
            os.environ.pop("PIANO_TEST_B", None)

    def test_gitignore_excludes_secrets_and_client_material(self):
        """Ask git itself, so the test checks real ignore behaviour, not text."""
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".gitignore").write_text((ROOT / ".gitignore").read_text())
        if subprocess.run(["git", "init", "-q", str(tmp)], capture_output=True).returncode != 0:
            self.skipTest("git not available")
        ignored = [".env", ".env.local", "secrets/google_token.json", "secrets/google_oauth_client.json",
                   "input/toc_photos/book.jpg", "output/擷取_曲目.csv"]
        tracked = [".env.example", "secrets/README.md", "input/toc_photos/README.md", "output/README.md"]
        for rel in ignored + tracked:
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_text("x")
        for rel in ignored:
            r = subprocess.run(["git", "-C", str(tmp), "check-ignore", "-q", rel])
            self.assertEqual(r.returncode, 0, f"{rel} should be ignored")
        for rel in tracked:
            r = subprocess.run(["git", "-C", str(tmp), "check-ignore", "-q", rel])
            self.assertEqual(r.returncode, 1, f"{rel} should be tracked")

    def test_env_example_has_no_value(self):
        import config

        values = config.parse_env((ROOT / ".env.example").read_text())
        self.assertEqual(values.get("ANTHROPIC_API_KEY"), "")


class SearchSheetTests(unittest.TestCase):
    def test_manual_shows_the_generated_formula(self):
        manual = (ROOT / "docs" / "04_管理者手冊.md").read_text(encoding="utf-8")
        self.assertIn(s.search_formula(), manual)

    def test_manual_headers_match_search_columns(self):
        manual = (ROOT / "docs" / "04_管理者手冊.md").read_text(encoding="utf-8")
        headers = [c.replace("（自動）", "") for c in s.SEARCH_COLUMNS]
        self.assertIn("、".join(f"`{h}`" for h in headers), manual)

    def test_column_letter(self):
        self.assertEqual([s.column_letter(n) for n in (1, 14, 26, 27, 52)], ["A", "N", "Z", "AA", "AZ"])

    def test_expected_search_row(self):
        from setup_google_sheet import expected_search_row, pad, sample_rows

        book, piece = sample_rows()
        row = expected_search_row(book, piece)
        self.assertEqual(row[:5], ["La Candeur (Op. 100 No. 1)", "Burgmüller", book[s.BOOK_TITLE], "2", "A-2-05"])
        self.assertEqual(pad(["a"], 3), ["a", "", ""])


@unittest.skipUnless(
    __import__("importlib").util.find_spec("openpyxl"), "openpyxl not installed"
)
class TemplateTests(unittest.TestCase):
    def test_template_structure(self):
        from openpyxl import load_workbook

        out = Path(tempfile.mkdtemp()) / "t.xlsx"
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_template.py"), "--rows", "20", "--out", str(out)],
            check=True, capture_output=True,
        )
        wb = load_workbook(out)
        self.assertEqual(wb.sheetnames, [s.GUIDE_SHEET, s.BOOK_SHEET, s.PIECE_SHEET, s.VOCAB_SHEET])
        pieces = wb[s.PIECE_SHEET]
        self.assertEqual([c.value for c in pieces[1]], s.PIECE_COLUMNS)
        # Lookup formulas reach the last pre-filled row and point at the right row.
        self.assertIn("$B21", pieces.cell(row=21, column=len(s.PIECE_COLUMNS)).value)
        # Every dropdown points at a range in the options sheet, without a leading "=".
        lists = [dv for dv in pieces.data_validations.dataValidation if dv.type == "list"]
        self.assertEqual(len(lists), 3)
        for dv in lists:
            self.assertTrue(dv.formula1.startswith(f"'{s.VOCAB_SHEET}'!"), dv.formula1)


if __name__ == "__main__":
    unittest.main()
