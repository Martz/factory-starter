#!/usr/bin/env python3
"""A minimal software factory: a work item in, a verified and evidenced branch out.

    python3 factory/run.py run work/001-reject-invalid-prices.md   # run the line on one work item
    python3 factory/run.py run --issue 12 --pr                      # GitHub issue in, draft PR out
    python3 factory/run.py report                                   # metrics across runs
    python3 factory/run.py show [--diff | --try CMD]                # inspect the latest run
    python3 factory/run.py learn                                    # improvement loop: propose AGENTS.md rules
    python3 factory/run.py doctor [--deep]                          # preflight checks
    python3 factory/run.py reset                                    # remove factory worktrees and branches

Agents propose, code disposes: agents do the creative stations (spec, build, review), and this
deterministic script owns the control flow, the gates, the evidence and the record.
Standard library only (Python 3.11+), plus git and at least one coding-agent CLI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agents  # noqa: E402

FACTORY = Path(__file__).resolve().parent
ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=FACTORY, capture_output=True, text=True).stdout.strip() or FACTORY.parent)
STATE = ROOT / ".factory"
LEDGER = STATE / "runs.jsonl"

# ---------------------------------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------------------------------
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


DIM, BOLD, GREEN, RED, YELLOW, CYAN, MAGENTA = "2", "1", "32", "31", "33", "36", "35"


def fmt_secs(s: float) -> str:
    return f"{s:.1f}s" if s < 10 else (f"{s:.0f}s" if s < 90 else f"{int(s // 60)}m{int(s % 60):02d}s")


class Station:
    """Prints one line per station, with a live spinner while it runs."""
    n = 0

    def __init__(self, name: str, who: str, number: bool = True):
        if number:
            Station.n += 1
        self.label = f"{Station.n if number else ' '} {name:<9}{who:<9}"
        self.start = time.time()
        self._stop = threading.Event()
        self._t = None
        if COLOR:
            self._t = threading.Thread(target=self._spin, daemon=True)
            self._t.start()

    def _spin(self):
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not self._stop.wait(0.1):
            sys.stdout.write(f"\r {self.label}{c(frames[i % 10], CYAN)} {c(fmt_secs(time.time() - self.start), DIM)}   ")
            sys.stdout.flush()
            i += 1

    def done(self, ok: bool | None, msg: str) -> float:
        self._stop.set()
        if self._t:
            self._t.join()
        secs = time.time() - self.start
        mark = c("✓", GREEN) if ok else (c("✗", RED) if ok is False else c("◆", MAGENTA))
        sys.stdout.write(("\r\033[K" if COLOR else "") + f" {self.label}{mark} {msg}  {c(fmt_secs(secs), DIM)}\n")
        sys.stdout.flush()
        return secs


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------
def sh(cmd: list[str] | str, cwd: Path, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check, timeout=timeout,
                          shell=isinstance(cmd, str))


def load_config() -> dict:
    return tomllib.loads((FACTORY / "factory.toml").read_text())


def prompt(name: str, **kw) -> str:
    return (FACTORY / "prompts" / f"{name}.md").read_text().format(**kw)


def test_names(tree: Path) -> set[str]:
    """test_* functions currently in a working tree."""
    names = set()
    for f in (tree / "tests").glob("test_*.py"):
        names |= {f"{f.stem}.{m}" for m in re.findall(r"^\s*def (test_\w+)", f.read_text(), re.M)}
    return names


def test_names_at(rev: str) -> set[str]:
    """test_* functions at a git revision (the base the factory started from)."""
    # POSIX classes, not \s or \w: git grep -E does not support them everywhere (silently matches nothing).
    out = sh(["git", "grep", "-n", "-E", r"^[[:space:]]*def test_[A-Za-z0-9_]+", rev, "--", "tests/"], ROOT, check=False).stdout
    names = set()
    for line in out.splitlines():
        _, path, _, code = line.split(":", 3)            # <rev>:tests/test_x.py:12:    def test_y(self):
        m = re.search(r"def (test_\w+)", code)
        if m and Path(path).name.startswith("test_"):
            names.add(f"{Path(path).stem}.{m.group(1)}")
    return names


def staged_diff(wt: Path, base: str) -> str:
    sh(["git", "add", "-A"], wt)
    return sh(["git", "diff", "--cached", base], wt).stdout


def diffstat(wt: Path, base: str) -> tuple[int, int, int, list[str]]:
    sh(["git", "add", "-A"], wt)
    rows = [r.split("\t") for r in sh(["git", "diff", "--cached", "--numstat", base], wt).stdout.splitlines() if r]
    ins = sum(int(a) for a, _, _ in rows if a.isdigit())
    dels = sum(int(b) for _, b, _ in rows if b.isdigit())
    return len(rows), ins, dels, [f for _, _, f in rows]


def extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def criteria_count(spec: str) -> int:
    m = re.search(r"##\s*Acceptance criteria\s*\n(.*?)(\n##\s|\Z)", spec, re.S | re.I)
    return len(re.findall(r"^\s*\d+[.)]\s", m.group(1), re.M)) if m else 0


def risk_of(spec: str) -> str:
    m = re.search(r"##\s*Risk\s*\n+\s*`?(low|medium|high)", spec, re.I)
    return m.group(1).lower() if m else "?"


def read_work(args) -> tuple[str, str, str]:
    """Return (stem, title, markdown) from a work-item file or a GitHub issue."""
    if args.issue:
        data = json.loads(sh(["gh", "issue", "view", str(args.issue), "--json", "number,title,body"], ROOT).stdout)
        return f"issue-{data['number']}", data["title"], f"# {data['title']}\n\n{data['body']}\n"
    path = Path(args.work)
    text = path.read_text()
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return path.stem, (m.group(1).strip() if m else path.stem), text


# ---------------------------------------------------------------------------------------------------
# The production line
# ---------------------------------------------------------------------------------------------------
@dataclass
class Run:
    id: str
    stem: str
    title: str
    work: str
    cfg: dict
    agents: dict
    record: bool
    wt: Path = Path()
    dir: Path = Path()
    base: str = ""
    spec: str = ""
    stations: dict = field(default_factory=dict)
    usage: list = field(default_factory=list)
    fix_rounds: int = 0
    review_rounds: int = 0
    gate_log: list = field(default_factory=list)
    review: dict = field(default_factory=dict)
    human_touches: int = 0
    violations: list = field(default_factory=list)
    outcome: str = "running"
    reason: str = ""
    pr: bool = False
    calls: dict = field(default_factory=dict)

    def agent(self, station: str, kind: str, body: str, write: bool) -> agents.AgentResult:
        """Run one agent station inside the worktree, enforce read-only, optionally record it."""
        n = self.calls[kind] = self.calls.get(kind, 0) + 1
        who = self.agents[station]
        call = agents.Call(agent=who, prompt=body, cwd=self.wt, write=write,
                           model=self.cfg.get("models", {}).get(station, ""),
                           timeout=int(self.cfg["limits"].get("agent_timeout", 600)),
                           log=self.dir / f"{kind}-{n}.log",
                           replay_dir=FACTORY / "replays" / self.stem, replay_key=f"{kind}-{n}")
        sh(["git", "add", "-A"], self.wt)   # snapshot: anything unstaged afterwards was written by this call
        result = agents.run(call)
        self.usage.append({"station": kind, "agent": who, "seconds": round(result.seconds, 1), **result.usage})
        if not write:
            touched = sh(["git", "diff", "--name-only"], self.wt).stdout.split() + \
                sh(["git", "ls-files", "--others", "--exclude-standard"], self.wt).stdout.split()
            if touched:
                self.violations.append(f"{kind}-{n}: {who} wrote {', '.join(touched[:3])} in a read-only station (reverted)")
                sh(["git", "checkout", "--", "."], self.wt)
                sh(["git", "clean", "-qfd"], self.wt)
        if self.record and who != "replay":
            agents.record(call, result, staged_diff(self.wt, self.base) if write else None)
        return result

    def gates(self) -> tuple[bool, str]:
        """Computational sensors: run outside the agent, deterministic, fast."""
        out, ok_all, summary = [], True, []
        for name, cmd in self.cfg.get("gates", {}).items():
            if cmd == "builtin" and name == "tests_kept":
                before, after = test_names_at(self.base), test_names(self.wt)
                missing = sorted(before - after)
                ok = not missing and (bool(before) or not after)   # fail closed if the sensor itself sees nothing
                out.append(f"[{name}] {'ok' if ok else 'removed tests: ' + ', '.join(missing)}")
            else:
                cmd = cmd.replace("{python}", shlex.quote(sys.executable))
                p = sh(cmd, self.wt, check=False, timeout=300)
                ok = p.returncode == 0
                out.append(f"[{name}] $ {cmd}\n{(p.stdout + p.stderr).strip()[-3000:]}")
            summary.append((name, ok))
            ok_all &= ok
        self.gate_log.append(summary)
        return ok_all, "\n\n".join(out)

    def test_cmd(self) -> str:
        return self.cfg.get("gates", {}).get("test", "the tests").replace("{python}", "python3")


def cmd_run(args) -> int:
    cfg = load_config()
    if args.checkpoint:
        cfg.setdefault("checkpoints", {})["spec"] = "spec" in args.checkpoint
    roles = dict(cfg["agents"])
    if args.agent:
        roles = {k: args.agent for k in roles}
    if args.reviewer:
        roles["review"] = args.reviewer
    for who in set(roles.values()):
        if not agents.available(who):
            sys.exit(f"agent CLI '{who}' not found on PATH (edit factory/factory.toml or pass --agent)")

    stem, title, work = read_work(args)
    rid = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + re.sub(r"[^a-z0-9]+", "-", stem.lower())[:24].strip("-")
    r = Run(id=rid, stem=stem, title=title, work=work, cfg=cfg, agents=roles, record=args.record, pr=args.pr)
    r.dir = STATE / "runs" / rid
    r.dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    print(f"\n {c('🏭 ' + cfg['factory']['name'], BOLD)}  {c('run ' + rid, DIM)}")
    print(f"    {c('work:', DIM)} {title}  {c('(' + (f'issue #{args.issue}' if args.issue else args.work) + ')', DIM)}")
    print(f"    {c('line:', DIM)} spec={roles['spec']} · build={roles['build']} · review={roles['review']}  "
          f"{c('· gates: ' + ', '.join(cfg.get('gates', {})), DIM)}\n")

    # 1 intake ---------------------------------------------------------------------------------------
    st = Station("intake", "code")
    r.base = sh(["git", "rev-parse", "HEAD"], ROOT).stdout.strip()
    r.wt = STATE / "worktrees" / rid
    sh(["git", "worktree", "add", "-q", "-b", f"factory/{rid}", str(r.wt), r.base], ROOT)
    (r.dir / "work.md").write_text(work)
    r.stations["intake"] = st.done(True, f"worktree + branch factory/{rid} @ {r.base[:7]}")
    return _line(r, args)(started)


def _line(r: Run, args):
    cfg = r.cfg
    limits = cfg["limits"]

    # 2 spec -----------------------------------------------------------------------------------------
    st = Station("spec", r.agents["spec"])
    res = r.agent("spec", "spec", prompt("spec", work=r.work), write=False)
    r.spec = res.text
    (r.dir / "spec.md").write_text(r.spec)
    n_crit = criteria_count(r.spec)
    if not res.ok or n_crit == 0:
        r.stations["spec"] = st.done(False, f"no usable spec ({res.error or 'no acceptance criteria'})")
        return escalate(r, "spec station failed")
    r.stations["spec"] = st.done(True, f"{n_crit} acceptance criteria · risk: {risk_of(r.spec)}")

    if cfg.get("checkpoints", {}).get("spec"):
        st = Station("approve", "human", number=False)
        m = re.search(r"##\s*Acceptance criteria\s*\n(.*?)(\n##\s|\Z)", r.spec, re.S | re.I)
        shown = (m.group(1).strip() if m else r.spec.strip()).splitlines()
        print("\n      " + c("Acceptance criteria (full spec: " + str((r.dir / "spec.md").relative_to(ROOT)) + ")", BOLD))
        print("\n".join("      " + line for line in shown) + "\n")
        answer = input(f"      {c('◆ Approve this spec? [y/N] ', MAGENTA)}").strip().lower()
        r.human_touches += 1
        if answer not in ("y", "yes"):
            r.stations["approve"] = st.done(False, "spec rejected by human")
            r.outcome, r.reason = "rejected", "spec rejected at checkpoint"
            return lambda started: finish(r, started)
        r.stations["approve"] = st.done(None, "spec approved by human")

    # 3 build ----------------------------------------------------------------------------------------
    st = Station("build", r.agents["build"])
    res = r.agent("build", "build", prompt("build", work=r.work, spec=r.spec, test_cmd=r.test_cmd()), write=True)
    (r.dir / "build.md").write_text(res.text)
    files, ins, dels, _ = diffstat(r.wt, r.base)
    if not res.ok or files == 0:
        r.stations["build"] = st.done(False, res.error or "agent made no changes")
        return escalate(r, "build station produced no change")
    r.stations["build"] = st.done(True, f"{files} files changed (+{ins} −{dels})")

    # 4 gates + fix loop, 5 review + revise loop ------------------------------------------------------
    while True:
        if not gate_loop(r, limits):
            return escalate(r, f"gates still failing after {r.fix_rounds} fix rounds")
        st = Station("review", r.agents["review"], number=r.review_rounds == 0)
        res = r.agent("review", "review", prompt("review", spec=r.spec, diff=staged_diff(r.wt, r.base)[:60000]), write=False)
        verdict = extract_json(res.text) or {"verdict": "changes", "findings": [
            {"severity": "high", "file": "-", "issue": "reviewer output was not valid JSON", "suggestion": "check the review log"}],
            "criteria": [], "summary": res.error or "unparseable review"}
        r.review = verdict
        (r.dir / f"review-{r.review_rounds + 1}.json").write_text(json.dumps(verdict, indent=2))
        crit = verdict.get("criteria") or []
        met = sum(1 for x in crit if x.get("met"))
        sev = [f.get("severity", "?") for f in verdict.get("findings") or []]
        sev_txt = ", ".join(f"{sev.count(s)} {s}" for s in ("high", "medium", "low") if sev.count(s)) or "no findings"
        approved = verdict.get("verdict") == "approve"
        r.stations[f"review{r.review_rounds + 1}"] = st.done(
            approved, f"{'APPROVE' if approved else 'CHANGES'} · {met}/{len(crit)} criteria met · {sev_txt}")
        if approved:
            break
        if r.review_rounds >= int(limits.get("review_rounds", 1)):
            return escalate(r, "reviewer still requests changes")
        r.review_rounds += 1
        st = Station("revise", r.agents["build"], number=False)
        findings = json.dumps(verdict.get("findings", []), indent=1)
        res = r.agent("build", "revise", prompt("revise", spec=r.spec, findings=findings, test_cmd=r.test_cmd()), write=True)
        r.stations[f"revise{r.review_rounds}"] = st.done(res.ok, "addressed review findings" if res.ok else res.error)

    r.outcome, r.reason = "ready", "gates green and independent review approved"
    return lambda started: finish(r, started)


def gate_loop(r: Run, limits: dict) -> bool:
    while True:
        st = Station("gates", "code", number=r.fix_rounds == 0 and not r.gate_log)
        ok, out = r.gates()
        (r.dir / f"gates-{len(r.gate_log)}.log").write_text(out)
        marks = " ".join(f"{n} {c('✓', GREEN) if g else c('✗', RED)}" for n, g in r.gate_log[-1])
        if ok:
            r.stations[f"gates{len(r.gate_log)}"] = st.done(True, marks)
            return True
        if r.fix_rounds >= int(limits.get("fix_rounds", 2)):
            r.stations[f"gates{len(r.gate_log)}"] = st.done(False, marks + " → escalate to human")
            return False
        r.fix_rounds += 1
        r.stations[f"gates{len(r.gate_log)}"] = st.done(False, marks + f" → fix round {r.fix_rounds}/{limits.get('fix_rounds', 2)}")
        st = Station("fix", r.agents["build"], number=False)
        res = r.agent("build", "fix", prompt("fix", spec=r.spec, gate_output=out[-6000:], test_cmd=r.test_cmd()), write=True)
        r.stations[f"fix{r.fix_rounds}"] = st.done(res.ok, "fix applied" if res.ok else res.error)


def escalate(r: Run, reason: str):
    r.outcome, r.reason = "needs-human", reason
    return lambda started: finish(r, started)


def finish(r: Run, started: float) -> int:
    # 6 evidence -------------------------------------------------------------------------------------
    st = Station("evidence", "code")
    files, ins, dels, names = diffstat(r.wt, r.base) if r.wt.exists() else (0, 0, 0, [])
    evidence = write_evidence(r, files, ins, dels, names, time.time() - started)
    r.stations["evidence"] = st.done(True, str(evidence.relative_to(ROOT)))

    # 7 ship -----------------------------------------------------------------------------------------
    st = Station("ship", "code")
    shipped = ""
    if files and r.outcome in ("ready", "needs-human"):
        sh(["git", "add", "-A"], r.wt)
        sh(["git", "commit", "-q", "-m", f"factory: {r.title}", "-m", f"{r.reason}.\n\nFactory-Run: {r.id}"], r.wt)
        shipped = f"factory/{r.id}"
        if getattr(r, "pr", False):
            sh(["git", "push", "-q", "-u", "origin", shipped], r.wt)
            draft = [] if r.outcome == "ready" else ["--draft"]
            url = sh(["gh", "pr", "create", "--head", shipped, "--title", f"factory: {r.title}",
                      "--body-file", str(evidence), *draft], r.wt).stdout.strip()
            shipped = url
    if r.outcome == "ready":
        r.stations["ship"] = st.done(None, f"{shipped} committed → human review & merge")
    elif shipped:
        r.stations["ship"] = st.done(False, f"{shipped} committed, NEEDS HUMAN: {r.reason}")
    else:
        r.stations["ship"] = st.done(False, f"nothing shipped: {r.reason}")

    # 8 record ---------------------------------------------------------------------------------------
    st = Station("record", "code")
    total = time.time() - started
    row = {"id": r.id, "work": r.stem, "title": r.title, "finished": dt.datetime.now().isoformat(timespec="seconds"),
           "base": r.base, "branch": f"factory/{r.id}" if shipped else None,
           "outcome": r.outcome, "reason": r.reason, "seconds": round(total, 1), "agents": r.agents,
           "fix_rounds": r.fix_rounds, "review_rounds": r.review_rounds,
           "review_verdict": r.review.get("verdict"), "findings": len(r.review.get("findings") or []),
           "criteria": criteria_count(r.spec), "human_touches": r.human_touches, "violations": r.violations,
           "files": files, "insertions": ins, "deletions": dels,
           "stations": {k: round(v, 1) for k, v in r.stations.items()}, "usage": r.usage}
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")
    (r.dir / "run.json").write_text(json.dumps(row, indent=2))
    pr = sum(u.get("premium_requests") or 0 for u in r.usage)
    tok = sum((u.get("tokens") or 0) + (u.get("tokens_in") or 0) + (u.get("tokens_out") or 0) for u in r.usage)
    cost = sum(u.get("cost_usd") or 0 for u in r.usage)
    spend = " · ".join(x for x in (f"{pr:g} premium req" if pr else "", f"{tok:,} tokens" if tok else "", f"${cost:.2f}" if cost else "") if x)
    st.done(True, f".factory/runs.jsonl  ({r.outcome} · fix rounds {r.fix_rounds} · {spend or 'usage n/a'})")

    banner = {"ready": c(" READY FOR HUMAN MERGE ", "30;42"), "needs-human": c(" NEEDS HUMAN ", "30;43"),
              "rejected": c(" REJECTED ", "30;41")}[r.outcome]
    print(f"\n {banner}  {fmt_secs(total)} · evidence: {evidence.relative_to(ROOT)}")
    if r.violations:
        print(c("   ⚠ " + "; ".join(r.violations), YELLOW))
    if shipped and not shipped.startswith("http"):
        print(c(f"   inspect: git -C {ROOT} diff {r.base[:7]}..{shipped}", DIM))
    print()
    return 0 if r.outcome == "ready" else 3


def write_evidence(r: Run, files: int, ins: int, dels: int, names: list[str], secs: float) -> Path:
    v = r.review
    crit_rows = "\n".join(f"| {x.get('id')} | {'✅' if x.get('met') else '❌'} | {x.get('evidence', '')} |" for x in v.get("criteria") or [])
    find_rows = "\n".join(f"- **{f.get('severity')}** `{f.get('file')}`: {f.get('issue')} → {f.get('suggestion')}" for f in v.get("findings") or []) or "- none"
    gate_rows = "\n".join(f"| {i + 1} | " + " · ".join(f"{n} {'✅' if ok else '❌'}" for n, ok in round_) + " |" for i, round_ in enumerate(r.gate_log))
    usage_rows = "\n".join(f"| {u['station']} | {u['agent']} | {u['seconds']}s | " +
                           ", ".join(f"{k}={u[k]}" for k in u if k not in ("station", "agent", "seconds") and u[k] not in (None, "")) + " |"
                           for u in r.usage)
    status = {"ready": "✅ Ready for human review and merge", "needs-human": f"⚠️ Needs human: {r.reason}",
              "rejected": f"⛔ Rejected: {r.reason}"}[r.outcome]
    md = f"""# Factory evidence: {r.title}

