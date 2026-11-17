"""The release the GUI checks a skin against and whether that release loads it (kdk-only, no Qt)."""

from kdk.gui import skins


def _skin(tmp_path, gui_version):
    """Skin folder whose addon.xml imports xbmc.gui at the version."""
    (tmp_path / "addon.xml").write_text(
        '<addon id="skin.test" version="1.0.0">\n<requires>\n'
        f'<import addon="xbmc.gui" version="{gui_version}"/>\n</requires>\n</addon>\n', encoding="utf-8")
    return str(tmp_path)


def test_gui_import_reads_the_version_and_its_line(tmp_path):
    """The import's version and line come back; a folder without addon.xml gives nothing."""
    assert skins.gui_import(_skin(tmp_path, "5.16.0")) == ("5.16.0", 3)
    assert skins.gui_import(str(tmp_path / "missing")) == ("", 0)


def test_implied_release_is_the_oldest_covering_the_import():
    """Each import maps to the oldest release covering it; past them all or missing, the newest."""
    assert skins.implied_release("5.16.0") == "omega"
    assert skins.implied_release("5.17.0") == "omega"
    assert skins.implied_release("5.18.0") == "piers"
    assert skins.implied_release("5.19.0") == "piers"
    assert skins.implied_release("") == "piers"


def test_needed_import_names_the_version_a_release_loads():
    """A release that cannot load the import names its version; otherwise nothing comes back."""
    assert skins.needed_import("5.16.0", "piers") == "5.18.0"
    assert skins.needed_import("5.17.0", "piers") == ""
    assert skins.needed_import("5.18.0", "omega") == "5.17.0"
    assert skins.needed_import("5.17.0", "omega") == ""
    assert skins.needed_import("", "piers") == ""
