"""Filtering, merging, sorting and grouping of the GUI's rows (kdk-only, no Qt needed)."""

from kdk.gui import issues


def _issue(file, line, severity="warning", message="m", **extra):
    """Issue dict with the fields the GUI reads."""
    return {"file": file, "line": line, "severity": severity, "message": message, "rule": "r", **extra}


def test_bucket_sorts_muted_errors_and_include_warnings_apart():
    """Muted wins, then errors, then warnings split by whether an include produced them."""
    assert issues.bucket(_issue("a", 1, muted=True)) == "muted"
    assert issues.bucket(_issue("a", 1, "error", include_name="X")) == "error"
    assert issues.bucket(_issue("a", 1, include_name="X")) == "include"
    assert issues.bucket(_issue("a", 1)) == "warning"


def test_counts_and_shown_issues_follow_the_search_text():
    """Counts and shown rows only cover issues the search matches, case ignored."""
    run = {"Fonts": [_issue("/s/Font.xml", 3, "error", "Bad font"), _issue("/s/Home.xml", 9, message="Other")]}
    assert issues.counts(run, "FONT") == {"error": 1, "warning": 0, "include": 0, "muted": 0}
    assert issues.shown_issues(run, {"warning"}, "") == {"Fonts": [run["Fonts"][1]]}
    assert issues.shown_issues(run, {"error", "warning"}, "home") == {"Fonts": [run["Fonts"][1]]}


def test_search_ignores_slash_direction():
    """A path typed with forward slashes finds a Windows path and the reverse."""
    windows = _issue("C:\\skin\\1080i\\Home.xml", 1)
    assert issues.matches(windows, "1080i/Home.xml")
    assert issues.matches(_issue("/skin/1080i/Home.xml", 1), "1080i\\home.xml")


def test_merged_row_holds_every_issue_it_joined():
    """A merged row holds the key of each line it lists, and no other."""
    run = {"XML": [_issue("/s/A.xml", 40), _issue("/s/A.xml", 12)]}
    (row,) = issues.build_rows(run, merge=True)
    assert row.holds(issues.issue_key("XML", run["XML"][0]))
    assert row.holds(issues.issue_key("XML", run["XML"][1]))
    assert not row.holds(issues.issue_key("XML", _issue("/s/A.xml", 41)))


def test_merge_joins_one_file_and_message_with_its_lines_in_order():
    """Repeats in one file merge with sorted lines; another file or a muted copy stays apart."""
    run = {"XML": [
        _issue("/s/A.xml", 40), _issue("/s/A.xml", 12), _issue("/s/B.xml", 5), _issue("/s/A.xml", 7, muted=True),
    ]}
    rows = issues.build_rows(run, merge=True)
    assert [row.lines for row in rows] == [[12, 40], [5], [7]]
    assert len(issues.build_rows(run, merge=False)) == 4


def test_sort_puts_errors_first_and_keeps_place_order_for_ties():
    """No column sorts errors first; a reversed column still breaks ties by file and line."""
    rows = issues.build_rows({"C": [
        _issue("/s/B.xml", 2), _issue("/s/A.xml", 9, "error"), _issue("/s/A.xml", 1, rule="z"),
    ]}, merge=False)
    assert [(r.issue["file"], r.issue["line"]) for r in issues.sort_rows(rows, None, True)] == [
        ("/s/A.xml", 9), ("/s/A.xml", 1), ("/s/B.xml", 2)]
    by_rule = issues.sort_rows(rows, "rule", descending=True)
    assert [r.issue["line"] for r in by_rule] == [1, 9, 2]


def test_groups_follow_check_order_or_errors_first():
    """Categories keep check order; files put those with errors first, each counting issues."""
    run = {"Labels": [_issue("/s/A.xml", 1)], "Fonts": [_issue("/s/B.xml", 2, "error"), _issue("/s/B.xml", 3, "error")]}
    rows = issues.build_rows(run, merge=True)
    assert [g.name for g in issues.group_rows(rows, "category", ["Fonts", "Labels"])] == ["Fonts", "Labels"]
    by_file = issues.group_rows(rows, "file", [])
    assert [(g.name, g.errors, g.warnings) for g in by_file] == [("/s/B.xml", 2, 0), ("/s/A.xml", 0, 1)]
    assert [g.name for g in issues.group_rows(rows, "none", [])] == [""]


def test_groups_count_muted_rows_apart_from_warnings():
    """A muted row counts as muted, not as a warning, in its group."""
    run = {"Labels": [_issue("/s/A.xml", 1), _issue("/s/A.xml", 2, muted=True)]}
    (group,) = issues.group_rows(issues.build_rows(run, merge=False), "category", ["Labels"])
    assert (group.errors, group.warnings, group.muted) == (0, 1, 1)
