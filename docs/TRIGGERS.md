# Point a trigger at the line

A factory starts when work arrives, not when you type. In this starter, every trigger does the same small thing: it puts a **ticket** in the inbox (`.factory/inbox/`). `run.py next` runs the line on the oldest one and files it under `done/` or `failed/` with the run id, outcome and branch.

```
 Jira · Linear · GitHub issue ─┐
 a webhook (run.py serve)  ────┤                    ┌──────────── the line ────────────┐
 a schedule (Orca, cron)   ────┼─▶ .factory/inbox ─▶ spec ▸ build ▸ gates ▸ review ▸ evidence ─▶ branch / PR ─▶ ◆ you merge
 you (run.py ticket)       ────┘     oldest first   └──────────────────────────────────┘
```

Because every trigger ends in the same inbox, the line never needs to know where work came from. Start with a simulated ticket, then wire up a real trigger once you trust the evidence.

## 1. Simulate a Jira ticket (no server, no account)

```bash
python3 factory/run.py ticket --payload examples/webhooks/jira-issue-created.json   # a Jira "issue created" webhook
python3 factory/run.py next                                                          # the factory takes it
```

`examples/webhooks/` also has Linear and GitHub payloads, plus `jira-issue-no-label.json`, an unlabelled ticket that tries a prompt injection. The factory ignores it (see [Safety](#safety)).

No agent CLI to hand? Queue a sample work item and replay its recording offline:

```bash
python3 factory/run.py ticket --from work/004-split-evenly.md
python3 factory/run.py next --agent replay
```

## 2. A webhook: tickets arrive over HTTP

```bash
python3 factory/run.py serve --run          # terminal 1: listen on http://127.0.0.1:8765/webhook and run tickets as they arrive
curl -s -d @examples/webhooks/jira-issue-created.json http://127.0.0.1:8765/webhook   # terminal 2: "a ticket was created"
```

`serve` understands Jira Cloud (`jira:issue_created` / `issue_updated`, including Jira's rich-text descriptions), Linear (`Issue` create/update) and GitHub (`issues` opened/labeled) payloads, and any JSON with `{title, body}`. It de-duplicates by issue key, because trackers send the same issue more than once. Without `--run` it only queues; run `next` yourself.

To receive real webhooks, the receiver needs a URL the tracker can reach. Put it behind your own ingress, or a tunnel while you experiment. **Always set a token** (`serve` refuses to listen beyond localhost without one):

```bash
export FACTORY_WEBHOOK_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
python3 factory/run.py serve --run --host 0.0.0.0
```

| Tracker | Where to configure it | Send the token as |
|---|---|---|
| Jira Cloud | Project settings → Automation: *When issue created* (+ label = factory) → *Send web request*, method POST, body "Issue data (Jira format)" | header `X-Factory-Token` |
| Linear | Settings → API → Webhooks, Issues events | `…/webhook?token=…` |
| GitHub | Repository settings → Webhooks, *Issues* events (or use `factory.yml`, below) | `…/webhook?token=…` |

## 3. A schedule: Orca automations or cron

A schedule plus a cheap check is a trigger. `next --check` exits 0 only when a ticket is waiting, so it's the guard.

**cron** (or launchd, or a CI schedule):

```cron
*/10 * * * *  cd /path/to/repo && python3 factory/run.py next --check >/dev/null && python3 factory/run.py next >> .factory/cron.log 2>&1
```

**[Orca](https://onorca.dev) automation.** An Orca automation is a scheduled prompt for an agent, with an optional *precheck* command: exit 0 runs it, anything else records a skipped run. The agent is only the operator here. The factory's deterministic line does the work.

```bash
orca automations create --name "factory: next ticket" --trigger "*/10 * * * *" \
  --precheck "python3 factory/run.py next --check" \
  --prompt "You operate this repository's software factory. From the repository root run: python3 factory/run.py next. Wait for it to finish. Do not edit files yourself. Report the outcome banner, the run id and the evidence path." \
  --provider copilot --workspace "path:$PWD" --enabled
```

Checked against Orca 1.4.233 on 22 Oct 2026:
- A scheduled run with an empty inbox was recorded as `skipped_precheck` and no agent started. With a ticket waiting, the precheck passed and Orca dispatched the agent.
- Use `--workspace` (the existing checkout), not `--repo`. `--repo` creates a new folder per run, and coding-agent CLIs stop each new folder at a "trust this folder?" prompt, so unattended runs block. The factory already makes its own worktree per run.
- **Trust the folder once** in your agent CLI (open `copilot` or `codex` in the repo and accept). Until you do, runs fail with `agent-trust-workspace`.
- *Run now* (`orca automations run`) skips the precheck. Only scheduled runs are gated.

**Orca with Jira or Linear, with no webhook or server.** Orca has saved Jira and Linear connections, so the precheck can pull matching issues into the inbox itself. Ticket keys de-duplicate, so pulling every 10 minutes is safe:

```bash
--precheck "orca jira search \"project = LUNCH AND labels = factory AND statusCategory = 'To Do'\" --json | python3 factory/run.py ticket --payload - ; python3 factory/run.py next --check"
```

Add the write-back to the prompt: *"…then comment the outcome and the branch or PR link on the Jira issue with `orca jira comment add`, and move it to In Review."* Deterministic code pulls and runs the work, and the agent handles the conversation with the tracker. `ticket --payload` reads the JSON that `orca jira search` prints (checked on 22 Oct 2026); the full Jira round trip still needs testing on your own site.

## 4. GitHub Actions: label an issue, get a PR

`.github/workflows/factory.yml` runs the same line in Actions when someone adds the `factory` label to an issue, then opens a PR with the evidence and comments on the issue. Setup notes are at the top of the file. *It is a starting point and hasn't been exercised in this repo's CI yet; test it on a scratch repository first.*

## Hosted alternatives: crawl first

If you'd rather not run anything yourself, start with single-purpose automations ("crawl") and come back for the full line later:

| Option | What you get | Trigger |
|---|---|---|
| [GitHub Agentic Workflows](https://github.github.com/gh-aw/) + [githubnext/agentics](https://github.com/githubnext/agentics) | ready-made workflows: issue triage, CI doctor, Repo Assist; `gh aw add-wizard githubnext/agentics/issue-triage` | issues, PRs, schedules, `/commands` |
| GitHub Copilot coding agent | assign an issue to Copilot, get a PR | issue assignment |
| [Cursor Automations](https://cursor.com/docs/cloud-agent/automations) | cloud agents with memory | schedule, GitHub, Linear, Slack, PagerDuty, webhooks |
| Codex | `@codex` on issues and PRs; scheduled automations in the app | mentions, schedules |
| [Warp Factories](https://docs.warp.dev/factories/quickstart/) | a hosted factory defined as code; see also [cloud-factory-demo](https://github.com/warpdotdev-demos/cloud-factory-demo) (GitHub Actions + Warp's Oz agents) | Slack, Linear, Jira, GitHub, schedules |

## Safety

- **Ticket text is untrusted input.** Payloads only get in with the `[ingress] label` from `factory/factory.toml` ("factory" by default). Restrict who can apply that label. The spec and build prompts also tell the agents that ticket text can't change their instructions. That helps, but it isn't a security boundary.
- **The webhook receiver is minimal.** It binds to localhost by default, needs `FACTORY_WEBHOOK_TOKEN` for anything else, and caps request size. Put real ingress (TLS, rate limits, and the tracker's own signature checks) in front of it before exposing it.
- **A schedule runs with your permissions.** Prefer a container, VM or dev box with no production credentials for unattended runs. The factory never merges, so keep the human merge.
