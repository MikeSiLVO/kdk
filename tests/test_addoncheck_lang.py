"""The language folder and strings.po checks of the add-on checker (kdk-only)."""

import unittest

from addons import PO_HEADER, AddonCase, clean_files, index_entry

EN_GB = "resources/language/resource.language.en_gb/strings.po"


class TestFolders(AddonCase):
    """Folder layout, place, codes and case."""

    def test_old_layout(self):
        """resources/language/English is the old layout."""
        files = {**clean_files(), "resources/language/English/strings.po": PO_HEADER}
        self.assertEqual(self.rules(files, "lang.layout"), ["lang.layout"])

    def test_outside_resources_language(self):
        """A top-level language/ folder is never read for an add-on."""
        files = {**clean_files(), "language/resource.language.de_de/strings.po": PO_HEADER}
        self.assertEqual(self.rules(files, "lang.base"), ["lang.base-folder"])

    def test_strings_xml(self):
        """A strings.xml under resources/language."""
        files = {**clean_files(), "resources/language/resource.language.de_de/strings.xml": "<strings/>"}
        self.assertEqual(self.rules(files, "lang.strings"), ["lang.strings-xml"])

    def test_invalid_code(self):
        """resource.language.english has no language code."""
        files = {**clean_files(), "resources/language/resource.language.english/strings.po": PO_HEADER}
        self.assertEqual(self.rules(files, "lang.code"), ["lang.code-invalid"])

    def test_unknown_code_but_not_en_gb(self):
        """A code no language add-on carries is dead; en_gb ships in Kodi and is never listed."""
        self.write_index("omega", index_entry("resource.language.de_de", "1.0.0", points=["kodi.resource.language"]))
        files = {**clean_files(), "resources/language/resource.language.de_de/strings.po": PO_HEADER,
                 "resources/language/resource.language.ga/strings.po": PO_HEADER}
        self.assertEqual([r["subject"] for r in self.rows(files, "lang.code")], ["resource.language.ga"])

    def test_uppercase_folder(self):
        """resource.language.de_DE warns."""
        self.write_index("omega", index_entry("resource.language.de_de", "1.0.0", points=["kodi.resource.language"]))
        files = {**clean_files(), "resources/language/resource.language.de_DE/strings.po": PO_HEADER}
        self.assertEqual(self.rules(files, "lang.folder"), ["lang.folder-case"])

    def test_no_en_gb(self):
        """Translations without en_gb."""
        files = clean_files()
        files["resources/language/resource.language.de_de/strings.po"] = files.pop(EN_GB)
        self.assertEqual(self.rules(files, "lang.no-en"), ["lang.no-en-gb"])

    def test_settings_without_strings(self):
        """Settings and no strings.po at all is a hint."""
        files = clean_files()
        del files[EN_GB]
        self.assertEqual(self.rules(files, "lang.no"), ["lang.no-po"])


class TestPo(AddonCase):
    """One strings.po on its own."""

    def po(self, text: str) -> list[str]:
        """Rule ids for a run whose en_gb strings.po holds the text."""
        return self.rules({**clean_files(), EN_GB: text}, "lang.")

    def test_clean(self):
        """The clean file gives nothing."""
        self.assertEqual(self.rules(clean_files(), "lang."), [])

    def test_missing_header(self):
        """No msgid "" / msgstr "" header."""
        self.assertEqual(self.po('msgctxt "#32000"\nmsgid "Hi"\nmsgstr ""\n'), ["lang.po-header"])

    def test_bom(self):
        """A byte order mark."""
        self.assertIn("lang.po-bom", self.po(chr(0xFEFF) + PO_HEADER))

    def test_crlf(self):
        """Windows line endings warn."""
        self.assertEqual(self.po((PO_HEADER + 'msgctxt "#32000"\nmsgid "Hi"\nmsgstr ""\n').replace("\n", "\r\n")),
                         ["lang.po-crlf"])

    def test_duplicate_id(self):
        """One id twice warns."""
        entry = 'msgctxt "#32000"\nmsgid "Hi"\nmsgstr ""\n\n'
        self.assertEqual(self.po(PO_HEADER + entry + entry), ["lang.duplicate-id"])

    def test_broken_string(self):
        """A string that never closes."""
        self.assertIn("lang.po-broken-string", self.po(PO_HEADER + 'msgctxt "#32000"\nmsgid "Hi\nmsgstr ""\n'))

    def test_msgctxt_forms(self):
        """A bare number and two msgctxt in one entry are skipped; metadata contexts are fine."""
        text = (PO_HEADER + 'msgctxt "32001"\nmsgid "A"\nmsgstr ""\n\n'
                'msgctxt "#32002"\nmsgctxt "#32003"\nmsgid "B"\nmsgstr ""\n\n'
                'msgctxt "Addon Summary"\nmsgid "Shows a thing"\nmsgstr ""\n')
        rows = self.rows({**clean_files(), EN_GB: text}, "lang.msgctxt")
        self.assertEqual(sorted(r["subject"] for r in rows), ["#32003", "32001"])


if __name__ == "__main__":
    unittest.main()
