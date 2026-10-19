"""Agent adapters: one interface over different coding-agent CLIs.

Each station asks for an agent by name. The adapter turns (prompt, read-only or write) into that
CLI's headless invocation and returns the final message plus whatever usage data the CLI reports.
The factory does not trust the agent to respect read-only: it checks `git status` afterwards.

Adapters: copilot (GitHub Copilot CLI), claude (Claude Code), codex (OpenAI Codex CLI), pi, replay.
"replay" re-plays a recorded run (see `run.py run --record`). Use it for offline demos and tests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ADAPTERS = ("copilot", "claude", "codex", "pi", "replay")


@dataclass
class AgentResult:
    text: str
    ok: bool
    seconds: float
    usage: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class Call:
    """Everything an adapter needs for one station call."""
    agent: str
    prompt: str
    cwd: Path
    write: bool
    model: str = ""
    timeout: int = 600
    log: Path | None = None
    replay_dir: Path | None = None   # factory/replays/<work-item>/
    replay_key: str = ""             # e.g. "build-1"


def available(agent: str) -> bool:
    return agent == "replay" or shutil.which(agent) is not None


def run(call: Call) -> AgentResult:
    if call.agent not in ADAPTERS:
        raise ValueError(f"unknown agent {call.agent!r}; choose one of {', '.join(ADAPTERS)}")
    if call.agent == "replay":
        return _replay(call)
    with tempfile.TemporaryDirectory() as tmp:
        argv, stdin, parse = BUILDERS[call.agent](call, Path(tmp))
        start = time.time()
        try:
            p = subprocess.run(argv, cwd=call.cwd, input=stdin, capture_output=True, text=True, timeout=call.timeout)
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") if isinstance(e.stdout, str) else ""
            _log(call, argv, out, "TIMEOUT")
            return AgentResult(text=out, ok=False, seconds=time.time() - start, error=f"timed out after {call.timeout}s")
        secs = time.time() - start
        _log(call, argv, p.stdout, p.stderr)
        text, usage, err = parse(p, Path(tmp))
        ok = p.returncode == 0 and not err
        return AgentResult(text=text.strip(), ok=ok, seconds=secs, usage=usage,
                           error=err or ("" if p.returncode == 0 else (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[-1]))


# --- GitHub Copilot CLI -----------------------------------------------------------------------------
def _copilot(call: Call, tmp: Path):
    usage_file = tmp / "usage.json"
    argv = ["copilot", "-p", call.prompt, "-s", "--no-ask-user", "--no-auto-update",
            "--usage-output-file", str(usage_file), "--allow-all-tools"]
    if call.write:
        argv += ["--deny-tool", "shell(git push)", "--deny-tool", "shell(git commit)", "--deny-tool", "shell(gh:*)"]
    else:
        argv += ["--deny-tool", "write", "--deny-tool", "shell(git commit)", "--deny-tool", "shell(git push)"]
    if call.model:
        argv += ["--model", call.model]

    def parse(p, tmp):
        usage = {}
        if usage_file.exists():
            u = json.loads(usage_file.read_text())
            td = u.get("tokenDetails", {})
            usage = {"premium_requests": u.get("totalPremiumRequestCost"),
                     "tokens_in": sum(td.get(k, {}).get("tokenCount", 0) for k in ("input", "cache_read", "cache_write")),
                     "tokens_out": td.get("output", {}).get("tokenCount", 0),
                     "models": ",".join(u.get("modelMetrics", {}).keys())}
        return p.stdout, usage, ""
    return argv, None, parse


# --- Claude Code -----------------------------------------------------------------------------------
def _claude(call: Call, tmp: Path):
    argv = ["claude", "-p", call.prompt, "--output-format", "json"]
    if call.model:
        argv += ["--model", call.model]
    if call.write:
        argv += ["--permission-mode", "acceptEdits", "--allowedTools",
                 "Read", "Grep", "Glob", "Edit", "Write", "Bash(python3:*)", "Bash(python:*)", "Bash(git diff:*)", "Bash(git status:*)", "Bash(ls:*)"]
    else:
        argv += ["--allowedTools", "Read", "Grep", "Glob", "Bash(git diff:*)", "Bash(python3 -m unittest:*)",
                 "--disallowedTools", "Edit", "Write", "NotebookEdit"]

    def parse(p, tmp):
        try:
            d = json.loads(p.stdout)
        except json.JSONDecodeError:
            return p.stdout, {}, "could not parse claude JSON output"
        usage = {"cost_usd": d.get("total_cost_usd"), "tokens_in": (d.get("usage") or {}).get("input_tokens"),
                 "tokens_out": (d.get("usage") or {}).get("output_tokens"), "turns": d.get("num_turns")}
        return d.get("result") or "", usage, (d.get("result") or "error") if d.get("is_error") else ""
    return argv, None, parse


# --- OpenAI Codex CLI ------------------------------------------------------------------------------
def _codex(call: Call, tmp: Path):
    last = tmp / "last.txt"
    argv = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write" if call.write else "read-only",
            "-C", str(call.cwd), "-o", str(last)]
    if call.model:
        argv += ["-m", call.model]
    argv += [call.prompt]

    def parse(p, tmp):
        text = last.read_text() if last.exists() else p.stdout
        m = re.search(r"tokens used\s*\n\s*([\d,]+)", p.stdout + "\n" + p.stderr)
        return text, ({"tokens": int(m.group(1).replace(",", ""))} if m else {}), ""
    return argv, None, parse


# --- pi --------------------------------------------------------------------------------------------
def _pi(call: Call, tmp: Path):
    argv = ["pi", "-p", "--no-session"]
    if not call.write:
        argv += ["--tools", "read,grep,find,ls"]
    if call.model:
        argv += ["--model", call.model]
    argv += [call.prompt]
    return argv, None, lambda p, tmp: (p.stdout, {}, "")


BUILDERS = {"copilot": _copilot, "claude": _claude, "codex": _codex, "pi": _pi}


# --- replay ----------------------------------------------------------------------------------------
def _replay(call: Call) -> AgentResult:
    """Re-play a recorded station: same text, same code change, a short pause."""
    if not call.replay_dir or not (call.replay_dir / f"{call.replay_key}.json").exists():
        return AgentResult(text="", ok=False, seconds=0, error=f"no recording for {call.replay_key} in {call.replay_dir}")
    rec = json.loads((call.replay_dir / f"{call.replay_key}.json").read_text())
    # Pace: 1/FACTORY_REPLAY_SPEED of the recorded time (default 6x faster), between 1 and 10 seconds.
    speed = float(os.environ.get("FACTORY_REPLAY_SPEED", "6"))
    time.sleep(min(10.0, max(1.0, rec.get("seconds", 1) / speed)))
    patch = call.replay_dir / f"{call.replay_key}.patch"
    if call.write and patch.exists():
        # Recorded patches are cumulative from the base commit: reset, then apply.
        subprocess.run(["git", "reset", "-q", "--hard"], cwd=call.cwd, check=True)
        subprocess.run(["git", "clean", "-qfd"], cwd=call.cwd, check=True)
        if patch.stat().st_size:
            subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch.resolve())], cwd=call.cwd, check=True)
    return AgentResult(text=rec["text"], ok=True, seconds=rec.get("seconds", 0), usage={"replayed_from": rec.get("agent")})


def record(call: Call, result: AgentResult, cumulative_patch: str | None) -> None:
    """Save a station's output so `--agent replay` can reproduce it offline."""
    if not call.replay_dir:
        return
    call.replay_dir.mkdir(parents=True, exist_ok=True)
    (call.replay_dir / f"{call.replay_key}.json").write_text(json.dumps(
        {"agent": call.agent, "seconds": round(result.seconds, 1), "text": result.text, "usage": result.usage}, indent=1))
    if cumulative_patch is not None:
        (call.replay_dir / f"{call.replay_key}.patch").write_text(cumulative_patch)


def _log(call: Call, argv: list[str], out: str, err: str) -> None:
    if call.log:
        shown = [a if len(a) < 200 else a[:120] + f"…[{len(a)} chars]" for a in argv]
        with call.log.open("a") as f:
            f.write(f"$ {' '.join(shown)}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n\n")
