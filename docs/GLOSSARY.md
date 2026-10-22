# Software factories: glossary and references

This is the companion to the talk *Software Factories: from driving an agent to designing the line*. Each term has a definition you can point to. Where a source exists, it is named next to the term. Numbers from companies are **self-reported**: treat them as claims, not measurements.

## Glossary

| Term | Definition | Source |
|---|---|---|
| **Software factory** | A system, defined as code, that turns work items into verified, mergeable change using agents, with humans at the checkpoints, and improves itself from its own telemetry. | Working definition synthesised from Warp, StrongDM, Tessl and Factory (below) |
| | Warp: "a fleet of agents wired to your SDLC — triggered by an issue, a slack message, or a schedule, and coordinated by warp factories from triage through review to a mergeable PR." | [warp.dev](https://www.warp.dev) |
| | StrongDM: "non-interactive development where specs + scenarios drive agents that write code, run harnesses, and converge without human review." | [factory.strongdm.ai](https://factory.strongdm.ai/) |
| **Dark factory** (level 5) | "A black box that turns specs into software." No human writes or reviews the code. The name comes from FANUC's lights-out robot factory. | [Dan Shapiro, Jan 2026](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/) |
| **Five levels** | 0 spicy autocomplete · 1 coding intern · 2 junior developer · 3 developer (full-time reviewer) · 4 engineering team (you write specs and plans) · 5 dark factory. Modelled on the NHTSA driving-automation levels. | Shapiro; [summary by Simon Willison](https://simonwillison.net/2026/jan/28/the-five-levels/) |
| **Workflow vs agent** | Workflow: "LLMs and tools are orchestrated through predefined code paths". Agent: "LLMs dynamically direct their own processes and tool usage". A factory is a workflow whose stations are agents. | [Anthropic, Building effective agents, Dec 2024](https://www.anthropic.com/engineering/building-effective-agents) |
| **Harness** | Everything in an agent except the model: *Agent = Model + Harness*. There is the builder's harness (Claude Code, Copilot, Codex) and your outer harness (AGENTS.md, skills, tests, hooks, CI). | [LangChain](https://blog.langchain.com/the-anatomy-of-an-agent-harness/); [Böckeler](https://martinfowler.com/articles/exploring-gen-ai/harness-engineering.html) |
| **Harness engineering** | Designing the environments, intent, feedback loops and control systems that let agents do reliable work. | [OpenAI, Feb 2026](https://openai.com/index/harness-engineering/); [Böckeler, Apr 2026](https://martinfowler.com/articles/exploring-gen-ai/harness-engineering.html) |
| **Guide** (feedforward) | A control that steers the agent *before* it acts: AGENTS.md, skills, specs, templates, codemods. | Böckeler |
| **Sensor** (feedback) | A control that observes *after* the agent acts so it can self-correct: tests, linters, type checkers, AI review. | Böckeler |
| **Computational / inferential** | Deterministic, fast, cheap controls (tests, linters, structural tests) versus semantic, probabilistic ones (AI code review, LLM-as-judge). | Böckeler |
| **Back-pressure** | Anything wired in to reject invalid generated code: type systems, tests, linters, security scanners. "The wheel has got to turn fast." | [Geoffrey Huntley](https://ghuntley.com/ralph/) |
| **Ralph loop** | `while :; do cat PROMPT.md \| claude-code ; done`: an agent re-run on a fixed prompt until the work converges. | Huntley |
| **Inner / outer / meta loop** | Cheap checks before the PR (autonomy) / expensive checks after the PR (less human verification) / observing runs to improve the harness. | Dru Knox, Tessl ([talk](https://www.youtube.com/watch?v=X6l4lpA0_NY)) |
| **Background (cloud) agent** | An unattended agent that runs in a remote sandbox, starts from a work item, and ends in a PR. | Stripe Minions, Ramp Inspect, GitHub Copilot coding agent |
| **Trigger / ingress** | How work reaches the factory without someone typing a prompt: a ticket created or labelled, a webhook, an alert, a schedule. Here every trigger puts a ticket in the inbox. | Warp; `docs/TRIGGERS.md` |
| **Precheck** | A cheap command a scheduler runs before starting an agent; the run only happens if it succeeds (e.g. `next --check`: is work waiting?). Turns a schedule into a trigger without webhooks. | Orca automations |
| **Control plane** | The orchestration layer: dispatches runs, tracks them, retries, escalates, and hands off between cloud and local. | Warp factory stack; HumanLayer |
| **Factory-as-code** | Agents, prompts, gates, limits and checkpoints in versioned files, reviewed and revertible ("Terraform for agents"). | Warp; `factory/factory.toml` here |
| **Evidence** | Proof attached to an agent's change: test results, screenshots or video, reviewer verdicts, acceptance criteria met. | Warp, Ramp, Factory; `evidence.md` here |
| **Independent validator** | A checker that did not write the code, judging it against a contract written before the code. | Factory ([talk](https://www.youtube.com/watch?v=vGCJ7diEtrw)) |
| **Scenario / satisfaction** | An end-to-end user story stored outside the codebase, like a holdout set / the share of observed runs that likely satisfy the user. | StrongDM |
| **Digital twin universe** | Behavioural clones of third-party services (Okta, Jira, Slack, Google Docs…) used to validate at volume. | StrongDM |
| **AGENTS.md** | "A README for agents": an open format used by 60k+ open-source projects, stewarded by the Agentic AI Foundation (Linux Foundation). | [agents.md](https://agents.md/) |
| **Agent Skills** | "A lightweight, open format for extending AI agent capabilities with specialized knowledge and workflows": a folder containing `SKILL.md`. | [agentskills.io](https://agentskills.io/) |
| **MCP** | Model Context Protocol: an open protocol for connecting agents to tools and data. | [modelcontextprotocol.io](https://modelcontextprotocol.io/) |
| **Lethal trifecta** | Access to private data + exposure to untrusted content + the ability to communicate externally. Combine all three and "an attacker can easily trick it into accessing your private data and sending it to that attacker." | [Simon Willison, Jun 2025](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) |
| **Brain / hands separation** | Run the agent's harness (the "brain": model calls, session state, credentials, monitoring) on a durable server, and spawn disposable sandboxes (the "hands") only to execute code. If a sandbox dies the agent carries on, and untrusted agent-written code never sits next to credentials. | Katelyn Lesse, Anthropic, Vercel Ship 2026 ([talk](https://www.youtube.com/watch?v=Fr5vzNknYJE), 1:21:53) |
| **Credential brokering** | Code in the sandbox holds only a placeholder token; the real credential is injected at the egress firewall/proxy on the way out. Combine with deny-by-default egress and a kill switch kept outside the sandbox. | Anthropic and Vercel, Vercel Ship 2026; GitHub Agentic Workflows uses an API proxy for the same purpose |
| **Verification engineer** | The engineer's role once agents write the code: building harnesses, acceptance tests and verifiable checks rather than hand-writing code. "We are now all verification engineers." | Tobi Lütke, Shopify, Vercel Ship 2026 (6:22:25) |
| **Continuous AI** | Coding agents running in CI to keep improving a repository: "a third pillar beside CI and CD". | [GitHub Agentic Workflows](https://github.github.com/gh-aw/) |
| **Gray factory** | The middle ground between human-reviewed and lights-out: lights dimmed, humans review by risk. | Victor Rentea ([talk](https://www.youtube.com/watch?v=H-z5mrBOD48)) |
| **Harnessability** | How far a codebase's properties (types, module boundaries, frameworks) let you build guides and sensors. | Böckeler |
| **Factory engineering** | Measuring the factory (DORA, scorers), finding improvements to skills, context and model mix, and shipping them. "Factory engineering is real engineering and a skill to develop." | [Warp, Sep 2026](https://www.warp.dev/blog/adapting-for-a-world-of-software-factories) |

## Metrics worth tracking

- **DORA** (keep): lead time for changes, deployment frequency, change failure rate, time to restore. DORA 2025: AI's "primary role is as an amplifier, magnifying an organization's existing strengths and weaknesses" ([dora.dev](https://dora.dev/research/2025/dora-report/)).
- **Factory metrics** (add): cost per merged change, human touches per PR, autonomy (% merged with no human code edits), escalation rate, first-pass review rate, escaped defects. `python3 factory/run.py report` computes a minimal version.
- **Avoid**: counting PRs, lines or tokens. Output metrics "can actually disguise how well these systems are working" (Ryan Cooke, WorkOS).

## Monday checklist

1. Make one repo agent-ready: AGENTS.md, one-command tests, fast CI.
2. Pick one loop with a verifiable outcome.
3. Put the gates outside the agent.
4. Require evidence on every agent PR.
5. Record every run: cost, touches, outcome.
6. Each week, turn repeated findings into guides and sensors.

## References

**Definitions and frameworks**
- Dan Shapiro, [The Five Levels: from Spicy Autocomplete to the Dark Factory](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/), 23 Jan 2026
- Anthropic, [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (Dec 2024) and [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (Nov 2025)
- Birgitta Böckeler, [Harness engineering for coding agent users](https://martinfowler.com/articles/exploring-gen-ai/harness-engineering.html), martinfowler.com, Apr 2026
- LangChain, [The Anatomy of an Agent Harness](https://blog.langchain.com/the-anatomy-of-an-agent-harness/)
- OpenAI (Ryan Lopopolo), [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/), Feb 2026 ([InfoQ summary](https://www.infoq.com/news/2026/02/openai-harness-engineering-codex/))
- Geoffrey Huntley, [Ralph Wiggum as a "software engineer"](https://ghuntley.com/ralph/)
- Simon Willison, [The lethal trifecta for AI agents](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/), 16 Jun 2025
- HumanLayer, [12-factor agents](https://github.com/humanlayer/12-factor-agents)

**Factories in practice**
- StrongDM, [Software Factory](https://factory.strongdm.ai/), Feb 2026, plus Simon Willison's [write-up](https://simonwillison.net/2026/Feb/7/software-factory/)
- Stripe, [Minions: Stripe's one-shot, end-to-end coding agents](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents), Feb 2026: 1,000+ merged PRs a week, human-reviewed
- Spotify, [1,500+ PRs later: background coding agent (Honk), part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1), Nov 2025
- Ramp, [Why we built our background agent](https://builders.ramp.com/post/why-we-built-our-background-agent): ~30% of merged PRs
- Warp: [Factories docs](https://docs.warp.dev/factories), [The factory stack](https://www.warp.dev/blog/the-factory-stack), [Crawl, walk, run](https://www.warp.dev/blog/adopting-the-software-factory-model-crawl-walk-run), [Adapting for a world of software factories](https://www.warp.dev/blog/adapting-for-a-world-of-software-factories) (Sep 2026)
- GitHub: [Agentic Workflows (gh-aw)](https://github.github.com/gh-aw/), [Copilot coding agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent), [Spec Kit](https://github.com/github/spec-kit)

**Talks** (YouTube)
- Zach Lloyd (Warp), [Software Engineering Is Becoming Factory Engineering](https://www.youtube.com/watch?v=tUPPVhBBcoM)
- Dex Horthy (HumanLayer), [Why Software Factories Fail](https://www.youtube.com/watch?v=Ib5GBkD555M) and [Fighting Code Slop](https://www.youtube.com/watch?v=ix1qQK1IvmA)
- Dru Knox (Tessl), [Harness Engineering: How to Build a Software Factory](https://www.youtube.com/watch?v=X6l4lpA0_NY); Tessl, [850 PRs a Week](https://www.youtube.com/watch?v=GRixg2mdJJA)
- Tereza Tížková (Factory), [What It Actually Takes to Build a Software Factory](https://www.youtube.com/watch?v=vGCJ7diEtrw)
- Ryan Cooke (WorkOS), [No, That's Not a Software Factory](https://www.youtube.com/watch?v=HvboD89DyQ8)
- Gabriel Martinez (G2i), [Generation Is Cheap, Review Is Expensive](https://www.youtube.com/watch?v=6qkzlT962es)
- Ryan Lopopolo (OpenAI), [Harness Engineering](https://www.youtube.com/watch?v=am_oeAoUhew)
- Victor Rentea, [Gray Factory: Code Review for Agentic Engineers](https://www.youtube.com/watch?v=H-z5mrBOD48)
- Vercel Ship 2026, [SF livestream](https://www.youtube.com/watch?v=Fr5vzNknYJE): Katelyn Lesse (Anthropic) on Claude Managed Agents, brain/hands separation and agent security (1:17:28), and Tobi Lütke on Shopify's River agent and "verification engineers" (5:59:50). Company numbers are self-reported.

**Evidence and history**
- METR, [early-2025 developer productivity RCT](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/): 19% slower, while believing they were 20% faster. Then the [Feb 2026 update](https://metr.org/blog/2026-02-24-uplift-update/): likely faster now, but hard to measure
- DORA, [State of AI-assisted Software Development 2025](https://dora.dev/research/2025/dora-report/)
- M. Cusumano, "The Software Factory: A Historical Interpretation", *IEEE Software* 6(2), 1989 ([doi](https://doi.org/10.1109/ms.1989.1430446)). Hitachi Software Works (1969) was the first organisation to use the term
- J. Greenfield, K. Short, S. Cook, S. Kent, *Software Factories: Assembling Applications with Patterns, Models, Frameworks, and Tools*, Wiley, 2004
