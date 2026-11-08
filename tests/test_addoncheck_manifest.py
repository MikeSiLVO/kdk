"""The addon.xml checks of the add-on checker (kdk-only)."""

import unittest

from addons import IMPORTS, METADATA, AddonCase, addon_xml, clean_files, index_entry


class TestParse(AddonCase):
    """A missing or malformed addon.xml."""

    def test_missing_addon_xml_is_the_only_row(self):
        """A folder without addon.xml gives addon.missing alone."""
        result = self.run_check({"default.py": "pass\n"})
        rules = [r["rule"] for rows in result["issues"].values() for r in rows]
        self.assertEqual(rules, ["addon.missing"])

    def test_malformed_addon_xml_names_the_line(self):
        """A bare & in news is reported at its line, in plain words."""
        files = clean_files(metadata=METADATA.replace("first release", "fish & chips"))
        rows = self.rows(files, "addon.")
        self.assertEqual([r["rule"] for r in rows], ["addon.parse"])
        self.assertEqual(rows[0]["line"], 12)
        self.assertIn("&amp;", rows[0]["message"])


class TestVersion(AddonCase):
    """The version's form and its place against the branches."""

    def test_bad_version_form(self):
        """A version with a space fails the repo's pattern."""
        self.assertEqual(self.rules(clean_files(version="1.0 beta"), "addon.version"), ["addon.version-format"])

    def test_two_part_version_is_style_only(self):
        """1.0 passes the repo's pattern and gets the style warning."""
        self.assertEqual(self.rules(clean_files(version="1.0"), "addon.version"), ["addon.version-style"])

    def test_suffixes_pass_the_style(self):
        """Suffixes such as +matrix.1 and ~beta1 are fine."""
        self.assertEqual(self.rules(clean_files(version="1.0.0+matrix.1"), "addon.version"), [])
        self.assertEqual(self.rules(clean_files(version="1.0.0~beta1"), "addon.version"), [])

    def test_not_higher_than_this_or_an_older_branch(self):
        """Equal to omega's copy and below leia's copy: one row per branch."""
        self.write_index("omega", index_entry("script.test", "1.0.0"))
        self.write_index("leia", index_entry("script.test", "2.0.0"))
        rows = self.rows(clean_files(), "addon.version-not-higher")
        self.assertEqual(sorted(r["subject"] for r in rows), ["leia", "omega"])

    def test_beta_counts_below_its_release(self):
        """1.0.0~beta1 on the branch is below 1.0.0."""
        self.write_index("omega", index_entry("script.test", "1.0.0~beta1"))
        self.assertEqual(self.rules(clean_files(), "addon.version-not-higher"), [])

    def test_newer_branch_with_a_rising_core_floor_is_an_error(self):
        """A matrix build at omega's version importing xbmc.gui, whose floor rises on omega."""
        imports = IMPORTS + '\n    <import addon="xbmc.gui" version="5.15.0"/>'
        self.write_index("omega", index_entry("script.test", "1.0.0"))
        self.write_copies(omega=True)
        rows = self.rows(clean_files(imports=imports), "addon.version-above-newer", release="matrix")
        self.assertEqual([(r["subject"], r["severity"]) for r in rows], [("omega", "error")])

    def test_newer_branch_without_a_rising_floor_is_a_warning(self):
        """An omega build at piers' version with only xbmc.python, whose floor stays."""
        self.write_index("piers", index_entry("script.test", "1.0.0"))
        self.write_copies(piers=True)
        rows = self.rows(clean_files(), "addon.version-above-newer")
        self.assertEqual([(r["subject"], r["severity"]) for r in rows], [("piers", "warning")])

    def test_newer_branch_without_its_own_copy(self):
        """Newer branch with only fallback copy gives no row; one not in copies.json, a notice."""
        self.write_index("piers", index_entry("script.test", "1.0.0"))
        self.write_copies(piers=False)
        self.assertEqual(self.rules(clean_files(), "addon.version-above-newer"), [])
        self.write_copies()
        result = self.run_check(clean_files())
        rules = [r["rule"] for rows in result["issues"].values() for r in rows]
        self.assertNotIn("addon.version-above-newer", rules)
        self.assertTrue(any("copies.json" in n and "Piers" in n for n in result["notices"]))

    def test_no_index_skips_with_a_notice(self):
        """Without an index folder the branch rules are skipped and one notice says so."""
        result = self.run_check(clean_files(), index=False)
        self.assertEqual(len(result["notices"]), 1)
        self.assertIn("index", result["notices"][0])


