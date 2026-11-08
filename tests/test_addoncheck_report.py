"""The add-on rule registry, report, compare and command line (kdk-only)."""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from addons import AddonCase, clean_files
from kdk.addoncheck import __version__
from kdk.addoncheck.report import render_json
from kdk.addoncheck.rules import ADDON_CHECKER, PREFIXES, RULES
from kdk.output.compare import compare, mismatch
from kdk.output.payload import render_rules

SRC = Path(__file__).resolve().parent.parent / "src"
PACKAGE = SRC / "kdk" / "addoncheck"


def emitted_ids() -> set[str]:
    """Rule ids the package's checks write, read from its source."""
    found = set()
    for path in PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r'finding\(\s*"([a-z]+\.[a-z0-9-]+)"', text))
        found |= set(re.findall(r'"repo\.[a-z-]+": "([a-z]+\.[a-z0-9-]+)"', text))
        found |= {f"art.no-{kind}" for kind in ("icon", "fanart") if 'f"art.no-{kind}"' in text}
    return found


class TestRegistry(unittest.TestCase):
    """Registered ids against the ones the checks emit."""

    def test_every_emitted_id_is_registered(self):
        """No check writes an id the registry lacks."""
        self.assertEqual(emitted_ids() - set(RULES), set())

    def test_every_registered_id_is_emitted(self):
        """No registered id is dead."""
        self.assertEqual(set(RULES) - emitted_ids(), set())

    def test_prefixes_and_levels(self):
        """Every id has a known prefix, and every checker level is a registered id."""
        self.assertTrue(all(rule.split(".")[0] in PREFIXES for rule in RULES))
        self.assertEqual(set(ADDON_CHECKER) - set(RULES), set())

    def test_rules_json_keeps_the_skin_list(self):
        """`kdk rules --json` adds addon_rules beside the unchanged skin rules."""
        payload = render_rules()
        self.assertTrue(all("severity" not in row for row in payload["rules"]))
        self.assertEqual({row["id"] for row in payload["addon_rules"]}, set(RULES))
        self.assertTrue(all(row["severity"] in ("error", "warning", "hint") for row in payload["addon_rules"]))


class TestReport(AddonCase):
    """The JSON payload and comparing two add-on runs."""

    def payload(self, files: dict) -> dict:
        """JSON payload of a run on the files."""
        result = self.run_check(files)
        return render_json(result, result["issues"])

    def test_payload_shape(self):
        """Add-on metadata, versions, totals and relative paths."""
        payload = self.payload({**clean_files(), "resources/bad.json": "{"})
        for key, value in (("domain", "addon"), ("addon_id", "script.test"), ("addon_version", "1.0.0"),
                           ("provider_name", "Someone"), ("addoncheck_version", __version__),
                           ("kodi_release", "omega"), ("errors", 1), ("hints", 1)):
            self.assertEqual(payload[key], value, key)
        self.assertEqual(payload["categories"]["Files"][0]["file"], "resources/bad.json")

    def test_compare_two_runs(self):
        """A fixed and a new finding between two add-on runs, with the add-on metadata on top."""
        base = self.payload({**clean_files(), "resources/bad.json": "{"})
        self.tmp_reset()
        head = self.payload({**clean_files(), "resources/bad.xml": "<a>"})
        self.assertIsNone(mismatch(base, head))
        result = compare(base, head)
        self.assertEqual((result["new"], result["fixed"], result["addon_id"]), (1, 1, "script.test"))
        self.assertIn("hints", result["head"])

    def test_compare_refuses_a_skin_run(self):
        """An add-on run and a skin run cannot be compared."""
        head = self.payload(clean_files())
        skin = {k: v for k, v in head.items() if k not in ("domain", "addoncheck_version")}
        self.assertIn("kinds of run", mismatch(skin, head) or "")

    def tmp_reset(self):
        """Empty the add-on folder so the next run starts from nothing."""
        import shutil

        shutil.rmtree(os.path.join(self.tmp, "script.test"), ignore_errors=True)


class TestCommandLine(AddonCase):
    """Exit codes and output of `kdk addon`."""

    def kdk(self, *args) -> subprocess.CompletedProcess:
        """Run kdk in a subprocess; returns the finished process."""
        env = dict(os.environ, PYTHONPATH=str(SRC))
        return subprocess.run([sys.executable, "-m", "kdk", *args], capture_output=True, text=True, env=env,
                              check=False)

    def test_exit_codes(self):
        """Errors exit 1, --exit-zero 0, hints alone 0, a bad release 2."""
        dirty = self.make({**clean_files(), "resources/bad.json": "{"}, "script.test")
        self.assertEqual(self.kdk("addon", "validate", dirty, "--release", "omega").returncode, 1)
        self.assertEqual(self.kdk("addon", "validate", dirty, "--release", "omega", "--exit-zero").returncode, 0)
        os.remove(os.path.join(dirty, "resources", "bad.json"))
        self.assertEqual(self.kdk("addon", "validate", dirty, "--release", "omega", "--strict").returncode, 0)
        self.assertEqual(self.kdk("addon", "validate", dirty, "--release", "leia").returncode, 2)

    def test_json_to_file(self):
        """With --json and -o the payload goes to the file and stdout stays empty."""
        path = self.make(clean_files())
        out = os.path.join(self.tmp, "run.json")
        proc = self.kdk("addon", "validate", path, "--release", "piers", "--json", "--isolated", "-o", out)
        self.assertEqual(proc.stdout, "")
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["domain"], "addon")

    def test_compare_saved_runs(self):
        """`kdk compare` takes two saved add-on runs and exits 1 on a new error."""
        path = self.make(clean_files())
        base, head = os.path.join(self.tmp, "base.json"), os.path.join(self.tmp, "head.json")
        self.kdk("addon", "validate", path, "--release", "omega", "--json", "-o", base)
        with open(os.path.join(path, "resources", "bad.json"), "w", encoding="utf-8") as f:
            f.write("{")
        self.kdk("addon", "validate", path, "--release", "omega", "--json", "-o", head)
        proc = self.kdk("compare", base, head, "--json")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["new"], 1)


if __name__ == "__main__":
    unittest.main()
