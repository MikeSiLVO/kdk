"""The file checks of the add-on checker (kdk-only)."""

import os
import unittest

from addons import AddonCase, clean_files


class TestUnwanted(AddonCase):
    """Git, development and documentation files."""

    def test_git_files(self):
        """The .github/ folder and .gitignore are git files, one row each."""
        files = {**clean_files(), ".github/workflows/ci.yml": "on: push\n", ".gitignore": "*.pyc\n"}
        self.assertEqual(sorted(r["subject"] for r in self.rows(files, "files.git")), [".github/", ".gitignore"])

    def test_dev_folder_once(self):
        """A tests/ folder is one row, and its files get no whitelist row."""
        files = {**clean_files(), "tests/test_x.py": "", "tests/data.bin": ""}
        self.assertEqual(self.rules(files, "files."), ["files.dev"])

    def test_dev_files(self):
        """pyproject.toml and a .pyc are development files."""
        files = {**clean_files(), "pyproject.toml": "", "resources/lib/x.pyc": b"\x00"}
        self.assertEqual(sorted(r["subject"] for r in self.rows(files, "files.dev")),
                         ["pyproject.toml", "resources/lib/x.pyc"])

    def test_bundled_code_keeps_its_packaging(self):
        """A bundled package's setup.py is left alone; its __pycache__ is not."""
        files = {**clean_files(), "resources/lib/requests/__init__.py": "", "resources/lib/requests/setup.py": "",
                 "resources/lib/requests/__pycache__/x.pyc": b"\x00"}
        self.assertEqual([r["subject"] for r in self.rows(files, "files.dev")],
                         ["resources/lib/requests/__pycache__/"])

    def test_docs_and_examples(self):
        """A docs/ folder and an example script warn."""
        files = {**clean_files(), "docs/readme.md": "", "example_use.py": ""}
        self.assertEqual(self.rules(files, "files.dev-docs"), ["files.dev-docs", "files.dev-docs"])

    def test_tests_config(self):
        """A shipped .tests-config.json is an error."""
        self.assertEqual(self.rules({**clean_files(), ".tests-config.json": "{}"}, "files.tests"),
                         ["files.tests-config"])


class TestEndingsAndModes(AddonCase):
    """Whitelisted endings, executables and binaries."""

    def test_whitelist(self):
        """A .bin file warns; a module skips the whitelist."""
        self.assertEqual(self.rules({**clean_files(), "resources/data.bin": ""}, "files.white"), ["files.whitelist"])
        files = {**clean_files("script.module.x"), "resources/data.bin": ""}
        self.assertEqual(self.rules(files, "files.white", folder="script.module.x"), [])

    def test_executable_from_the_tree(self):
        """A 100755 blob in --tree output is executable, with the add-on folder prefix stripped."""
        tree = os.path.join(self.tmp, "tree.txt")
        with open(tree, "w", encoding="utf-8") as f:
            f.write("100644 blob aaa\tscript.test/addon.xml\n100755 blob bbb\tscript.test/default.py\n")
        rows = self.rows(clean_files(), "files.executable", tree=tree)
        self.assertEqual([r["subject"] for r in rows], ["default.py"])

    def test_every_file_executable_is_a_drive_without_modes(self):
        """When every file reads executable the check is skipped with a notice."""
        path = self.make(clean_files())
        for root, _, names in os.walk(path):
            for name in names:
                os.chmod(os.path.join(root, name), 0o755)
        result = self.run_check({})
        self.assertFalse([r for rows in result["issues"].values() for r in rows if r["rule"] == "files.executable"])
        self.assertTrue(any("executable" in n for n in result["notices"]))

    def test_binary_by_magic(self):
        """A file starting with the ELF magic is a binary whatever its name."""
        files = {**clean_files(), "resources/lib/helper": b"\x7fELF\x02\x01"}
        self.assertEqual(self.rules(files, "files.binary"), ["files.binary"])


class TestNamesAndParsing(AddonCase):
    """Case clashes, non-ASCII names, XML, JSON and nested add-ons."""

    def test_case_clash(self):
        """Two files that differ only by case."""
        files = {**clean_files(), "resources/Data.txt": "", "resources/data.txt": ""}
        self.assertEqual(self.rules(files, "files.case"), ["files.case-clash"])

    def test_non_ascii_name(self):
        """A file name with non-ASCII characters is a hint."""
        self.assertEqual(self.rules({**clean_files(), "resources/caf" + chr(0xE9) + ".txt": ""}, "files.non"),
                         ["files.non-ascii-name"])

    def test_bad_xml_and_json(self):
        """Malformed XML and JSON each give a row at their line."""
        files = {**clean_files(), "resources/bad.xml": "<a>\n<b></a>", "resources/bad.json": '{\n"a": }'}
        rows = self.rows(files, "files.")
        self.assertEqual(sorted((r["rule"], r["line"]) for r in rows), [("files.json-invalid", 2),
                                                                        ("files.xml-invalid", 2)])

    def test_nested_addon(self):
        """A folder holding its own addon.xml."""
        files = {**clean_files(), "extra/addon.xml": "<addon/>"}
        self.assertEqual(self.rules(files, "files.nested"), ["files.nested-addon"])


if __name__ == "__main__":
    unittest.main()
