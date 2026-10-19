"""Tests for the factory itself (not for lunchbox). Run: python3 -m unittest discover -s factory/tests -v

Each test clones the repo into a temp dir and drives the real orchestrator with the `replay` agent and
synthetic recordings, so the control flow (fix loop, review loop, escalation) is checked without any
model calls. Factories are software too: test them, version them, review changes to them.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = "## Summary\nSelf-test.\n\n## Acceptance criteria\n1. `lunchbox.selftest.answer()` returns 42.\n\n## Risk\nlow: test only\n"
CODE = "def answer():\n    return {value}\n"
TEST = "import unittest\nfrom lunchbox.selftest import answer\n\n\nclass SelfTest(unittest.TestCase):\n    def test_answer(self):\n        self.assertEqual(answer(), 42)\n"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class FactoryFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        git("clone", "-q", str(ROOT), str(self.repo), cwd=ROOT)
        git("config", "user.email", "test@example.com", cwd=self.repo)
        git("config", "user.name", "factory test", cwd=self.repo)
        (self.repo / "work").mkdir(exist_ok=True)
        (self.repo / "work" / "999-selftest.md").write_text("# Self-test\n\nAdd `answer()` returning 42.\n")
        self.replays = self.repo / "factory" / "replays" / "999-selftest"
        self.replays.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def patch_for(self, value: int) -> str:
        """A cumulative patch (base → change) that adds selftest.py returning `value`, plus its test."""
        scratch = Path(self.tmp.name) / f"scratch-{value}"
        git("clone", "-q", str(self.repo), str(scratch), cwd=self.repo)
        (scratch / "lunchbox" / "selftest.py").write_text(CODE.format(value=value))
        (scratch / "tests" / "test_selftest.py").write_text(TEST)
        git("add", "-A", cwd=scratch)
        return git("diff", "--cached", cwd=scratch)

    def rec(self, key: str, text: str, patch: str | None = None):
        (self.replays / f"{key}.json").write_text(json.dumps({"agent": "test", "seconds": 0, "text": text}))
        if patch is not None:
            (self.replays / f"{key}.patch").write_text(patch)

    def run_factory(self) -> dict:
        env = dict(os.environ, FACTORY_REPLAY_SPEED="1000000", NO_COLOR="1")
        p = subprocess.run([sys.executable, "factory/run.py", "run", "work/999-selftest.md", "--agent", "replay"],
                           cwd=self.repo, capture_output=True, text=True, env=env, timeout=120)
        ledger = (self.repo / ".factory" / "runs.jsonl").read_text().splitlines()
        self.output = p.stdout + p.stderr
        return json.loads(ledger[-1])

    def test_happy_path_is_ready(self):
        self.rec("spec-1", SPEC)
        self.rec("build-1", "built", self.patch_for(42))
        self.rec("review-1", json.dumps({"verdict": "approve", "criteria": [{"id": 1, "met": True}], "findings": []}))
        row = self.run_factory()
        self.assertEqual(row["outcome"], "ready", self.output)
        self.assertEqual((row["fix_rounds"], row["review_rounds"]), (0, 0))

    def test_gate_failure_is_fixed_then_review_changes_are_revised(self):
        self.rec("spec-1", SPEC)
        self.rec("build-1", "built", self.patch_for(41))          # test fails → gate fails
        self.rec("fix-1", "fixed", self.patch_for(42))            # fix round 1 → gates pass
        self.rec("review-1", "Here you go: " + json.dumps({"verdict": "changes", "findings": [
            {"severity": "medium", "file": "lunchbox/selftest.py", "issue": "no docstring", "suggestion": "add one"}]}))
        self.rec("revise-1", "revised", self.patch_for(42))
        self.rec("review-2", json.dumps({"verdict": "approve", "criteria": [{"id": 1, "met": True}], "findings": []}))
        row = self.run_factory()
        self.assertEqual(row["outcome"], "ready", self.output)
        self.assertEqual((row["fix_rounds"], row["review_rounds"]), (1, 1))

    def test_gates_that_never_pass_escalate_to_a_human(self):
        self.rec("spec-1", SPEC)
        self.rec("build-1", "built", self.patch_for(1))
        self.rec("fix-1", "tried", self.patch_for(2))
        self.rec("fix-2", "tried again", self.patch_for(3))
        row = self.run_factory()
        self.assertEqual(row["outcome"], "needs-human", self.output)
        self.assertEqual(row["fix_rounds"], 2)
        self.assertIn("gates still failing", row["reason"])

    def test_deleting_an_existing_test_trips_the_tests_kept_sensor(self):
        scratch = Path(self.tmp.name) / "scratch-del"
        git("clone", "-q", str(self.repo), str(scratch), cwd=self.repo)
        (scratch / "tests" / "test_cli.py").unlink()
        (scratch / "lunchbox" / "selftest.py").write_text(CODE.format(value=42))
        git("add", "-A", cwd=scratch)
        cheat = git("diff", "--cached", cwd=scratch)
        self.rec("spec-1", SPEC)
        self.rec("build-1", "built", cheat)
        self.rec("fix-1", "tried", cheat)
        self.rec("fix-2", "tried", cheat)
        row = self.run_factory()
        self.assertEqual(row["outcome"], "needs-human", self.output)
        self.assertIn("removed tests", self.output + "".join(
            p.read_text() for p in (self.repo / ".factory" / "runs").rglob("gates-*.log")))

    def test_unparseable_review_is_not_treated_as_approval(self):
        self.rec("spec-1", SPEC)
        self.rec("build-1", "built", self.patch_for(42))
        self.rec("review-1", "looks good to me!")
        self.rec("revise-1", "revised", self.patch_for(42))
        self.rec("review-2", "still not json")
        row = self.run_factory()
        self.assertEqual(row["outcome"], "needs-human", self.output)


if __name__ == "__main__":
    unittest.main()