class TestId(AddonCase):
    """The id against its folder and the form of a new id."""

    def test_id_differs_from_folder(self):
        """An id unlike the folder name."""
        self.assertEqual(self.rules(clean_files("script.other"), "addon.id"), ["addon.id-folder"])

    def test_new_id_with_uppercase(self):
        """A new add-on whose id has a capital letter."""
        self.write_index("omega")
        rows = self.rules(clean_files("script.Test"), "addon.id-format", folder="script.Test")
        self.assertEqual(rows, ["addon.id-format"])

    def test_new_id_without_its_prefix(self):
        """A new script named like a plugin."""
        self.write_index("omega")
        self.assertEqual(self.rules(clean_files("plugin.test"), "addon.id-format", folder="plugin.test"),
                         ["addon.id-format"])

    def test_update_keeps_its_id(self):
        """An id the branch already lists is never questioned."""
        self.write_index("omega", index_entry("plugin.test", "0.9.0"))
        self.assertEqual(self.rules(clean_files("plugin.test"), "addon.id-format", folder="plugin.test"), [])


class TestSchema(AddonCase):
    """The schemas, with the causes named in plain words."""

    def test_clean_addon_passes(self):
        """The clean add-on raises no schema row."""
        self.assertEqual(self.rules(clean_files(), "addon.schema"), [])

    def test_summary_without_lang(self):
        """The schema needs lang on <summary>; the message says Kodi reads it as en_GB."""
        files = clean_files(metadata=METADATA.replace('<summary lang="en_GB">', "<summary>"))
        rows = self.rows(files, "addon.schema")
        self.assertEqual([r["subject"] for r in rows], ["summary@lang"])
        self.assertIn("en_GB", rows[0]["message"])

    def test_news_with_lang(self):
        """The schema refuses lang on <news>."""
        files = clean_files(metadata=METADATA.replace("<news>", '<news lang="en_GB">'))
        self.assertEqual([r["subject"] for r in self.rows(files, "addon.schema")], ["news@lang"])

    def test_platform_kodi_knows(self):
        """Kodi reads the tvos platform, which the schema's list lacks."""
        files = clean_files(metadata=METADATA + "\n    <platform>tvos</platform>")
        rows = self.rows(files, "addon.schema")
        self.assertEqual([r["subject"] for r in rows], ["platform@tvos"])

    def test_news_over_the_limit(self):
        """News over 1500 characters names its length."""
        files = clean_files(metadata=METADATA.replace("first release", "x" * 1600))
        rows = self.rows(files, "addon.schema")
        self.assertEqual(len(rows), 1)
        self.assertIn("1500", rows[0]["message"])

    def test_service_start_is_its_own_rule(self):
        """A start attribute on xbmc.service is reported once, as addon.service-start."""
        xml = addon_xml().replace('<extension point="xbmc.python.script" library="default.py"/>',
                                  '<extension point="xbmc.service" library="default.py" start="login"/>')
        files = {**clean_files(), "addon.xml": xml}
        self.assertEqual(self.rules(files, "addon.s"), ["addon.service-start"])

    def test_unknown_point(self):
        """An extension point the repo does not know, without a second root schema row."""
        xml = addon_xml().replace("xbmc.python.script", "xbmc.python.nothing")
        files = {**clean_files(), "addon.xml": xml}
        self.assertEqual(self.rules(files, "addon.extension-point"), ["addon.extension-point"])
        self.assertEqual(self.rules(files, "addon.schema"), [])


class TestExtensions(AddonCase):
    """Metadata present and entry points that exist."""

    def test_no_metadata(self):
        """An addon.xml without the metadata extension."""
        xml = addon_xml().split('  <extension point="xbmc.addon.metadata">')[0] + "</addon>\n"
        files = {**clean_files(), "addon.xml": xml}
        self.assertIn("addon.no-metadata", self.rules(files, "addon."))

    def test_missing_entry_point(self):
        """A library that is not in the folder."""
        files = clean_files()
        del files["default.py"]
        self.assertEqual(self.rules(files, "addon.entrypoint-missing"), ["addon.entrypoint-missing"])


