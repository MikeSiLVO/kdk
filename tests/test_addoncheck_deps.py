"""The <import> checks of the add-on checker (kdk-only)."""

import unittest

from addons import IMPORTS, AddonCase, addon_xml, clean_files, index_entry


def with_import(line: str, base: str = IMPORTS) -> dict:
    """Clean files whose addon.xml adds the import line."""
    return clean_files(imports=base + "\n    " + line)


class TestCore(AddonCase):
    """Core imports against the branch's floor, ceiling and advised version."""

    def test_python_2(self):
        """xbmc.python below 3.0.0, which is also below omega's floor."""
        files = clean_files(imports='    <import addon="xbmc.python" version="2.25.0"/>')
        self.assertEqual(self.rules(files, "deps."), ["deps.abi-below-min", "deps.python-below-3"])

    def test_gui_below_the_floor(self):
        """xbmc.gui 5.14.0 on omega, whose floor is 5.17.0."""
        self.assertEqual(self.rules(with_import('<import addon="xbmc.gui" version="5.14.0"/>'), "deps.abi"),
                         ["deps.abi-below-min"])

    def test_gui_above_the_first_release(self):
        """xbmc.gui 5.18.0 on omega, which shipped 5.17.0; a lower minversion makes it fine."""
        self.assertEqual(self.rules(with_import('<import addon="xbmc.gui" version="5.18.0"/>'), "deps.abi"),
                         ["deps.abi-above-branch"])
        line = '<import addon="xbmc.gui" version="5.18.0" minversion="5.17.0"/>'
        self.assertEqual(self.rules(with_import(line), "deps.abi"), [])

    def test_not_advised(self):
        """xbmc.python 3.0.0 on omega is a hint; on matrix it is the advised one."""
        self.assertEqual(self.rules(clean_files(), "deps.not-advised"), ["deps.not-advised"])
        self.assertEqual(self.rules(clean_files(), "deps.not-advised", release="matrix"), [])

    def test_advice_above_the_ceiling_is_dropped(self):
        """Matrix advises xbmc.json 12.4.0 while its first release shipped 12.2.1."""
        files = with_import('<import addon="xbmc.json" version="6.0.0"/>')
        self.assertEqual(self.rules(files, "deps.not-advised", release="matrix"), [])

    def test_core_without_version(self):
        """A core import without a version is an error."""
        files = clean_files(imports='    <import addon="xbmc.python"/>')
        rows = self.rows(files, "deps.no-version")
        self.assertEqual([r["severity"] for r in rows], ["error"])


class TestModules(AddonCase):
    """Other imports against the branch's list."""

    def test_unavailable_and_optional(self):
        """A module the branch lacks is an error unless optional."""
        self.write_index("omega")
        self.assertEqual(self.rules(with_import('<import addon="script.module.nope" version="1.0.0"/>'),
                                    "deps.unavail"), ["deps.unavailable"])
        line = '<import addon="script.module.nope" version="1.0.0" optional="true"/>'
        self.assertEqual(self.rules(with_import(line), "deps.unavail"), [])

    def test_version_above_what_the_branch_holds(self):
        """A module needed at 2.0.0 while the branch holds 1.5.0."""
        self.write_index("omega", index_entry("script.module.foo", "1.5.0"))
        self.assertEqual(self.rules(with_import('<import addon="script.module.foo" version="2.0.0"/>'), "deps.v"),
                         ["deps.version-unavailable"])

    def test_module_without_version(self):
        """A module import without a version is a warning."""
        self.write_index("omega", index_entry("script.module.foo", "1.5.0"))
        rows = self.rows(with_import('<import addon="script.module.foo"/>'), "deps.no-version")
        self.assertEqual([r["severity"] for r in rows], ["warning"])

    def test_simplejson(self):
        """script.module.simplejson warns."""
        self.write_index("omega", index_entry("script.module.simplejson", "3.0.0"))
        self.assertEqual(self.rules(with_import('<import addon="script.module.simplejson" version="3.0.0"/>'),
                                    "deps.simple"), ["deps.simplejson"])


class TestExtensions(AddonCase):
    """Imports an extension point needs, and imports nothing needs."""

    def test_script_without_python(self):
        """xbmc.python.script needs xbmc.python."""
        files = clean_files(imports='    <import addon="script.module.foo" version="1.0.0"/>')
        self.assertEqual(self.rules(files, "deps.extension"), ["deps.extension-import"])

    def test_unneeded_core(self):
        """xbmc.addon, and xbmc.gui without window XML, are hints."""
        files = with_import('<import addon="xbmc.addon" version="21.0.0"/>')
        self.assertEqual(self.rules(files, "deps.unneeded"), ["deps.unneeded-core"])
        files = with_import('<import addon="xbmc.gui" version="5.17.0"/>')
        self.assertEqual(self.rules(files, "deps.unneeded"), ["deps.unneeded-core"])
        files["resources/skins/Default/1080i/main.xml"] = "<window/>"
        self.assertEqual(self.rules(files, "deps.unneeded"), [])


class TestConsumers(AddonCase):
    """A module nothing in the repo imports."""

    def module(self) -> dict:
        """Files of a module add-on."""
        xml = addon_xml("script.module.foo").replace(
            '<extension point="xbmc.python.script" library="default.py"/>',
            '<extension point="xbmc.python.module" library="lib"/>')
        return {**clean_files("script.module.foo"), "addon.xml": xml, "lib/foo/__init__.py": ""}

    def test_module_without_consumer(self):
        """No add-on on any branch imports it."""
        self.write_all_indexes()
        self.assertEqual(self.rules(self.module(), "deps.module", folder="script.module.foo"),
                         ["deps.module-no-consumer"])

    def test_consumer_on_an_older_branch(self):
        """An add-on on leia imports it."""
        self.write_all_indexes(("leia", index_entry("plugin.x", "1.0.0", imports=["script.module.foo"])))
        self.assertEqual(self.rules(self.module(), "deps.module", folder="script.module.foo"), [])

    def test_missing_branch_list_skips(self):
        """With a branch list missing the rule cannot decide and stays quiet."""
        self.write_index("omega")
        self.assertEqual(self.rules(self.module(), "deps.module", folder="script.module.foo"), [])


if __name__ == "__main__":
    unittest.main()
