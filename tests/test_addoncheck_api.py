"""The Kodi Python API checks of the add-on checker (kdk-only)."""

import unittest

from addons import AddonCase, clean_files

HEADER = "import json\nimport xbmc\nimport xbmcaddon\nimport xbmcgui\nimport xbmcvfs\n"


def code(body: str) -> dict:
    """Clean files with resources/lib/main.py holding the Kodi imports and the body."""
    return {**clean_files(), "resources/lib/main.py": HEADER + body}


class TestTranslatePath(AddonCase):
    """The xbmc.translatePath rule per branch, and its fallbacks."""

    def test_error_from_nexus_warning_on_matrix(self):
        """An error on omega, a warning on matrix, through an import too."""
        files = code("a = xbmc.translatePath('special://home')\n")
        self.assertEqual([r["severity"] for r in self.rows(files, "py.translatepath")], ["error"])
        self.assertEqual([r["severity"] for r in self.rows(files, "py.translatepath", release="matrix")],
                         ["warning"])
        files = code("from xbmc import translatePath\nb = translatePath('special://home')\n")
        self.assertEqual(self.rules(files, "py.translatepath"), ["py.translatepath"])

    def test_fallbacks(self):
        """After xbmcvfs in an or, or in an AttributeError handler, it is left alone."""
        body = ("tp = getattr(xbmcvfs, 'translatePath', None) or xbmc.translatePath\n"
                "try:\n    t = xbmcvfs.translatePath\nexcept AttributeError:\n    t = xbmc.translatePath\n")
        self.assertEqual(self.rules(code(body), "py.translatepath"), [])


class TestRemoved(AddonCase):
    """Names and arguments that raise at run time."""

    def test_removed_names(self):
        """LOGNOTICE, abortRequested and setIconImage raise; Monitor().abortRequested() is fine."""
        body = ("xbmc.log('x', xbmc.LOGNOTICE)\nif xbmc.abortRequested:\n    pass\n"
                "li = xbmcgui.ListItem('a')\nli.setIconImage('i.png')\nok = xbmc.Monitor().abortRequested()\n")
        self.assertEqual(sorted(r["subject"] for r in self.rows(code(body), "py.removed")),
                         ["xbmc.LOGNOTICE", "xbmc.abortRequested", "xbmcgui.ListItem.setIconImage"])

    def test_removed_arguments(self):
        """Removed keywords, a non-bool fourth argument and extra dialog arguments all fail."""
        body = ("a = xbmcgui.ListItem('a', iconImage='i.png')\nb = xbmcgui.ListItem('a', 'b', 'p', 'x')\n"
                "c = xbmcgui.ListItem('a', 'b', 'p', True)\nxbmcgui.Dialog().yesno('h', line1='x')\n"
                "xbmcgui.Dialog().ok('h', 'a', 'b')\nd = xbmcgui.DialogProgress()\nd.create('h', 'l1', 'l2')\n")
        self.assertEqual(len(self.rows(code(body), "py.removed")), 5)

    def test_start_server_wait(self):
        """The wait argument of startServer is gone from nexus on."""
        files = code("xbmc.startServer(1, True, False)\n")
        self.assertEqual(self.rules(files, "py.removed", release="nexus"), ["py.removed-api"])
        self.assertEqual(self.rules(files, "py.removed", release="matrix"), [])


class TestDeprecated(AddonCase):
    """Names that log a warning, and names deprecated in the docs."""

    def test_logged_from_nexus(self):
        """The setInfo, ResumeTime and getVotes uses warn on omega, not on matrix."""
        body = ("li = xbmcgui.ListItem('a')\nli.setInfo('video', {'title': 'x'})\nli.setProperty('ResumeTime', '10')\n"
                "v = li.getVideoInfoTag().getVotes()\n")
        self.assertEqual(len(self.rows(code(body), "py.deprecated-logged")), 3)
        self.assertEqual(self.rules(code(body), "py.deprecated-logged", release="matrix"), [])

    def test_fanart_only_on_piers(self):
        """ListItem.setAvailableFanart warns on piers only."""
        files = code("li = xbmcgui.ListItem('a')\nli.setAvailableFanart([])\n")
        self.assertEqual(self.rules(files, "py.deprecated", release="piers"), ["py.deprecated-logged"])
        self.assertEqual(self.rules(files, "py.deprecated"), [])

    def test_documented(self):
        """Addon.getSettingBool is a hint."""
        files = code("ADDON = xbmcaddon.Addon()\nx = ADDON.getSettingBool('a')\n")
        self.assertEqual(self.rules(files, "py.deprecated"), ["py.deprecated-doc"])


class TestCalls(AddonCase):
    """Zero waits, inputstreamaddon, Notification builtins and JSON-RPC payloads."""

    def test_wait_for_abort(self):
        """0, negative and sub-millisecond timeouts wait forever; 1 and no argument do not count."""
        body = ("m = xbmc.Monitor()\nm.waitForAbort(0)\nm.waitForAbort(-1)\nm.waitForAbort(0.0001)\n"
                "m.waitForAbort(1)\nm.waitForAbort()\n")
        self.assertEqual(len(self.rows(code(body), "py.waitforabort")), 3)

    def test_inputstreamaddon_and_notification(self):
        """The old property name warns, a Notification builtin is a hint."""
        body = ("li = xbmcgui.ListItem('a')\nli.setProperty('inputstreamaddon', 'inputstream.adaptive')\n"
                "xbmc.executebuiltin('Notification(Test, Done)')\n")
        self.assertEqual(self.rules(code(body), "api."), ["api.inputstreamaddon", "api.notification-builtin"])

    def test_jsonrpc_schema(self):
        """An unknown property and an unknown method fail; method names match in any case."""
        body = ("xbmc.executeJSONRPC('{\"jsonrpc\": \"2.0\", \"method\": \"VideoLibrary.GetMovies\", "
                "\"params\": {\"properties\": [\"title\", \"nope\"]}, \"id\": 1}')\n"
                "xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'method': 'VideoLibrary.GetMoviez', 'id': 1}))\n"
                "xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'method': 'videolibrary.getmovies', 'id': 1}))\n")
        self.assertEqual(sorted(r["subject"] for r in self.rows(code(body), "api.jsonrpc")),
                         ["VideoLibrary.GetMovies nope", "VideoLibrary.GetMoviez"])


if __name__ == "__main__":
    unittest.main()
