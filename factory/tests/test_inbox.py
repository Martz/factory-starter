"""Tests for work ingress (factory/inbox.py and run.py ticket | next | serve). No model calls.

Run: python3 -m unittest discover -s factory/tests -v
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
import inbox  # noqa: E402

EXAMPLES = ROOT / "examples" / "webhooks"


def load(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text())


class ParseTest(unittest.TestCase):
    def test_jira_webhook_with_rich_text(self):
        (t,), _ = inbox.parse(load("jira-issue-created"))
        self.assertEqual((t.key, t.source, t.title), ("LUNCH-4", "jira", "Split the bill evenly"))
        self.assertEqual(t.url, "https://your-team.atlassian.net/browse/LUNCH-4")
        self.assertIn("`Order.split_evenly()`", t.body)          # ADF code marks survive as Markdown
        self.assertIn("factory", t.labels)

    def test_linear_and_github_webhooks(self):
        (lin,), _ = inbox.parse(load("linear-issue-created"))
        (gh,), _ = inbox.parse(load("github-issue-labeled"))
        self.assertEqual((lin.key, lin.source), ("LUN-2", "linear"))
        self.assertEqual((gh.key, gh.source), ("factory-starter-3", "github"))

    def test_tracker_cli_list_and_ignored_events(self):
        tickets, _ = inbox.parse({"ok": True, "result": [{"key": "KAN-1", "title": "a", "labels": ["factory"]},
                                                         {"key": "KAN-2", "title": "b"}]})
        self.assertEqual([t.key for t in tickets], ["KAN-1", "KAN-2"])
        self.assertEqual(inbox.parse({"webhookEvent": "jira:issue_deleted", "issue": {}})[0], [])
        self.assertEqual(inbox.parse({"action": "closed", "issue": {"number": 1}})[0], [])
        self.assertEqual(inbox.parse({"nothing": "here"})[0], [])


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.box = inbox.Inbox(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_label_guard_and_dedupe(self):
        (jira,), _ = inbox.parse(load("jira-issue-created"))
        (unlabelled,), _ = inbox.parse(load("jira-issue-no-label"))
        self.assertIsNotNone(self.box.add(jira, "factory")[0])
        self.assertIsNone(self.box.add(jira, "factory")[0])                 # same key again: ignored
        self.assertIsNone(self.box.add(unlabelled, "factory")[0])           # no label: ignored
        self.assertIsNotNone(self.box.add(unlabelled, "factory", require_label=False)[0])   # queued by a human
        self.assertEqual(len(self.box.pending()), 2)

    def test_claim_and_settle_keep_the_record(self):
        path, _ = self.box.add(inbox.Ticket("Do a thing", "details", "T-1"), "")
        done = self.box.settle(self.box.claim(path), True, {"run": "r1", "outcome": "ready"})
        meta, body = inbox.front_matter(done.read_text())
        self.assertEqual((done.parent.name, meta["key"], meta["run"], meta["outcome"]), ("done", "T-1", "r1", "ready"))
        self.assertIn("# Do a thing", body)
        self.assertEqual(self.box.pending(), [])


class CommandsTest(unittest.TestCase):
    """Drive run.py in a throwaway clone (with the factory code on disk), using recorded replays."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        subprocess.run(["git", "clone", "-q", str(ROOT), str(self.repo)], check=True)
        for d in ("factory", "examples"):
            shutil.copytree(ROOT / d, self.repo / d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        self.env = dict(os.environ, NO_COLOR="1", FACTORY_REPLAY_SPEED="1000000")
        self.env.pop("FACTORY_WEBHOOK_TOKEN", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, *args, stdin=None):
        return subprocess.run([sys.executable, "factory/run.py", *args], cwd=self.repo, env=self.env, input=stdin,
                              capture_output=True, text=True, timeout=120)

    def test_ticket_then_next_runs_the_line_and_files_the_ticket(self):
        self.assertEqual(self.run_py("next", "--check").returncode, 1)
        self.run_py("ticket", "--from", "work/004-split-evenly.md")
        self.run_py("ticket", "--payload", "-", stdin=(EXAMPLES / "jira-issue-no-label.json").read_text())
        self.assertEqual(self.run_py("next", "--check").returncode, 0)
        p = self.run_py("next", "--agent", "replay")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        done = list((self.repo / ".factory" / "inbox" / "done").glob("*.md"))
        self.assertEqual(len(done), 1)
        self.assertIn("outcome: ready", done[0].read_text())
        self.assertEqual(self.run_py("next", "--check").returncode, 1)     # the unlabelled ticket never got in

    def test_serve_queues_labelled_webhooks_and_requires_its_token(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = dict(self.env, FACTORY_WEBHOOK_TOKEN="t0ken")
        srv = subprocess.Popen([sys.executable, "factory/run.py", "serve", "--port", str(port)], cwd=self.repo, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            url = f"http://127.0.0.1:{port}/webhook"
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)

            def post(name, token):
                req = urllib.request.Request(url, data=(EXAMPLES / f"{name}.json").read_bytes(), headers={"X-Factory-Token": token})
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, {}

            self.assertEqual(post("jira-issue-created", "wrong")[0], 401)
            status, body = post("jira-issue-created", "t0ken")
            self.assertEqual((status, len(body["queued"])), (202, 1))
            self.assertEqual(post("jira-issue-no-label", "t0ken")[1]["queued"], [])
        finally:
            srv.terminate()
            srv.wait(timeout=10)
        self.assertEqual(len(list((self.repo / ".factory" / "inbox").glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
