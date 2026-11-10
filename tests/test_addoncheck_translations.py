"""The checks of translations against en_gb in the add-on checker (kdk-only)."""

import unittest

from addons import PO_HEADER, AddonCase, clean_files

EN_GB = "resources/language/resource.language.en_gb/strings.po"
DE_DE = "resources/language/resource.language.de_de/strings.po"


def entry(string_id: int, msgid: str, msgstr: str = "") -> str:
    """One strings.po entry."""
    return f'msgctxt "#{string_id}"\nmsgid "{msgid}"\nmsgstr "{msgstr}"\n\n'


class TestTranslations(AddonCase):
    """A translation against en_gb."""

    def rules_for(self, english: str, german: str, prefix: str = "lang.") -> list[str]:
        """Rule ids for an add-on with the en_gb and de_de entries given."""
        files = {**clean_files(), EN_GB: PO_HEADER + english, DE_DE: PO_HEADER + german}
        return self.rules(files, prefix)

    def test_orphan_id(self):
        """A translated id en_gb lacks is a hint."""
        self.assertEqual(self.rules_for(entry(32000, "Hello"), entry(32000, "Hello", "Hallo") +
                                        entry(32001, "Bye", "Tschuess")), ["lang.orphan-id"])

    def test_outdated_skips_the_placeholder_check(self):
        """A translation of an older English text warns once, without placeholder rows."""
        self.assertEqual(self.rules_for(entry(32000, "Hello %s"), entry(32000, "Hello", "Hallo")),
                         ["lang.outdated"])

    def test_format_placeholders(self):
        """In a string code reads, a missing %s, swapped tokens and a broken brace are errors."""
        reader = {"resources/lib/main.py": "import xbmcaddon\nx = xbmcaddon.Addon().getLocalizedString(32000)\n"}
        for english, german in (("Play %s", "Abspielen"), ("%s of %d", "%d von %s"), ("Testing {0}", "Test {0")):
            rows = self.rows({**clean_files(), **reader, EN_GB: PO_HEADER + entry(32000, english),
                              DE_DE: PO_HEADER + entry(32000, english, german)}, "lang.placeholders")
            self.assertEqual([r["severity"] for r in rows], ["error"], english)

    def test_settings_text_is_never_formatted(self):
        """A string only settings.xml reads is not compared, and "10 % davon" is no placeholder."""
        rows = self.rows({**clean_files(), EN_GB: PO_HEADER + entry(32000, "Play %s"),
                          DE_DE: PO_HEADER + entry(32000, "Play %s", "Abspielen")}, "lang.placeholders")
        self.assertEqual(rows, [])
        reader = {"resources/lib/main.py": "import xbmcaddon\nx = xbmcaddon.Addon().getLocalizedString(32000)\n"}
        rows = self.rows({**clean_files(), **reader, EN_GB: PO_HEADER + entry(32000, "at least 10% of it"),
                          DE_DE: PO_HEADER + entry(32000, "at least 10% of it", "mindestens 10 % davon")},
                         "lang.placeholders")
        self.assertEqual(rows, [])

    def test_markup(self):
        """An unclosed tag or a literal \\n warns; a dropped balanced pair hints; %% is ignored."""
        cases = (("[B]Hi[/B]", "[B]Hallo", "warning"), ("[B]Hi[/B]", "Hallo", "hint"),
                 ("A\\nB", "A\\\\nB", "warning"))
        for english, german, severity in cases:
            rows = self.rows({**clean_files(), EN_GB: PO_HEADER + entry(32000, english),
                              DE_DE: PO_HEADER + entry(32000, english, german)}, "lang.placeholders")
            self.assertEqual([r["severity"] for r in rows], [severity], german)
        self.assertEqual(self.rules_for(entry(32000, "100%% done") + entry(32001, "Hi"),
                                        entry(32000, "100%% done", "100%% fertig") + entry(32001, "Hi")), [])


class TestSource(AddonCase):
    """The en_gb file on its own and against addon.xml."""

    def test_en_gb_msgstr(self):
        """An en_gb msgstr unlike its msgid warns."""
        files = {**clean_files(), EN_GB: PO_HEADER + entry(32000, "Hello", "Hi there")}
        self.assertEqual(self.rules(files, "lang.en-gb"), ["lang.en-gb-msgstr"])

    def test_metadata_mismatch(self):
        """An Addon Summary entry unlike addon.xml's summary is a hint; the same text is not."""
        old = 'msgctxt "Addon Summary"\nmsgid "Shows another thing"\nmsgstr ""\n\n'
        files = {**clean_files(), EN_GB: PO_HEADER + old + entry(32000, "Hello")}
        self.assertEqual(self.rules(files, "lang.metadata"), ["lang.metadata-mismatch"])
        same = 'msgctxt "Addon Summary"\nmsgid "Shows  a thing"\nmsgstr ""\n\n'
        files = {**clean_files(), EN_GB: PO_HEADER + same + entry(32000, "Hello")}
        self.assertEqual(self.rules(files, "lang.metadata"), [])


if __name__ == "__main__":
    unittest.main()
