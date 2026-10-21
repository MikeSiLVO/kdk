"""The text report `kdk validate --report` writes."""

import os
import tempfile
import unittest

from kdk.core import save_report


class TestSaveReport(unittest.TestCase):
    """A validate result written as a text report."""

    def test_report_lists_each_issue_under_its_file(self):
        """The report lists each issue with its line under the file path relative to the skin."""
        with tempfile.TemporaryDirectory() as tmp:
            skin = os.path.join(tmp, "skin.test")
            issue = {"file": os.path.join(skin, "16x9", "Home.xml"), "line": 7,
                     "message": "Undefined font: Nope", "severity": "error"}
            result = {"skin_name": "skin.test", "skin_path": skin, "issues": {"Fonts": [issue]}}
            path = save_report(result, os.path.join(tmp, "report.txt"))
            with open(path, encoding="utf-8") as f:
                text = f.read()
        self.assertIn(os.path.join("16x9", "Home.xml"), text)
        self.assertIn("ERROR    line 7     Undefined font: Nope", text)


if __name__ == "__main__":
    unittest.main()
