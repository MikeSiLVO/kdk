"""The string id and untranslated text checks of the add-on checker (kdk-only)."""

import unittest

from addons import PO_HEADER, AddonCase, addon_xml, clean_files

EN_GB = "resources/language/resource.language.en_gb/strings.po"
SKIN_XML = "resources/skins/Default/1080i/script-test-main.xml"


def defined(*ids: int) -> str:
    """An en_gb strings.po defining the ids."""
    return PO_HEADER + "".join(f'msgctxt "#{i}"\nmsgid "Text {i}"\nmsgstr ""\n\n' for i in ids)


def code(body: str) -> dict:
    """Clean files with resources/lib/main.py holding the body and en_gb defining 32000."""
    return {**clean_files(), "resources/lib/main.py": "import xbmc\nimport xbmcaddon\nimport xbmcgui\n" + body}


class TestMissing(AddonCase):
    """Ids read from the add-on's own strings that en_gb lacks."""

    def test_direct_alias_and_wrapper(self):
        """Direct, aliased and wrapped lookups of undefined ids are all errors."""
        body = ("ADDON = xbmcaddon.Addon()\nLANGUAGE = ADDON.getLocalizedString\n"
                "def localize(i):\n    return ADDON.getLocalizedString(i)\n"
                "a = xbmcaddon.Addon().getLocalizedString(32005)\nb = LANGUAGE(32006)\nc = localize(32007)\n")
        rows = self.rows(code(body), "strings.missing")
        self.assertEqual(sorted(r["subject"] for r in rows), ["32005", "32006", "32007"])

    def test_settings_fall_back_to_kodi(self):
        """A settings id Kodi defines is fine; one nobody defines is an error."""
        files = clean_files()
        files["resources/settings.xml"] = ('<settings version="1"><section id="script.test">'
                                           '<category id="general" label="32000"><group id="1">'
                                           '<setting id="a" type="boolean" label="186" help="39999"/>'
                                           '</group></category></section></settings>')
        self.assertEqual([r["subject"] for r in self.rows(files, "strings.missing")], ["39999"])

    def test_addon_macro_and_context_label(self):
        """Context menu labels and $ADDON[] naming this add-on read its strings; others' do not."""
        files = {**clean_files(), SKIN_XML: "<window><controls><control type=\"label\">"
                                            "<label>$ADDON[script.test 32008]</label>"
                                            "<label2>$ADDON[script.other 32009]</label2>"
                                            "</control></controls></window>"}
        files["addon.xml"] = addon_xml().replace(
            '<extension point="xbmc.addon.metadata">',
            '<extension point="kodi.context.item"><menu id="kodi.core.main"><item library="default.py">'
            '<label>32010</label><visible>true</visible></item></menu></extension>\n'
            '  <extension point="xbmc.addon.metadata">')
        self.assertEqual(sorted(r["subject"] for r in self.rows(files, "strings.missing")), ["32008", "32010"])


class TestLookups(AddonCase):
    """Own ids read as Kodi's, id ranges, unused ids and a missing strings.po."""

    def test_core_lookup(self):
        """xbmc.getLocalizedString and a bare skin label of an own id warn; a Kodi id does not."""
        files = {**code("x = xbmc.getLocalizedString(32000)\n"),
                 SKIN_XML: "<window><controls><control type=\"label\"><label>32000</label></control>"
                           "<control type=\"label\"><label>186</label></control></controls></window>"}
        rows = self.rows(files, "strings.core")
        self.assertEqual(sorted(r["file"].rsplit("/", 1)[-1] for r in rows), ["main.py", "script-test-main.xml"])

    def test_wrapper_of_both_lookups_is_no_core_lookup(self):
        """A wrapper that calls either lookup also reads the add-on's strings and is not flagged."""
        body = ("def text(i):\n    if i < 32000:\n        return xbmc.getLocalizedString(i)\n"
                "    return xbmcaddon.Addon().getLocalizedString(i)\nx = text(32000)\n")
        self.assertEqual(self.rules(code(body), "strings.core"), [])

    def test_ranges(self):
        """Ids outside the add-on ranges, and own skin-range ids in its windows, are hints."""
        files = {**clean_files(), EN_GB: defined(32000, 33000, 31001),
                 SKIN_XML: "<window><label>$ADDON[script.test 31001]</label><label>$ADDON[script.test 33000]"
                           "</label></window>"}
        self.assertEqual(sorted(r["subject"] for r in self.rows(files, "strings.range")),
                         ["31001", "31001", "33000"])

    def test_unused_unless_ids_are_computed(self):
        """An id nothing reads is a hint, unless the code looks up computed ids."""
        files = {**clean_files(), EN_GB: defined(32000, 32001)}
        self.assertEqual([r["subject"] for r in self.rows(files, "strings.unused")], ["32001"])
        files = {**files, "resources/lib/main.py": "import xbmcaddon\nn = 1\nxbmcaddon.Addon().getLocalizedString(n)\n"}
        self.assertEqual(self.rules(files, "strings.unused"), [])

    def test_no_po_with_ids_and_no_settings(self):
        """Reading string ids with no strings.po at all is a hint even without settings."""
        files = code("x = xbmcaddon.Addon().getLocalizedString(32000)\n")
        del files[EN_GB], files["resources/settings.xml"]
        self.assertEqual(self.rules(files, "lang.no-po"), ["lang.no-po"])


class TestHardcoded(AddonCase):
    """Text shown to users written in code or settings.xml."""

    def test_dialog_and_list_item_text(self):
        """Literal dialog text and list item labels warn, through an instance too."""
        body = ('xbmcgui.Dialog().ok("Error", "Something failed")\n'
                'dialog = xbmcgui.Dialog()\ndialog.notification("Test", "Done")\n'
                'item = xbmcgui.ListItem(label="Play now")\n')
        self.assertEqual(sorted(r["subject"] for r in self.rows(code(body), "strings.hardcoded")),
                         ["Done", "Error", "Play now", "Something failed"])

    def test_product_names(self):
        """The provider and a whole word of the add-on name pass as headings; other text warns."""
        body = 'xbmcgui.Dialog().yesno("WeTrakr", "Mark as unwatched?")\nxbmcgui.Dialog().ok("Someone", "Done")\n'
        files = {**code(body), "addon.xml": addon_xml(name="WeTrakr Scrobbler")}
        self.assertEqual(sorted(r["subject"] for r in self.rows(files, "strings.hardcoded")),
                         ["Done", "Mark as unwatched?"])

    def test_not_ui_text(self):
        """The add-on name, format-only strings, markup, URLs and logging are left alone."""
        body = ('xbmcgui.Dialog().ok("Test", "%s [CR]")\n'
                'xbmcgui.Dialog().ok("https://example.org", "{} - {}")\nxbmc.log("Starting up")\n')
        self.assertEqual(self.rules(code(body), "strings.hardcoded"), [])

    def test_settings_text(self):
        """A settings label written as text warns; an option's label does not."""
        files = clean_files()
        files["resources/settings.xml"] = ('<settings version="1"><section id="script.test">'
                                           '<category id="general" label="Volume"><group id="1">'
                                           '<setting id="lang" type="string" label="32000"><constraints><options>'
                                           '<option label="Deutsch">de</option></options></constraints>'
                                           '</setting></group></category></section></settings>')
        self.assertEqual([r["subject"] for r in self.rows(files, "strings.hardcoded")], ["Volume"])


if __name__ == "__main__":
    unittest.main()