class TestMetadata(AddonCase):
    """Languages, news, links, placeholders and the name."""

    def test_translations_without_en_gb(self):
        """Two summaries, neither en_GB, is an error."""
        meta = METADATA.replace('<summary lang="en_GB">Shows a thing</summary>',
                                '<summary lang="de_DE">Zeigt</summary><summary lang="fr_FR">Montre</summary>')
        rows = self.rows(clean_files(metadata=meta), "addon.lang-en-gb")
        self.assertEqual([(r["subject"], r["severity"]) for r in rows], [("summary", "error")])

    def test_single_variant_in_another_language(self):
        """One summary with lang="en" warns twice: not en_GB, and not ll_CC."""
        meta = METADATA.replace('<summary lang="en_GB">', '<summary lang="en">')
        self.assertEqual(self.rules(clean_files(metadata=meta), "addon.lang"), ["addon.lang-en-gb",
                                                                                "addon.lang-format"])

    def test_news_missing_and_repeated(self):
        """No news warns; two news for one language warns."""
        self.assertEqual(self.rules(clean_files(metadata=METADATA.replace("<news>v1.0.0 - first release</news>",
                                                                          "")), "addon.news"),
                         ["addon.news-missing"])
        meta = METADATA.replace("</news>", "</news><news>again</news>")
        self.assertEqual(self.rules(clean_files(metadata=meta), "addon.news"), ["addon.news-multiple"])

    def test_changelog_beside_news(self):
        """changelog.txt beside news is a hint."""
        files = {**clean_files(), "changelog.txt": "v1.0.0\n"}
        self.assertEqual(self.rules(files, "addon.changelog"), ["addon.changelog-file"])

    def test_empty_email(self):
        """An empty <email> warns."""
        files = clean_files(metadata=METADATA + "\n    <email></email>")
        self.assertEqual(self.rules(files, "addon.empty"), ["addon.empty-element"])

    def test_forum_links(self):
        """A forum index warns; a thread in either URL form does not."""
        meta = METADATA.replace("showthread.php?tid=12345", "forumdisplay.php?fid=26")
        self.assertEqual(self.rules(clean_files(metadata=meta), "addon.forum"), ["addon.forum-url"])
        meta = METADATA.replace("showthread.php?tid=12345", "thread-12345.html")
        self.assertEqual(self.rules(clean_files(metadata=meta), "addon.forum"), [])

    def test_placeholders(self):
        """An example.com website is an error, TODO in the description a warning."""
        meta = METADATA + "\n    <website>https://www.example.com/addon</website>"
        meta = meta.replace("on screen.", "on screen. TODO")
        rows = self.rows(clean_files(metadata=meta), "addon.placeholder")
        self.assertEqual(sorted((r["subject"], r["severity"]) for r in rows),
                         [("description", "warning"), ("website", "error")])

    def test_name_with_kodi(self):
        """Kodi as a word in the name is a hint; a module is left alone."""
        self.assertEqual(self.rules(clean_files(name="Kodi Helper"), "addon.name"), ["addon.name-kodi"])
        files = clean_files("script.module.six", name="Kodi Six")
        self.assertEqual(self.rules(files, "addon.name", folder="script.module.six"), [])


class TestBroken(AddonCase):
    """A broken submission gets only the version, id and Python import checks."""

    def test_broken_skips_the_rest(self):
        """A broken add-on with an unknown point and no license gets no row for either."""
        xml = addon_xml(metadata=METADATA + "\n    <lifecyclestate type=\"broken\">Gone</lifecyclestate>")
        xml = xml.replace("xbmc.python.script", "xbmc.python.nothing")
        result = self.run_check({"addon.xml": xml})
        rules = [r["rule"] for rows in result["issues"].values() for r in rows]
        self.assertEqual(rules, [])
        self.assertIn("broken", result["notices"][0])


if __name__ == "__main__":
    unittest.main()
