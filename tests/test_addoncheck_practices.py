"""The Python practice checks of the add-on checker (kdk-only)."""

import unittest

from addons import AddonCase, clean_files


def code(body: str) -> dict:
    """Clean files with resources/lib/main.py holding the body."""
    return {**clean_files(), "resources/lib/main.py": body}


class TestFloors(AddonCase):
    """Annotations and standard library names newer than Python 3.8."""

    def test_annotations(self):
        """Builtin generics and unions in evaluated annotations fail; local and string ones pass."""
        body = ("def f(a: list[int]) -> dict[str, int]:\n    b: list[int] = []\n    return {}\n"
                "x: int | None = None\ny: 'list[int]' = []\n")
        self.assertEqual(len(self.rows(code(body), "py.annotations")), 3)
        self.assertEqual(self.rules(code("from __future__ import annotations\n" + body), "py.annotations"), [])

    def test_stdlib_names_and_guards(self):
        """The removeprefix, tomllib, functools.cache and zip strict uses warn unless guarded."""
        body = ("import functools\nimport sys\ns = 'ab'.removeprefix('a')\nimport tomllib\n"
                "@functools.cache\ndef f():\n    return 1\nz = zip([1], [2], strict=True)\n"
                "try:\n    t = s.removesuffix('b')\nexcept AttributeError:\n    t = s\n"
                "if sys.version_info >= (3, 11):\n    import tomllib as toml\n")
        self.assertEqual(sorted(r["subject"] for r in self.rows(code(body), "py.stdlib")),
                         [".removeprefix()", "functools.cache", "tomllib", "zip(strict=...)"])

    def test_union_in_isinstance(self):
        """A union in isinstance fails on 3.8 even with the future import; a tuple does not."""
        body = "from __future__ import annotations\nok = isinstance(1, int | str)\nfine = isinstance(1, (int, str))\n"
        rows = self.rows(code(body), "py.annotations")
        self.assertEqual([(r["subject"], r["severity"]) for r in rows], [("int | str", "error")])

    def test_levels_on_piers(self):
        """On piers 3.9 names and generics pass, 3.10 to 3.13 hint, 3.14 fails; omega warns."""
        body = ("import itertools\nimport annotationlib\nfrom warnings import deprecated\n"
                "def f(a: list[int], b: dict[str, int | None]) -> None:\n    return None\n"
                "s = 'ab'.removeprefix('a')\np = itertools.pairwise([1, 2])\n@deprecated('x')\ndef g():\n    pass\n")
        rows = self.rows(code(body), "py.", release="piers")
        self.assertEqual(sorted((r["subject"], r["severity"]) for r in rows),
                         [("annotationlib", "error"), ("dict[str, int | None]", "hint"),
                          ("itertools.pairwise", "hint"), ("warnings.deprecated", "hint")])
        self.assertIn("Debian 12 has 3.11", next(r["message"] for r in rows if r["subject"] == "warnings.deprecated"))
        omega = self.rows(code(body), "py.stdlib")
        self.assertEqual({r["severity"] for r in omega}, {"warning"})
        self.assertEqual(len(omega), 4)


