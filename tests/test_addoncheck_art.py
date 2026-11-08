"""The artwork checks of the add-on checker (kdk-only)."""

import unittest

from addons import METADATA, AddonCase, clean_files, jpeg, png


def assets(inner: str) -> dict:
    """Clean files whose <assets> holds the inner XML."""
    meta = METADATA.split("<assets>")[0] + f"<assets>{inner}</assets>"
    return clean_files(metadata=meta)


class TestArtwork(AddonCase):
    """Declared images and their specs."""

    def test_clean(self):
        """The clean add-on gives nothing."""
        self.assertEqual(self.rules(clean_files(), "art."), [])

    def test_undeclared_and_missing(self):
        """A root icon.png outside <assets> is an error; a listed image that is absent too."""
        files = {**assets("<fanart>resources/fanart.jpg</fanart>"), "icon.png": png(256, 256)}
        self.assertEqual(self.rules(files, "art."), ["art.undeclared"])
        files = assets("<icon>resources/nope.png</icon><fanart>resources/fanart.jpg</fanart>")
        self.assertEqual(self.rules(files, "art."), ["art.missing"])

    def test_no_icon_or_fanart(self):
        """Neither declared nor in the root warns; a module needs no fanart."""
        self.assertEqual(self.rules(assets(""), "art."), ["art.no-fanart", "art.no-icon"])
        files = {**assets(""), "addon.xml": assets("")["addon.xml"].replace('id="script.test"',
                                                                             'id="script.module.test"')}
        self.assertEqual(self.rules(files, "art.", folder="script.module.test"), ["art.no-icon"])

    def test_empty_tag(self):
        """An empty <screenshot> warns."""
        self.assertIn("art.empty-tag", self.rules(assets("<icon>resources/icon.png</icon>"
                                                         "<fanart>resources/fanart.jpg</fanart><screenshot/>"),
                                                  "art."))

    def test_type_is_case_sensitive(self):
        """ICON.PNG fails the extension list, as the repo's checker compares it."""
        files = {**assets("<icon>resources/ICON.PNG</icon><fanart>resources/fanart.jpg</fanart>"),
                 "resources/ICON.PNG": png(256, 256)}
        self.assertEqual(self.rules(files, "art."), ["art.type"])

    def test_transparency(self):
        """A transparent icon and a solid clearlogo are both errors."""
        files = {**clean_files(), "resources/icon.png": png(256, 256, alpha=0)}
        self.assertEqual(self.rules(files, "art."), ["art.transparency"])
        files = {**assets("<icon>resources/icon.png</icon><fanart>resources/fanart.jpg</fanart>"
                          "<clearlogo>resources/logo.png</clearlogo>"), "resources/logo.png": png(400, 155)}
        self.assertEqual(self.rules(files, "art."), ["art.transparency"])

    def test_size_and_file_size(self):
        """A 100x100 icon is the wrong size; a 1.1 MB fanart is too large."""
        self.assertEqual(self.rules({**clean_files(), "resources/icon.png": png(100, 100)}, "art."), ["art.size"])
        files = {**clean_files(), "resources/fanart.jpg": jpeg(1280, 720, padding=1100 * 1024)}
        self.assertEqual(self.rules(files, "art."), ["art.file-size"])

    def test_unreadable_and_unlisted_screenshot(self):
        """A damaged image errors; an unlisted screenshot is a hint."""
        files = {**clean_files(), "resources/broken.png": b"not an image",
                 "resources/screenshots/one.jpg": jpeg(1280, 720)}
        self.assertEqual(self.rules(files, "art."), ["art.screenshot-unlisted", "art.unreadable"])


if __name__ == "__main__":
    unittest.main()
