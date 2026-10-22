# factory-starter

A minimal **software factory** you can read in 15 minutes, run in 5, and build on.

A work item goes in. Agents write a spec, build the change and review it independently. Deterministic gates check the work, the evidence is collected, and every run is recorded. A human decides what merges.

```
 ticket ─▶ 1 intake ─▶ 2 spec ─▶ 3 build ─▶ 4 gates ─▶ 5 review ─▶ 6 evidence ─▶ 7 ship ─▶ 8 record
 (md / issue)   code       agent      agent       code        agent        code          code      code
                         read-only    writes    ▲  │ fail    independent                 ◆ human   runs.jsonl
                              ◆ optional        └──┘ fix      read-only                   merges        │
                              human approval    (≤2 rounds)   ▲  │ changes                              ▼
                                                              └──┘ revise (1 round)         learn: propose AGENTS.md rules
```

**Agents propose, code disposes.** Agents do the creative work (spec, build, review). A plain Python script owns the control flow, the gates, the evidence and the record, so the parts that must always happen don't depend on a model remembering to do them.

> Companion to the talk *Software Factories: from driving an agent to designing the line*. **Glossary, metrics and references: [docs/GLOSSARY.md](docs/GLOSSARY.md).**

## Your first factory in 10 minutes

You need Python 3.11+, git, and one coding-agent CLI that is logged in:
[GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/copilot-cli) (`copilot`), [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude`), [OpenAI Codex CLI](https://github.com/openai/codex) (`codex`) or [pi](https://github.com/earendil-works/pi) (`pi`). No agent? You can replay recorded runs offline (below).

```bash
git clone https://github.com/Martz/factory-starter && cd factory-starter
python3 factory/run.py doctor                    # preflight: tools, auth, gates green on HEAD

# 1. A ticket arrives. This file is a real-shaped Jira "issue created" webhook.
python3 factory/run.py ticket --payload examples/webhooks/jira-issue-created.json

# 2. The factory takes the oldest ticket: spec → build → gates → independent review → evidence → branch.
python3 factory/run.py next

# 3. You decide. Read the evidence and the change, then merge the branch (or don't).
python3 factory/run.py show --diff
```

With only one agent installed, use it for every station: `python3 factory/run.py next --agent claude`. By default the build agent is Copilot and the reviewer is Codex (`factory/factory.toml`).

No model to hand? `python3 factory/run.py ticket --from work/004-split-evenly.md`, then `python3 factory/run.py next --agent replay` replays a recorded run from `factory/replays/` offline. It's also handy for rehearsing a demo.

### Point a real trigger at it

Every trigger just drops a ticket in the inbox (`.factory/inbox/`), so you can start simple and swap triggers later. **[docs/TRIGGERS.md](docs/TRIGGERS.md)** has the recipes:

- **A webhook:** `python3 factory/run.py serve --run` receives Jira, Linear and GitHub issue events and runs each ticket as it arrives.
- **A schedule:** an [Orca](https://onorca.dev) automation or a cron job, gated by `python3 factory/run.py next --check` (exit 0 only when work is waiting). Orca can also pull from Jira or Linear directly.
- **A label in GitHub:** `.github/workflows/factory.yml` runs the line in Actions when an issue is labelled `factory`, and opens a PR with the evidence.

Only tickets labelled `factory` get in from payloads, because ticket text is untrusted input.

### Run work items directly

```bash
python3 factory/run.py run work/001-reject-invalid-prices.md
python3 factory/run.py run work/002-service-charge.md --checkpoint spec   # pause for a human to approve the spec
python3 factory/run.py report                 # lead time, autonomy, fix rounds, spend
python3 factory/run.py show [--diff | --try "python3 -m lunchbox friday.csv"]   # inspect the latest run
```

Each run leaves:
- a branch `factory/<run-id>` with one commit, ready for you to review and merge (`git diff main..factory/<run-id>`)
- `.factory/runs/<run-id>/`, holding `spec.md`, `evidence.md` (the PR body), the gate logs, the review JSON and the agent logs
- a line in `.factory/runs.jsonl`, the factory's own telemetry

## How it works

| # | station | who | what it does | vocabulary |
|---|---|---|---|---|
| 1 | intake | code | creates a git worktree and branch from `HEAD` | work ingress |
| 2 | spec | agent, read-only | writes a summary, 3–7 testable acceptance criteria, a plan and a risk level | spec-driven development |
| ◆ | approve | **human** | optional: approve the spec before anything is built (`--checkpoint spec`) | human checkpoint |
| 3 | build | agent, writes | implements the change and its tests, guided by `AGENTS.md` | guide (feedforward) |
| 4 | gates | code | runs `test`, `compile` and `tests_kept`. On failure the output goes back to the agent, at most twice, then the run escalates | sensor (feedback), back-pressure |
| 5 | review | a *different* agent, read-only | checks the diff against every criterion and returns a JSON verdict. "changes" sends one revise round | independent validator |
| 6 | evidence | code | writes `evidence.md`: spec, gate results, review table, diff stats, usage | agents prove their work |
| 7 | ship | code | commits the branch (with `--pr`, also pushes and opens a PR). It never merges | human merge |
| 8 | record | code | appends the run to `runs.jsonl` | measure outcomes |
| ↻ | learn | agent, read-only | `run.py learn` mines recent findings and failures, then proposes `AGENTS.md` rules | improvement loop |

Read-only is **enforced by the factory, not by trusting the agent**: after a read-only station it checks git for changes, reverts them and records a violation. The `tests_kept` gate fails the run if any existing `test_*` function disappears.

Files:

```
AGENTS.md               guides: rules every agent gets (an open standard: agents.md)
work/*.md               sample work items (run them directly, or queue them: ticket --from FILE)
examples/webhooks/      Jira, Linear and GitHub payloads, to simulate tickets arriving
factory/factory.toml    factory-as-code: which agent runs each station, the gates, limits, checkpoints
factory/prompts/*.md    the station instructions
factory/run.py          the orchestrator (stdlib only)
factory/inbox.py        ingress: the ticket inbox, webhook parsing and the webhook receiver
factory/agents.py       adapters: copilot | claude | codex | pi | replay
factory/tests/          tests for the factory itself (replay-driven, no model calls)
.github/workflows/      ci.yml (product + factory tests) and factory.yml (label an issue → PR)
```

## Crawl → walk → run

- **Crawl: on your laptop.** Run the line on small, verifiable work items: bug fixes, validation, small features, dependency bumps. Watch `report`. Turn repeated review findings into `AGENTS.md` rules and gates (`run.py learn`).
- **Walk: give it a trigger.** Work arrives without you: a Jira, Linear or GitHub webhook (`serve`), a schedule (an Orca automation or cron, gated by `next --check`), or a GitHub label (`factory.yml` runs the line in Actions and opens a PR with the evidence; *not yet exercised in this repo's CI, so test it on a scratch repo first*). See [docs/TRIGGERS.md](docs/TRIGGERS.md).
- **Run: as a platform.** Use real sandboxes per run, a work queue, model routing, cost budgets, scorers or benchmarks that replay past work items against new prompts and models, and dashboards. Then decide what to buy rather than build: GitHub Copilot coding agent, [GitHub Agentic Workflows](https://github.github.com/gh-aw/), Cursor Automations, Warp, Factory, Codex cloud and others.

## Use it on your own repository

1. Copy `factory/` and `AGENTS.md` into your repo, and add `.factory/` to `.gitignore`.
2. Edit the `[gates]` in `factory/factory.toml` to use your real commands: tests, linter, type checker, build. Keep them fast; they run after every build round.
3. Rewrite `AGENTS.md` for your codebase. Include the one-command test and the rules that reviewers keep repeating.
4. Write work items the way you would brief a colleague: the problem, the expected behaviour, and examples.
5. Run `doctor`, then one small work item, then read the evidence before you trust the next one.
6. Point one trigger at it ([docs/TRIGGERS.md](docs/TRIGGERS.md)), keep the `factory` label restricted, and keep merging by hand.

## Safety: read this before pointing it at real code

- **A git worktree is not a sandbox.** Copilot (`--allow-all-tools`), Claude Code and pi run with *your* user permissions on *your* machine. Codex runs in its own sandbox. For real use, run the factory inside a container, dev container or VM with no production credentials.
- **Work items are untrusted input.** If issue text can come from outside your team, an agent that also has private data and a way to send it out has all three parts of the [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). Keep the trigger (the `factory` label) restricted to maintainers, and keep secrets away from the agent. The webhook receiver binds to localhost unless you set `FACTORY_WEBHOOK_TOKEN`; put real ingress in front of it before exposing it.
- **The factory never merges.** Keep it that way until your evidence, metrics and gates have earned more trust.

## Test the factory

```bash
python3 -m unittest discover -s tests -q            # the product
python3 -m unittest discover -s factory/tests -v    # the factory: fix loop, review loop, escalation, tests_kept, ingress
```

The factory is software too. Version it, test it and review changes to it like any other code.
