---
name: doctor
description: Self-test the workspace build's wiring for Claude Code and Codex — fires the real hooks, checks skill and agent discovery, validates MCP and git safety, then reports PASS/FAIL with a runbook. Use after installing the layer, after an agent CLI update, after settings/permissions/hooks change, or when a guard or skill stopped firing. Fixes nothing by design.
argument-hint: "(optional) which part to focus on: hooks | mcp | git"
---

## Parameters

| Placeholder | Meaning | Reference value (Acme) |
|---|---|---|
| qa-cert | Short slug used in artifact/sandbox names | acme |
| номера в названиях тестов (без live-трекера) | Issue tracker name | Jira |

# doctor — is the safety net still connected?

A safety net nobody tests dies quietly. The reference build this kit comes from already
paid for that once: the deny list in `.claude/settings.local.json` named an MCP server
that did not exist, so the "drafts only" guarantee (a human publishes, the AI does not)
had nothing behind it for a month while every session behaved as if it did. Config files
describe intent; only firing the mechanism proves it works.

## Run it

```bash
python3 .claude/skills/doctor/scripts/doctor.py
python3 .claude/skills/doctor/scripts/doctor_codex.py   # when Codex is installed
```

Takes ~30 seconds (most of it is `claude mcp list` health-checking connectors).
Exit code 1 means at least one FAIL. What it covers:

The first script validates Claude Code. The Codex companion validates the generated
`AGENTS.md`, `.agents/skills`, `.codex/agents`, the project-local hook, its exit-2
contract, `codex doctor --json`, and the `AGENTS.md` line count, judged on its
`CLAUDE.md` body after the generated header. It requires commit and destructive push
to block always; plain push and PR/MR creation block under `never`/`on-request` and
pass under `PUSH_POLICY=auto`, where it also requires the SETUP-PLAN's code-host gate
to be filled. Run both when the workspace supports both hosts.

| Group | What is actually done |
|---|---|
| Registration | The guard hook present in `.claude/settings.local.json` — the workspace's own settings, nothing machine-wide — pointing at this workspace's script with an interpreter that identifies itself; a leftover registration in `~/.claude/settings.json` from an earlier kit version is named as a WARN |
| Live fire | Sandbox git repo under `.doctor-sandbox/`; the **registered** hook command is invoked with the same JSON payload Claude Code sends; expects a block on a staged `.claude/` file, `push --force`, `push --delete`, `reset --hard`, `clean -fd`, `branch -D`, `checkout .` and `reset --hard` carried inside an interpreter heredoc — under every policy; `commit` (plain, `-am`, chained, in a heredoc) blocked under `COMMIT_POLICY=never` and let through under `on-request`; `push`, `push -u`, a heredoc push and `gh pr create` / `glab mr create` blocked under `PUSH_POLICY=never` and let through under `on-request` and `auto` (a guard from before the parameter is a WARN: PR/MR creation is prompt-only there); expects a pass on `git add`, `git status`, `git log --grep=commit`, `gh pr view`, an `mr.md` draft that quotes `git commit`/`git push`, and any repo outside the workspace; runs the guard's unit tests (skipped when the guard isn't registered — there is nothing to fire at) |
| Self-test | The doctor's own unit tests (`test_doctor.py`) — a top-level step, always run regardless of whether the guard is registered: `python3 .claude/skills/doctor/scripts/test_doctor.py` |
| Git hygiene | Nothing of the layer is written into client repos — the doctor only reports, read-only, traces an earlier kit version left there (an exclude block in `.git/info/exclude`, skill/agent links) for the human to remove by hand; no leftover global `core.excludesFile`; `includeCoAuthoredBy: false` in the workspace settings |
| MCP wiring | Every `mcp__<server>__*` in allow/ask/deny resolves to a live connected server (the incident above), exactly one номера в названиях тестов (без live-трекера) MCP server, no write-looking tool in `allow`, deny non-empty, global `mcpServers` empty. Skipped under `TRACKER_MCP_PREFIX=none` (one PASS line says so), where the generic rules still run — every `mcp__` permission entry names a live server, no write-looking tool in allow, deny non-empty, the global `mcpServers` WARN; `TRACKER_MCP_POLICY` cross-checked against the buckets (`block-all`: no tracker tool in allow/ask, the server denied whole) |
| Policy | `COMMIT_POLICY` and `PUSH_POLICY` as the guard carries them vs the permission buckets (`never`: entries in deny, an `ask` is a WARN; `on-request`: entries in `ask`, `allow` is a FAIL, an auto-approving `defaultMode` is a FAIL — the prompt is the only approval left; `PUSH_POLICY=auto`: entries in `allow`, `deny` is a FAIL, and the SETUP-PLAN §1 row "What protects the default branch" must be filled — a FILL, empty or "nothing" is a FAIL, because that row names the only gate left); the live `defaultMode`; `model` / `effortLevel` pinned; `CLAUDE.md` line count against the 150-line cap (WARN above) |

The sandbox repos are deleted afterwards, including on failure; a sandbox the doctor cannot remove (read-only git objects on Windows) is a FAIL that names the path to remove by hand.

## Then do the checks the script cannot

No tracker MCP (`none` in the setup plan): there is nothing to compare — say so and go straight to the push probe below.

The script sees server *names*; only a live session sees the *tools*. So after it runs:

1. Read the actual tool list available to you this session (the `mcp__…` tools).
2. Compare it against `allow` and `deny` in `.claude/settings.local.json`:
   - a **deny** entry with no matching live tool = a rule guarding nothing (report it, name the entry);
   - a live **write** tool (create/update/delete/edit/add/transition/assign…) that is
     in neither `deny` nor `allow` = unlisted, so it prompts — acceptable, but say so;
   - a live write tool present in `allow` = a hole in the drafts-only rule, report it loudly.
3. State plainly which of the three you found. "Looks fine" without naming the tools you
   compared is not an answer.

If the connector exposes no write tools at all today, say that too — then the deny names
are unverifiable placeholders, not enforcement, and that is worth knowing before relying
on them.

The script also calls the guard directly, so it cannot see whether this host runs it.
Run `git push --force` at the workspace root: it must come back `git-guard: BLOCKED`.
The personal git has no remote, so if git answers instead nothing leaves the machine —
but this host is not running the hook (in Codex: the `/hooks` entry is untrusted).
Report that as a FAIL on the guard.

## Reporting

Repeat the FAIL/WARN lines and their runbook commands to the user as-is. Then stop:

- **Never fix a FAIL by editing the deny/allow list, the hook, or the settings yourself.**
  A safety net that rewrites itself is worse than a broken one — the whole point is that a
  human sees the failure. The one exception is a fix the user explicitly asks for in this
  conversation, after seeing the report.
- OAuth and `claude mcp` re-auth are interactive; hand over the command, do not attempt it.
- FAIL on a guard means the iron rules ("push is human-only" — or "only on the human's word"
  under `PUSH_POLICY=on-request`, or "no destructive push" under `auto` — and "no AI files in
  client repos") are currently prompt-only. Say that in those words and do not start a ticket until it is green.

## When to run it

- After installing the layer on a new machine (the workspace cloned or copied over).
- After a Claude Code or Codex update (hook and settings formats move).
- After any edit to `~/.claude/settings.json`, `.claude/settings.local.json`, or the hooks.
- When something feels off: a command that should have been blocked went through,
  the charter is missing from a fresh session, a tracker call fails.
- First step of any weekly build review.

Record the outcome in `.claude/RETRO.md` only when something failed — a green run is the
expected state and does not need a note.
