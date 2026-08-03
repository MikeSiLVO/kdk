"""Unit tests for the GitHub Actions annotation output (kdk-only, no editor counterpart)."""

from kdk.output.render import render_github


def annotations(capsys):
    """Just the workflow-command lines from what was printed."""
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith("::")]


def issue(severity, message, path="/repo/16x9/Home.xml", line=10):
    return {"severity": severity, "message": message, "file": path, "line": line}


def test_severity_picks_the_annotation_level(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_WORKSPACE", "/repo")

    render_github({"Images": [issue("error", "boom"), issue("warning", "meh"), issue(None, "fyi")]})

    levels = [line.split(" ", 1)[0] for line in annotations(capsys)]
    assert levels == ["::error", "::warning", "::notice"]


def test_path_is_relative_to_the_workspace(capsys, monkeypatch):
    """GitHub anchors annotations to the checkout root, not the skin root."""
    monkeypatch.setenv("GITHUB_WORKSPACE", "/repo")

    render_github({"Images": [issue("error", "boom", path="/repo/skin/16x9/Home.xml")]})

    assert "file=skin/16x9/Home.xml," in annotations(capsys)[0]


def test_percent_and_newline_escaped_in_message(capsys, monkeypatch):
    """A raw newline would end the command early and swallow the rest of the message."""
    monkeypatch.setenv("GITHUB_WORKSPACE", "/repo")

    render_github({"Images": [issue("error", "100% wrong\nsecond line")]})

    line = annotations(capsys)[0]
    assert line.endswith("::100%25 wrong%0Asecond line")
    assert "\n" not in line


def test_comma_and_colon_escaped_in_a_property(capsys, monkeypatch):
    """An unescaped comma would split the property list and lose the line number."""
    monkeypatch.setenv("GITHUB_WORKSPACE", "/repo")

    render_github({"Images": [issue("error", "boom", path="/repo/16x9/Home,v2:old.xml")]})

    assert "file=16x9/Home%2Cv2%3Aold.xml," in annotations(capsys)[0]


def test_issue_without_a_line_omits_the_property(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_WORKSPACE", "/repo")

    render_github({"File Integrity": [issue("error", "boom", line=0)]})

    line = annotations(capsys)[0]
    assert "line=" not in line
    assert "title=File Integrity" in line


def test_no_issues_prints_nothing(capsys):
    render_github({})

    assert annotations(capsys) == []
