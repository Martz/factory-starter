"""Work ingress: every trigger puts a ticket in the inbox, and `run.py next` works through it, oldest first.

All triggers end in the same inbox, so the line never cares where the work came from:

  you          run.py ticket "Title" --body "..."           or  run.py ticket --from work/004-split-evenly.md
  a payload    run.py ticket --payload examples/webhooks/jira-issue-created.json   (simulate a Jira ticket)
  a webhook    run.py serve [--run], then POST Jira, Linear or GitHub issue webhooks to http://localhost:8765/webhook
  a tracker    orca jira search "<JQL>" --json | run.py ticket --payload -      (any CLI that prints issues as JSON)
  a schedule   run.py next --check exits 0 only when work is waiting: an Orca automation precheck or a cron guard

Ticket text is untrusted input. A payload is only accepted when it carries the `[ingress] label` from
factory.toml ("factory" by default): who may apply that label is your first line of defence. Tickets are
de-duplicated by key, because trackers send the same issue more than once (created, then updated).
Standard library only.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@dataclass
class Ticket:
    title: str
    body: str = ""
    key: str = ""
    source: str = "manual"
    url: str = ""
    labels: list[str] = field(default_factory=list)
    stem: str = ""          # set when the ticket mirrors a work/*.md item, so its recorded replay still applies


def slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].strip("-")


def adf_text(node) -> str:
    """Flatten Atlassian Document Format (Jira Cloud's rich-text JSON) to plain text."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    kind, inner = node.get("type"), adf_text(node.get("content", []))
    if kind == "text":
        code = any(m.get("type") == "code" for m in node.get("marks", []))
        return f"`{node.get('text', '')}`" if code else node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    if kind == "listItem":
        return "- " + inner.strip() + "\n"
    if kind == "codeBlock":
        return "```\n" + inner + "\n```\n\n"
    if kind in ("paragraph", "heading", "bulletList", "orderedList"):
        return inner.rstrip("\n") + "\n\n"
    return inner


def label_names(labels) -> list[str]:
    return [n for n in ((x.get("name", "") if isinstance(x, dict) else str(x)) for x in labels or []) if n]


def parse(payload) -> tuple[list[Ticket], str]:
    """Turn a webhook body or a tracker CLI's JSON into tickets. Returns (tickets, why-not note)."""
    if isinstance(payload, dict) and "result" in payload and "ok" in payload:      # orca … --json envelope
        payload = payload["result"]
    if isinstance(payload, dict) and isinstance(payload.get("issues"), list):      # {"issues": [...]}
        payload = payload["issues"]
    if isinstance(payload, list):
        tickets = [t for item in payload for t in parse(item)[0]]
        return tickets, "" if tickets else "no issues in the list"
    if not isinstance(payload, dict):
        return [], "not a JSON object"

    if "webhookEvent" in payload and isinstance(payload.get("issue"), dict):        # Jira Cloud webhook
        if payload["webhookEvent"] not in ("jira:issue_created", "jira:issue_updated"):
            return [], f"ignored Jira event {payload['webhookEvent']}"
        issue, fields = payload["issue"], payload["issue"].get("fields", {})
        site = re.sub(r"/rest/api/.*$", "", issue.get("self", ""))
        return [Ticket(fields.get("summary", ""), adf_text(fields.get("description") or ""), issue.get("key", ""), "jira",
                       f"{site}/browse/{issue.get('key')}" if site else "", label_names(fields.get("labels")))], ""

    if payload.get("type") == "Issue" and isinstance(payload.get("data"), dict):   # Linear webhook
        if payload.get("action") not in ("create", "update"):
            return [], f"ignored Linear action {payload.get('action')}"
        d = payload["data"]
        return [Ticket(d.get("title", ""), d.get("description") or "", d.get("identifier", ""), "linear",
                       d.get("url", ""), label_names(d.get("labels")))], ""

    issue = payload.get("issue")
    if "action" in payload and isinstance(issue, dict) and "number" in issue:      # GitHub issues webhook
        if payload["action"] not in ("opened", "labeled", "reopened"):
            return [], f"ignored GitHub action {payload['action']}"
        repo = (payload.get("repository") or {}).get("name", "issue")
        return [Ticket(issue.get("title", ""), issue.get("body") or "", f"{repo}-{issue['number']}", "github",
                       issue.get("html_url", ""), label_names(issue.get("labels")))], ""

    title = payload.get("title") or payload.get("summary")                         # any tracker CLI or script
    if title:
        key = payload.get("key") or payload.get("identifier") or payload.get("number") or ""
        return [Ticket(title, adf_text(payload.get("description") or payload.get("body") or ""), str(key),
                       payload.get("source") or "api", payload.get("url") or "", label_names(payload.get("labels")))], ""
    return [], "unrecognised payload: expected a Jira, Linear or GitHub issue webhook, or {title, body}"


def front_matter(text: str) -> tuple[dict, str]:
    """Split `---` key: value front matter from a work item."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip() for k, v in meta.items()}, text[m.end():]


class Inbox:
    """A folder queue: inbox/*.md (waiting) → processing/ → done/ or failed/. Oldest first, by file name."""

    def __init__(self, state: Path):
        self.dir = state / "inbox"
        self.lock = threading.Lock()

    def pending(self) -> list[Path]:
        return sorted(self.dir.glob("*.md")) if self.dir.exists() else []

    def seen(self, key: str) -> bool:
        tag = f"--{slug(key)}--"
        return bool(key) and self.dir.exists() and any(tag in p.name for p in self.dir.rglob("*.md"))

    def add(self, t: Ticket, label: str = "", require_label: bool = True) -> tuple[Path | None, str]:
        who = t.key or t.title[:40]
        if not t.title.strip():
            return None, "ignored: ticket has no title"
        if require_label and label and label.lower() not in (x.lower() for x in t.labels):
            return None, f"ignored {who}: no '{label}' label"
        with self.lock:
            if t.key and self.seen(t.key):
                return None, f"ignored {who}: already in the inbox or done"
            self.dir.mkdir(parents=True, exist_ok=True)
            now = dt.datetime.now()
            path = self.dir / f"{now:%Y%m%d-%H%M%S-%f}--{slug(t.key) or 'ticket'}--{slug(t.title, 30)}.md"
            meta = {"source": t.source, "key": t.key, "url": t.url, "labels": ", ".join(t.labels),
                    "received": now.isoformat(timespec="seconds"), "stem": t.stem or slug(f"{t.key} {t.title}", 40)}
            head = "\n".join(f"{k}: {v}" for k, v in meta.items() if v)
            path.write_text(f"---\n{head}\n---\n# {t.title.strip()}\n\n{t.body.strip()}\n")
        return path, f"queued {who} from {t.source}"

    def claim(self, path: Path) -> Path:
        (self.dir / "processing").mkdir(parents=True, exist_ok=True)
        return path.rename(self.dir / "processing" / path.name)

    def settle(self, path: Path, ok: bool, notes: dict) -> Path:
        dest = self.dir / ("done" if ok else "failed")
        dest.mkdir(parents=True, exist_ok=True)
        meta, body = front_matter(path.read_text())
        meta.update({k: v for k, v in notes.items() if v})
        path.write_text("---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\n" + body)
        return path.rename(dest / path.name)


def serve(inbox: Inbox, label: str, host: str, port: int, token: str = "", on_queued=None, log=print):
    """A minimal webhook receiver: POST /webhook with a Jira, Linear or GitHub issue payload (or {title, body})."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(200, {"factory": "ok", "waiting": [p.name for p in inbox.pending()]})

        def do_POST(self):
            path, _, query = self.path.partition("?")
            if path.rstrip("/") not in ("", "/webhook"):
                return self._send(404, {"error": "POST to /webhook"})
            given = self.headers.get("X-Factory-Token") or dict(q.split("=", 1) for q in query.split("&") if "=" in q).get("token", "")
            if token and not hmac.compare_digest(given, token):
                return self._send(401, {"error": "missing or wrong token"})
            size = int(self.headers.get("Content-Length") or 0)
            if size > 1_000_000:
                return self._send(413, {"error": "payload too large"})
            try:
                payload = json.loads(self.rfile.read(size) or b"null")
            except json.JSONDecodeError:
                return self._send(400, {"error": "body is not JSON"})
            tickets, note = parse(payload)
            results = [inbox.add(t, label) for t in tickets]
            queued = [p.name for p, _ in results if p]
            for msg in [m for _, m in results] or [note]:
                log(f"   webhook: {msg}")
            if queued and on_queued:
                on_queued()
            self._send(202 if queued else 200, {"queued": queued, "notes": [m for _, m in results] or [note]})

        def log_message(self, *_):     # keep the terminal for the factory's own output
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
