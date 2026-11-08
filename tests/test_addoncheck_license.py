"""The license checks of the add-on checker (kdk-only)."""

import unittest

from addons import GPL_TEXT, METADATA, MIT_TEXT, AddonCase, clean_files
from kdk.addoncheck.licenses import identify, parse_spdx


def licensed(expression: str) -> dict:
    """Clean files with the <license> given."""
    return clean_files(metadata=METADATA.replace("GPL-2.0-or-later", expression))


class TestSpdx(unittest.TestCase):
    """The SPDX expression parser."""

    def test_valid_expressions(self):
        """Ids in any case, OR, AND, WITH, parentheses, + and LicenseRef parse."""
        for text in ("GPL-2.0-or-later", "MIT OR Apache-2.0", "(MIT AND BSD-3-Clause) OR GPL-3.0-only",
                     "GPL-2.0-only WITH Classpath-exception-2.0", "LGPL-2.1+", "LicenseRef-mine", "mit"):
            self.assertIsNone(parse_spdx(text)[1], text)

    def test_invalid_expressions(self):
        """Free text, lowercase operators and an unclosed group fail."""
        for text in ("GPL v2", "MIT or GPL-2.0-only", "(MIT", "GNU GENERAL PUBLIC LICENSE", "MIT OR"):
            self.assertIsNotNone(parse_spdx(text)[1], text)

    def test_identify(self):
        """The GPL v2 and MIT texts are told apart; other text is unknown."""
        self.assertEqual(identify(GPL_TEXT), "GPL-2.0")
        self.assertEqual(identify(MIT_TEXT), "MIT")
        self.assertIsNone(identify("All rights reserved."))


class TestLicenseRules(AddonCase):
    """The license file, tag, expression and their agreement."""

    def test_clean(self):
        """The clean add-on gives nothing."""
        self.assertEqual(self.rules(clean_files(), "license."), [])

    def test_file_missing_and_licenses_folder(self):
        """No license file is an error; a LICENSES/ folder counts."""
        files = clean_files()
        del files["LICENSE.txt"]
        self.assertEqual(self.rules(files, "license.file"), ["license.file-missing"])
        files["LICENSES/GPL-2.0-or-later.txt"] = GPL_TEXT
        self.assertEqual(self.rules(files, "license.file"), [])

    def test_tag_missing(self):
        """No <license> warns."""
        self.assertEqual(self.rules(clean_files(metadata=METADATA.replace(
            "<license>GPL-2.0-or-later</license>", "")), "license."), ["license.tag-missing"])

    def test_not_spdx(self):
        """Free text in <license> is an error."""
        self.assertEqual(self.rules(licensed("GNU GPL v2"), "license."), ["license.spdx"])

    def test_deprecated(self):
        """GPL-2.0 is a deprecated id; the GPL v2 file still matches it."""
        self.assertEqual(self.rules(licensed("GPL-2.0"), "license."), ["license.spdx-deprecated"])

    def test_mismatch_root_and_subfolder(self):
        """An MIT root file under a GPL tag is an error; in a subfolder it warns."""
        files = {**clean_files(), "LICENSE.txt": MIT_TEXT}
        self.assertEqual([r["severity"] for r in self.rows(files, "license.mismatch")], ["error"])
        files = {**clean_files(), "resources/lib/thing/LICENSE": MIT_TEXT}
        self.assertEqual([r["severity"] for r in self.rows(files, "license.mismatch")], ["warning"])
        self.assertEqual(self.rules({**files, "addon.xml": licensed("GPL-2.0-or-later OR MIT")["addon.xml"]},
                                    "license.mismatch"), [])

    def test_placeholder_in_code(self):
        """The GNU notice with <name of author> left in a comment."""
        files = {**clean_files(), "resources/lib/main.py": "# Copyright (C) <year>  <name of author>\n"}
        self.assertEqual(self.rules(files, "license.placeholder"), ["license.placeholder"])

    def test_full_gpl_text_keeps_its_appendix(self):
        """The full GPL carries the placeholders in its appendix and is not flagged."""
        files = {**clean_files(), "LICENSE.txt": GPL_TEXT + "TERMS AND CONDITIONS\n<name of author>\n"}
        self.assertEqual(self.rules(files, "license.placeholder"), [])


if __name__ == "__main__":
    unittest.main()
