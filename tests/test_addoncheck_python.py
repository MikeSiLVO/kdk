"""The Python syntax and entry point checks of the add-on checker (kdk-only)."""

import sys
import unittest

from addons import AddonCase, clean_files


class TestNewerSyntax(AddonCase):
    """Syntax newer than Python 3.8 that the oldest-Python parse lets through."""

    def test_parenthesized_context_managers(self):
        """Bracketed with items need 3.10; a bracketed expression before as does not."""
        files = {**clean_files(), "resources/lib/a.py": "with (open('a') as f, open('b') as g):\n    pass\n",
                 "resources/lib/b.py": "with (open('a')) as f:\n    pass\n"}
        self.assertEqual([r["subject"] for r in self.rows(files, "py.syntax")], ["resources/lib/a.py"])

    @unittest.skipIf(sys.version_info < (3, 12), "only Python 3.12 tokenizes nested f-string quotes")
    def test_same_quote_fstring(self):
        """A string in an f-string reusing its quotes needs 3.12; other quotes are fine."""
        files = {**clean_files(), "resources/lib/a.py": 'x = f"{d["k"]}"\n',
                 "resources/lib/b.py": "x = f\"{d['k']}\"\n"}
        self.assertEqual([r["subject"] for r in self.rows(files, "py.syntax")], ["resources/lib/a.py"])


class TestSyntax(AddonCase):
    """Python files that must decode and parse on the oldest Python."""

    def test_python_2_print(self):
        """A print statement does not parse."""
        files = {**clean_files(), "resources/lib/old.py": "print 'hi'\n"}
        rows = self.rows(files, "py.syntax")
        self.assertEqual([(r["subject"], r["line"]) for r in rows], [("resources/lib/old.py", 1)])

    def test_match_needs_python_3_10(self):
        """A match statement parses on the running Python but not on 3.8."""
        files = {**clean_files(), "resources/lib/new.py": "match x:\n    case 1:\n        pass\n"}
        rows = self.rows(files, "py.syntax")
        self.assertEqual(len(rows), 1)
        self.assertIn("3.8", rows[0]["message"])

    def test_not_utf8(self):
        """A Latin-1 file does not decode."""
        files = {**clean_files(), "resources/lib/latin.py": "x = 'caf\u00e9'\n".encode("latin-1")}
        self.assertEqual(self.rules(files, "py."), ["py.syntax"])

    def test_bom_is_fine(self):
        """A UTF-8 byte order mark is accepted."""
        files = {**clean_files(), "resources/lib/bom.py": "\ufeffx = 1\n".encode("utf-8")}
        self.assertEqual(self.rules(files, "py."), [])


class TestEntryPoint(AddonCase):
    """Entry point size."""

    def test_fifteen_logical_lines_warn(self):
        """15 statements warn, 14 do not."""
        self.assertEqual(self.rules({**clean_files(), "default.py": "x = 1\n" * 15}, "py."),
                         ["py.entrypoint-complex"])
        self.assertEqual(self.rules({**clean_files(), "default.py": "x = 1\n" * 14}, "py."), [])


if __name__ == "__main__":
    unittest.main()
