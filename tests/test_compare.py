"""`kdk compare`: which findings a head run adds, mutes or fixes against a base (kdk-only)."""

import json
import os
import subprocess
import sys
from pathlib import Path

from kdk import __version__
from kdk.output.compare import compare, mismatch

SRC = Path(__file__).resolve().parent.parent / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run(rows, **meta):
    """A saved run payload with its findings under one category."""
    return {"format_version": 1, "kdk_version": __version__, "kodi_release": "piers", "info_source": "snapshot",
            "notices": [], "skin_name": "skin.test", "errors": 0, "warnings": 0, "muted": 0,
            "categories": {"Fonts": rows}, **meta}


def row(line, subject="Nope", rule="fonts.undefined", file="16x9/Home.xml", **extra):
    """One finding row as `validate --json` writes it."""
    return {"file": file, "line": line, "rule": rule, "subject": subject, "message": f"{subject} at {line}",
            "severity": "error", **extra}


def statuses(payload):
    """Status, line and subject of each compare row, in output order."""
    return [(r["status"], r["line"], r["subject"]) for r in payload["rows"]]


def test_a_finding_that_moves_lines_is_neither_new_nor_fixed():
    """A shifted line is the same finding, rows matching on rule, file and subject."""
    assert statuses(compare(run([row(10)]), run([row(14)]))) == []


def test_duplicates_pair_by_nearest_line():
    """Of two head copies of one finding, the one far from the base copy is the new one."""
    payload = compare(run([row(10)]), run([row(11), row(40)]))
    assert statuses(payload) == [("new", 40, "Nope")]
    assert (payload["new"], payload["fixed"]) == (1, 0)


def test_unmatched_base_rows_are_fixed_and_a_new_subject_is_new():
    """A finding gone from head is fixed; one about another name is new, whatever its line."""
    payload = compare(run([row(10, "Old")]), run([row(10, "Other")]))
    assert statuses(payload) == [("new", 10, "Other"), ("fixed", 10, "Old")]


def test_muting_on_head_shows_with_its_reason_and_never_counts_as_new():
    """A new muted finding and one muted only on head list as muted, with the comment's reason."""
    mute = {"line": 3, "reason": "brand name"}
    payload = compare(run([row(10, "Kept"), row(20, "Both", muted=mute)]),
                      run([row(10, "Kept", muted=mute), row(20, "Both", muted=mute), row(30, "Fresh", muted=mute)]))
    assert [(r["status"], r["subject"], r["in_base"], r["muted"]["reason"]) for r in payload["rows"]] == [
        ("muted", "Kept", True, "brand name"), ("muted", "Fresh", False, "brand name")]
    assert (payload["new"], payload["muted"]) == (0, 2)


def test_one_finding_across_language_files_folds_into_one_row():
    """The same string id duplicated in every strings.po is one row with the count and files."""
    files = [f"language/resource.language.{code}/strings.po" for code in ("de_de", "en_gb", "fr_fr")]
    payload = compare(None, run([row(5, "31000", rule="repo.po-duplicate-id", file=f) for f in files]))
    assert len(payload["rows"]) == 1
    assert (payload["rows"][0]["count"], payload["rows"][0]["files"], payload["new"]) == (3, files, 3)


def test_no_base_makes_everything_new():
    """Against no base, every finding of a new skin is new."""
    payload = compare(None, run([row(1), row(2, "Other")]))
    assert ([r["status"] for r in payload["rows"]], payload["base"]) == (["new", "new"], False)


def test_runs_from_another_kdk_or_release_are_not_compared():
    """A different kdk version, format version or Kodi release stops the compare."""
    assert mismatch(run([]), run([])) is None
    assert "kdk versions" in (mismatch(run([], kdk_version="0.0.1"), run([])) or "")
    assert "Kodi releases" in (mismatch(run([], kodi_release="omega"), run([])) or "")
    assert "format versions" in (mismatch(run([], format_version=2), run([])) or "")


def test_same_inputs_give_the_same_rows_in_the_same_order():
    """The same inputs give the same rows in the same order, by status, then file and line."""
    base, head = run([row(3, "A"), row(9, "B")]), run([row(9, "C"), row(1, "D"), row(3, "A")])
    assert compare(base, head) == compare(base, head)
    assert statuses(compare(base, head)) == [("new", 1, "D"), ("new", 9, "C"), ("fixed", 9, "B")]


def kdk(*args):
    """Run kdk in a subprocess; returns the finished process."""
    code = "import sys; from kdk.__main__ import main; sys.argv = ['kdk'] + sys.argv[1:]; sys.exit(main())"
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env, check=False)


def test_cli_exits_one_on_new_findings_and_reads_saved_runs(tmp_path):
    """The compare command exits 1 when head adds a finding, 0 when not, and reads saved runs."""
    saved = tmp_path / "clean.json"
    assert kdk("validate", "--json", "--isolated", "--exit-zero", "-o", str(saved),
               str(FIXTURES / "clean_skin")).returncode == 0
    assert kdk("compare", "--json", "--isolated", str(saved), str(FIXTURES / "clean_skin")).returncode == 0
    proc = kdk("compare", "--json", "--isolated", str(saved), str(FIXTURES / "dirty_skin"))
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["new"] > 0


def test_cli_refuses_a_saved_run_from_another_kdk(tmp_path):
    """A saved run written by another kdk version exits 2 with the error object."""
    saved = tmp_path / "old.json"
    saved.write_text(json.dumps(run([], kdk_version="0.0.1")), encoding="utf-8")
    proc = kdk("compare", "--json", "--isolated", str(saved), str(FIXTURES / "clean_skin"))
    assert proc.returncode == 2
    assert "kdk versions" in json.loads(proc.stdout)["error"]
