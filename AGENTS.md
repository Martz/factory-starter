# AGENTS.md: lunchbox

Guidance for any coding agent (Copilot, Claude Code, Codex, pi…) working in this repository.
The factory feeds this file forward to every station. Humans: when the factory keeps making the same mistake, add a rule here (see `python3 factory/run.py learn`).

## What this is
A tiny Python library and CLI that splits a group lunch bill. Standard library only.

## Commands
- Test: `python3 -m unittest discover -s tests -q`
- Run: `python3 -m lunchbox friday.csv`

## Rules
- Python 3.11+, standard library only. Do not add dependencies.
- Money is always `Decimal`, created with `lunchbox.money()`. Never use `float` for money.
- Per-person amounts must always add up exactly to the order total: no lost or extra pennies.
- Every behaviour change needs a unittest in `tests/` that would fail without the change.
- Never delete or weaken an existing test to make the suite pass.
- Keep changes small. Don't reformat unrelated code.
- CLI output stays a fixed-width table ending with the `TOTAL` line. Errors go to stderr with a non-zero exit code.
- Don't touch `factory/` or `.github/`. That is the factory itself, and it changes through human-reviewed PRs.
