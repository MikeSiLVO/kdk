"""Muted findings in kdk's own output: counts, JSON, the text report and the exit code."""

import json
import os

from kdk.core import save_report
from kdk.output.payload import severity_counts, unmuted
from kdk.output.render import count_cells
from tests.test_cli import _process

ADDON_XML = """<?xml version="1.0" encoding="UTF-8"?>
<addon id="skin.test" version="1.0.0" name="Test Skin" provider-name="Test">
    <requires>
        <import addon="xbmc.gui" version="5.15.0"/>
    </requires>
    <extension point="xbmc.gui.skin" debugging="false">
        <res width="1920" height="1080" aspect="16:9" default="true" folder="16x9" />
    </extension>
</addon>
"""


def make_skin(tmp_path, label_line):
    """Make a skin whose Home.xml holds one label control, its label written as given on line 4."""
    skin = tmp_path / "skin.test"
    (skin / "16x9").mkdir(parents=True)
    (skin / "addon.xml").write_text(ADDON_XML, encoding="utf-8")
    (skin / "16x9" / "Home.xml").write_text(
        '<window>\n<controls>\n<control type="label">\n' + label_line + '\n</control>\n</controls>\n</window>\n',
        encoding="utf-8")
    return skin


def test_muted_finding_is_kept_in_json_and_never_fails_the_run(tmp_path):
    """A muted label comes back marked in the JSON, counted apart, and leaves --strict at 0."""
    skin = make_skin(tmp_path, "<label>Untranslated text</label> <!-- kdk-ignore: labels; testing -->")

    proc = _process("validate", "--json", "--strict", "--isolated", "--category", "labels", str(skin))

    payload = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert (payload["errors"], payload["warnings"], payload["muted"]) == (0, 0, 1)
    assert payload["categories"]["Labels"][0]["muted"] == {"line": 4, "reason": "testing"}


def test_same_finding_unmuted_fails_the_strict_run(tmp_path):
    """Without the comment the same label is a warning that --strict fails on."""
    skin = make_skin(tmp_path, "<label>Untranslated text</label>")

    proc = _process("validate", "--json", "--strict", "--isolated", "--category", "labels", str(skin))

    assert proc.returncode == 1, proc.stderr
    assert json.loads(proc.stdout)["muted"] == 0


def test_counts_keep_muted_apart():
    """A muted issue counts only as muted, whatever its severity."""
    rows = [{"severity": "error"}, {"severity": "warning", "muted": {"line": 1, "reason": ""}},
            {"severity": "warning"}]

    assert severity_counts(rows) == (1, 1, 1)


def test_unmuted_drops_muted_rows_and_emptied_categories():
    """The terminal list gets every unmuted row, and no category left with none."""
    issues = {"Labels": [{"message": "a", "muted": {"line": 1, "reason": ""}}],
              "Fonts": [{"message": "b"}, {"message": "c", "muted": {"line": 2, "reason": ""}}]}

    assert unmuted(issues) == {"Fonts": [{"message": "b"}]}


def test_count_cells_puts_muted_last():
    """The muted count follows the others in the same cell, and leads when nothing else is there."""
    assert count_cells(1, 0, 2) == ("[red]1[/]", "[red]error[/], [dim]2 muted[/]")
    assert count_cells(0, 0, 3) == ("[dim]3[/]", "[dim]muted[/]")
    assert count_cells(0, 0) == ("[yellow]0[/]", "[yellow]warnings[/]")


def test_saved_report_notes_a_muted_issue(tmp_path):
    """The text report lists the muted issue under its note and counts it apart."""
    skin = str(tmp_path / "skin.test")
    issue = {"file": os.path.join(skin, "16x9", "Home.xml"), "line": 4, "message": "Label not translated",
             "severity": "warning", "muted": {"line": 4, "reason": "debug overlay"}}
    result = {"skin_name": "skin.test", "skin_path": skin, "issues": {"Labels": [issue]}}

    with open(save_report(result, str(tmp_path / "report.txt")), encoding="utf-8") as f:
        text = f.read()

    assert (f"  {os.path.join('16x9', 'Home.xml')}  (1 muted warning)\n"
            "    Muted by kdk-ignore at line 4: debug overlay\n"
            "      WARNING  line 4     Label not translated\n") in text
    assert "Total:     0 errors, 0 warnings, 1 muted" in text