**{status}**. Run `{r.id}` · {fmt_secs(secs)} · spec={r.agents['spec']} · build={r.agents['build']} · review={r.agents['review']}

## Spec (written by the spec station)
{r.spec.strip() or '_none_'}

## Gates (computational sensors, run by the factory)
| round | result |
|---|---|
{gate_rows or '| - | not reached |'}

Fix rounds used: {r.fix_rounds} of {r.cfg['limits'].get('fix_rounds', 2)}.

## Independent review ({r.agents['review']}, fresh context): **{(v.get('verdict') or 'not reached').upper()}**
{v.get('summary', '')}

| criterion | met | evidence |
|---|---|---|
{crit_rows or '| - | - | - |'}

Findings:
{find_rows}

## Change
{files} files changed, +{ins} −{dels}: {', '.join(f'`{n}`' for n in names) or 'none'}

## Run record
| station | agent | time | usage |
|---|---|---|---|
{usage_rows}

Human touches before merge: {r.human_touches}. Read-only violations: {', '.join(r.violations) or 'none'}.

_Generated by `factory/run.py`. A human reviews and merges; the factory never merges._
"""
    path = r.dir / "evidence.md"
    path.write_text(md)
    return path


# ---------------------------------------------------------------------------------------------------
# Other commands
# ---------------------------------------------------------------------------------------------------
def cmd_report(args) -> int:
    every = [json.loads(line) for line in LEDGER.read_text().splitlines()] if LEDGER.exists() else []
    rows = [x for x in every if set(x["agents"].values()) != {"replay"}]   # replays are rehearsals, not production
    if not rows:
        print("no (non-replay) runs yet: python3 factory/run.py run work/001-reject-invalid-prices.md")
        return 0
    n = len(rows)
    ready = [x for x in rows if x["outcome"] == "ready"]
    autonomous = [x for x in ready if x.get("human_touches", 0) == 0]
    first_pass = [x for x in rows if x.get("review_rounds", 0) == 0 and x.get("review_verdict") == "approve"]
    secs = sorted(x["seconds"] for x in rows)
    pr = sum(u.get("premium_requests") or 0 for x in rows for u in x.get("usage", []))
    print(f"\n {c('Factory report', BOLD)}  {n} runs  ({LEDGER.relative_to(ROOT)})\n")
    print(f"   ready for merge     {len(ready)}/{n}  ({100 * len(ready) // n}%)")
    print(f"   autonomy            {len(autonomous)}/{n}  ({100 * len(autonomous) // n}%)  ready with zero human touches")
    print(f"   first-pass review   {len(first_pass)}/{n}  approved without a revise round")
    print(f"   avg fix rounds      {sum(x.get('fix_rounds', 0) for x in rows) / n:.1f}")
    print(f"   median lead time    {fmt_secs(secs[n // 2])}   (work item → evidenced branch)")
    if pr:
        print(f"   premium requests    {pr:g} total · {pr / max(1, len(ready)):.1f} per ready change")
    print(f"\n   {'run':<42}{'outcome':<13}{'fix':>4}{'rev':>4}{'time':>8}  work")
    for x in rows[-12:]:
        col = GREEN if x["outcome"] == "ready" else YELLOW
        outcome = c(f"{x['outcome']:<13}", col)
        print(f"   {x['id']:<42}{outcome}{x.get('fix_rounds', 0):>4}{x.get('review_rounds', 0):>4}{fmt_secs(x['seconds']):>8}  {x['title'][:40]}")
    print()
    return 0


def cmd_show(args) -> int:
    """Show a run (default: the latest): evidence summary, optionally the diff, or try a command on its branch."""
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines()] if LEDGER.exists() else []
    if args.run:
        rows = [x for x in rows if x["id"].startswith(args.run) or args.run in x["id"]]
    if not rows:
        print("no matching runs")
        return 1
    x = rows[-1]
    d, wt = STATE / "runs" / x["id"], STATE / "worktrees" / x["id"]
    if args.diff:
        if not x.get("base") or not wt.exists():
            print("no worktree/branch for this run")
            return 1
        os.execvp("git", ["git", "-C", str(wt), "-c", "color.ui=always", "--no-pager", "diff", x["base"], "HEAD", "--stat", "-p", "--", "."])
    if args.try_cmd:
        print(c(f"$ (on {x.get('branch')}) {args.try_cmd}", DIM), flush=True)
        return subprocess.run(args.try_cmd, shell=True, cwd=wt).returncode
    col = GREEN if x["outcome"] == "ready" else YELLOW
    print(f"\n {c(x['title'], BOLD)}  {c(x['id'], DIM)}")
    print(f"   outcome   {c(x['outcome'], col)} · {x['reason']}")
    print(f"   line      " + " · ".join(f"{k}={v}" for k, v in x["agents"].items()))
    print(f"   time      {fmt_secs(x['seconds'])}  (" + ", ".join(f"{k} {fmt_secs(v)}" for k, v in x["stations"].items() if v >= 1) + ")")
    print(f"   change    {x['files']} files, +{x['insertions']} −{x['deletions']} on {x.get('branch') or '-'}")
    print(f"   loops     fix rounds {x['fix_rounds']} · review rounds {x['review_rounds']} · human touches {x['human_touches']}")
    reviews = sorted(d.glob("review-*.json"))
    if reviews:
        v = json.loads(reviews[-1].read_text())
        print(f"\n   {c('independent review: ' + str(v.get('verdict', '?')).upper(), BOLD)}  {v.get('summary', '')}")
        for k in v.get("criteria") or []:
            mark = c("✓", GREEN) if k.get("met") else c("✗", RED)
            print(f"     {mark} {k.get('id')}: {str(k.get('evidence', ''))[:110]}")
        for f in v.get("findings") or []:
            print(f"     {c('•', YELLOW)} {f.get('severity')}: {f.get('issue')}")
    print(f"\n   evidence  {(d / 'evidence.md').relative_to(ROOT)}")
    print(f"   spec      {(d / 'spec.md').relative_to(ROOT)}")
    print(c(f"   next      run.py show --diff · run.py show --try \"python3 -m lunchbox friday.csv\"", DIM))
    print()
    return 0


def cmd_learn(args) -> int:
    """The improvement loop: mine recent runs and propose AGENTS.md rules (a human decides)."""
    cfg = load_config()
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines()][-args.last:] if LEDGER.exists() else []
    evidence = []
    for x in rows:
        d = STATE / "runs" / x["id"]
        reviews = [json.loads(p.read_text()) for p in sorted(d.glob("review-*.json"))]
        findings = [f for rv in reviews for f in rv.get("findings") or []]
        fails = [p.read_text()[-1500:] for p in sorted(d.glob("gates-*.log")) if "FAILED" in p.read_text() or "Error" in p.read_text()]
        if findings or fails or x["outcome"] != "ready":
            evidence.append(f"### run {x['id']} ({x['outcome']}: {x['reason']})\nfindings: {json.dumps(findings)}\n"
                            + "".join(f"gate failure:\n{f}\n" for f in fails))
    if not evidence:
        print("nothing to learn from yet: every recent run was clean")
        return 0
    who = args.agent or cfg["agents"].get("learn", "copilot")
    st = Station("learn", who)
    res = agents.run(agents.Call(agent=who, cwd=ROOT, write=False, prompt=prompt(
        "learn", evidence="\n".join(evidence)[-40000:], agents_md=(ROOT / "AGENTS.md").read_text())))
    out = STATE / "proposals" / f"{dt.date.today()}-agents-md.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(res.text)
    st.done(res.ok, str(out.relative_to(ROOT)))
    print("\n" + res.text + "\n")
    print(c("   ◆ Human decision: copy the rules you agree with into AGENTS.md (and add a gate if one is suggested).", MAGENTA))
    return 0


def cmd_doctor(args) -> int:
    cfg = load_config()
    ok = True

    def check(label, good, hint=""):
        nonlocal ok
        ok &= bool(good)
        print(f"   {c('✓', GREEN) if good else c('✗', RED)} {label}" + (f"  {c(hint, DIM)}" if not good and hint else ""))

    print(f"\n {c('Factory doctor', BOLD)}  {ROOT}\n")
    check(f"python {sys.version.split()[0]} (needs 3.11+)", sys.version_info >= (3, 11))
    check("git repository", (ROOT / ".git").exists(), "run inside a git clone")
    dirty = sh(["git", "status", "--porcelain"], ROOT).stdout.strip()
    check("working tree clean (the factory builds from HEAD)", not dirty, "commit your changes first")
    for station, who in cfg["agents"].items():
        check(f"{station:<7} agent '{who}' installed", agents.available(who), f"install {who} or change factory/factory.toml")
    for name, cmd in cfg.get("gates", {}).items():
        if cmd == "builtin":
            continue
        p = sh(cmd.replace("{python}", shlex.quote(sys.executable)), ROOT, check=False, timeout=300)
        check(f"gate '{name}' passes on HEAD", p.returncode == 0, (p.stdout + p.stderr).strip()[-200:])
    if args.deep:
        for who in sorted(set(cfg["agents"].values())):
            if who == "replay" or not agents.available(who):
                continue
            res = agents.run(agents.Call(agent=who, cwd=ROOT, write=False, timeout=120, prompt="Reply with the single word: ready"))
            check(f"agent '{who}' answers headless ({fmt_secs(res.seconds)})", res.ok and "ready" in res.text.lower(), res.error)
    print(f"\n   {'ready to run' if ok else 'fix the items above first'}\n")
    return 0 if ok else 1


def cmd_reset(args) -> int:
    for line in sh(["git", "worktree", "list", "--porcelain"], ROOT).stdout.splitlines():
        if line.startswith("worktree ") and str(STATE / "worktrees") in line:
            sh(["git", "worktree", "remove", "--force", line.split(" ", 1)[1]], ROOT, check=False)
    sh(["git", "worktree", "prune"], ROOT, check=False)
    branches = sh(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/factory/"], ROOT).stdout.split()
    for b in branches:
        sh(["git", "branch", "-q", "-D", b], ROOT, check=False)
    removed = 0
    if args.all and STATE.exists():
        for p in sorted(STATE.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
            removed += 1
    print(f"removed {len(branches)} factory branches" + (f" and {removed} state files" if args.all else " (run history kept; --all clears it)"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="run the line on one work item")
    p.add_argument("work", nargs="?", help="work item markdown file, e.g. work/001-reject-invalid-prices.md")
    p.add_argument("--issue", type=int, help="take the work item from a GitHub issue instead (needs gh)")
    p.add_argument("--agent", choices=agents.ADAPTERS, help="use this agent for every station")
    p.add_argument("--reviewer", choices=agents.ADAPTERS, help="override the review agent")
    p.add_argument("--checkpoint", action="append", choices=["spec"], help="pause for a human at this checkpoint")
    p.add_argument("--pr", action="store_true", help="push the branch and open a PR with the evidence (needs gh)")
    p.add_argument("--record", action="store_true", help="save agent outputs to factory/replays/ for --agent replay")
    sub.add_parser("report", help="metrics across runs")
    p_show = sub.add_parser("show", help="show a run (default: latest): evidence summary, --diff, or --try CMD")
    p_show.add_argument("run", nargs="?", help="run id or part of it")
    p_show.add_argument("--diff", action="store_true", help="show the change")
    p_show.add_argument("--try", dest="try_cmd", metavar="CMD", help="run a command on the run's branch (in its worktree)")
    p_learn = sub.add_parser("learn", help="improvement loop: propose AGENTS.md rules from recent runs")
    p_learn.add_argument("--last", type=int, default=10)
    p_learn.add_argument("--agent", choices=agents.ADAPTERS)
    p_doc = sub.add_parser("doctor", help="preflight checks")
    p_doc.add_argument("--deep", action="store_true", help="also ping each agent CLI")
    p_reset = sub.add_parser("reset", help="remove factory worktrees and branches")
    p_reset.add_argument("--all", action="store_true", help="also delete run history and evidence")
    args = ap.parse_args()
    if args.cmd == "run":
        if not args.work and not args.issue:
            ap.error("run needs a work item file or --issue N")
        STATE.mkdir(exist_ok=True)
    return {"run": cmd_run, "report": cmd_report, "show": cmd_show, "learn": cmd_learn, "doctor": cmd_doctor, "reset": cmd_reset}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