class TestHabits(AddonCase):
    """Sleeps, prints, sys.path, own ids, paths, Kodi files, timeouts and strptime."""

    def test_sleeps(self):
        """A sleep in a loop warns; a long one elsewhere is a hint; a short one is fine."""
        body = ("import time\nimport xbmc\nwhile True:\n    time.sleep(1)\ntime.sleep(5)\ntime.sleep(0.1)\n"
                "xbmc.sleep(500)\nxbmc.sleep(2000)\n")
        self.assertEqual(sorted((r["line"], r["severity"]) for r in self.rows(code(body), "py.sleep")),
                         [(4, "warning"), (5, "hint"), (8, "hint")])

    def test_bounded_loops(self):
        """A range loop warns once its sleeps reach a second; a loop over items always warns."""
        body = ("import time\nimport xbmc\nfor i in range(5):\n    xbmc.sleep(30)\nfor i in range(10):\n"
                "    time.sleep(0.5)\nfor item in items:\n    xbmc.sleep(delay)\n")
        self.assertEqual(sorted((r["line"], r["severity"]) for r in self.rows(code(body), "py.sleep")),
                         [(6, "warning"), (8, "warning")])

    def test_sleep_after_abort(self):
        """A sleep that runs only once waitForAbort returned True is left alone, even in a loop."""
        body = ("import time\nimport xbmc\nmonitor = xbmc.Monitor()\nwhile True:\n"
                "    if monitor.waitForAbort(0.2):\n        for i in range(4):\n            time.sleep(0.1)\n"
                "        break\n")
        self.assertEqual(self.rules(code(body), "py.sleep"), [])

    def test_print_and_sys_path(self):
        """A print warns unless it writes elsewhere or runs as __main__; sys.path changes warn."""
        body = ("import sys\nprint('x')\nprint('y', file=sys.stderr)\nsys.path.insert(0, 'lib')\n"
                "sys.path += ['lib']\nif __name__ == '__main__':\n    print('z')\n")
        self.assertEqual(self.rules(code(body), "py."), ["py.print", "py.sys-path", "py.sys-path"])

    def test_own_id_paths_and_kodi_files(self):
        """Own id, a home path, other add-on data and a database get rows; comparisons do not."""
        body = ("import xbmcaddon\na = xbmcaddon.Addon('script.test')\nb = xbmcaddon.Addon('script.other')\n"
                "p = '/home/me/file.txt'\nok = p.startswith('/storage/')\n"
                "q = 'special://profile/addon_data/script.other/settings.xml'\n"
                "r = 'special://profile/addon_data/script.test/cache'\ndb = 'MyVideos131.db'\n")
        self.assertEqual(sorted((r["rule"], r["severity"]) for r in self.rows(code(body), "py.")),
                         [("py.absolute-path", "warning"), ("py.addon-own-id", "hint"),
                          ("py.kodi-files", "hint"), ("py.kodi-files", "warning")])

    def test_timeouts_and_strptime(self):
        """Requests without a timeout, also on a session, and strptime are hints."""
        body = ("import requests\nfrom datetime import datetime\nrequests.get('u')\nrequests.get('u', timeout=5)\n"
                "s = requests.Session()\ns.post('u')\nd = datetime.strptime('2020', '%Y')\n")
        self.assertEqual(self.rules(code(body), "py."), ["py.requests-timeout", "py.requests-timeout", "py.strptime"])


class TestCodeScope(AddonCase):
    """Bundled modules, keys, and development folders left out."""

    def test_vendored_module(self):
        """A bundled requests package is a hint, and its own code is not checked."""
        files = {**clean_files(), "resources/lib/requests/__init__.py": "print('x')\n"}
        self.assertEqual(self.rules(files, "py."), ["py.vendored-module"])

    def test_plaintext_keys(self):
        """A key-shaped literal warns; placeholders, short values and decoded values do not."""
        body = ("import base64\nAPI_KEY = 'abcdef0123456789abcd'\nTOKEN = 'YOUR_TOKEN_GOES_HERE_OK'\n"
                "SECRET = base64.b64decode('YWJjZGVmMDEyMzQ1Njc4OQ==')\nheaders = {'password': 'short'}\n")
        self.assertEqual([r["subject"] for r in self.rows(code(body), "py.plaintext")], ["API_KEY"])
        files = clean_files()
        files["resources/settings.xml"] = ('<settings version="1"><section id="script.test"><category id="a" '
                                           'label="32000"><group id="1"><setting id="api_key" type="string" '
                                           'label="32000"><default>abcdef0123456789abcd</default></setting>'
                                           '</group></category></section></settings>')
        rows = self.rows(files, "py.plaintext")
        self.assertEqual([r["subject"] for r in rows if r["file"].endswith("settings.xml")], ["api_key"])

    def test_development_folders_left_out(self):
        """Code under tests/ gets the files.dev row and no Python rows."""
        files = {**clean_files(), "tests/test_main.py": "import sys\nprint('x')\nsys.path.insert(0, 'lib')\n"}
        self.assertEqual(self.rules(files, "py."), [])


if __name__ == "__main__":
    unittest.main()
