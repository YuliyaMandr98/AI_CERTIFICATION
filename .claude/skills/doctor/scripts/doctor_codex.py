#!/usr/bin/env python3
"""Read-only self-test for the Codex half of an installed workspace."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

WORKSPACE_ROOT = os.path.realpath(os.path.expanduser("/Users/oadmin/PROJECTS/FINCA/qa-api-tests-ai-delegation"))
PROJECT_HOOKS = os.path.join(WORKSPACE_ROOT, ".codex", "hooks.json")
GUARD = os.path.join(WORKSPACE_ROOT, ".claude", "hooks", "git-guard.py")
TRACKER_MCP_PREFIX = "none"


def effective_prefix(raw):
    value = (raw or "").strip()
    if not value or value.lower() == "none" or "{{" in value:
        return ""
    return value


TOKEN = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
BRANCH_PROTECTION_ROW = "What protects the default branch"


def load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def split_command(command):
    return [next(group for group in match.groups() if group is not None)
             for match in re.finditer(r'''"([^"]*)"|'([^']*)'|(\S+)''', command)]


def installed_push_policy():
    """PUSH_POLICY carried by the installed guard, fail-closed to never."""
    try:
        with open(GUARD, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return "never"
    match = re.search(r'''^PUSH_POLICY\s*=\s*["']([^"']*)["']''', text, re.M)
    if not match:
        return "never"
    value = match.group(1).strip().lower()
    return value if value in ("never", "on-request", "auto") else "never"


def installed_tracker_policy():
    """TRACKER_MCP_POLICY carried by the installed guard, fail-open to drafts-only —
    the guard's own reading of a missing or unrecognised value."""
    try:
        with open(GUARD, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return "drafts-only"
    match = re.search(r'''^TRACKER_MCP_POLICY\s*=\s*["']([^"']*)["']''', text, re.M)
    if not match:
        return "drafts-only"
    value = match.group(1).strip().lower()
    return value if value == "block-all" else "drafts-only"


def source_digests(root):
    """sha256 of every .claude source the Codex layer is generated from.

    Must return the same map as sync_codex_workspace.source_digests on the flash
    drive, which records it at generation time; a test holds the two together.
    CRLF is folded to LF so a Windows checkout of the personal repo agrees.
    """
    paths = [os.path.join(root, "CLAUDE.md")]
    skills = os.path.join(root, ".claude", "skills")
    if os.path.isdir(skills):
        for name in sorted(os.listdir(skills)):
            skill_dir = os.path.join(skills, name)
            if not os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
                continue
            for base, dirs, names in os.walk(skill_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                paths += [os.path.join(base, n) for n in names if not n.endswith(".pyc")]
    agents = os.path.join(root, ".claude", "agents")
    if os.path.isdir(agents):
        paths += [os.path.join(agents, n) for n in sorted(os.listdir(agents)) if n.endswith(".md")]
    digests = {}
    for path in paths:
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        digests[rel] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    return digests


def stale_sources(root):
    """Sources that differ from the generator's record; empty when the layer is fresh."""
    record = load_json(os.path.join(root, ".codex", "generated-from.json"))
    recorded = (record or {}).get("sources")
    if not isinstance(recorded, dict):
        return [".codex/generated-from.json (missing — generated before the record existed)"]
    current = source_digests(root)
    return sorted(rel for rel in set(recorded) | set(current)
                  if recorded.get(rel) != current.get(rel))


def recorded_branch_protection():
    """SETUP-PLAN answer naming the code-host gate required by PUSH_POLICY=auto."""
    try:
        plans = sorted(name for name in os.listdir(WORKSPACE_ROOT)
                       if name.endswith("-SETUP-PLAN.md"))
    except OSError:
        return None
    for name in plans:
        try:
            with open(os.path.join(WORKSPACE_ROOT, name), encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        match = re.search(r"^\|\s*" + re.escape(BRANCH_PROTECTION_ROW) +
                          r"\s*\|([^|\n]*)\|", text, re.M)
        if not match:
            continue
        value = match.group(1).strip()
        if value and "<FILL" not in value and value.lower() not in ("nothing", "none", "-", "—"):
            return value
    return None


def hook_registration(config):
    """(command, matcher) of the guard registration, or (None, None)."""
    for group in ((config or {}).get("hooks", {}) or {}).get("PreToolUse", []) or []:
        matcher = group.get("matcher", "")
        if "Bash" not in matcher:
            continue
        for hook in group.get("hooks", []) or []:
            command = hook.get("command", "")
            if any(os.path.realpath(token) == os.path.realpath(GUARD)
                   for token in split_command(command) if token.endswith(".py")):
                return command, matcher
    return None, None


def hook_command(config):
    return hook_registration(config)[0]


def matcher_problem(matcher, prefix):
    """Why the registered matcher does not fit the tracker setting, or None if it does."""
    if not prefix:
        if matcher != "Bash":
            return (f'matcher is "{matcher}" but TRACKER_MCP_PREFIX=none expects exactly '
                    f'"Bash" — Codex would route MCP calls through a guard with no tracker '
                    f"to guard")
        return None
    if prefix not in matcher:
        return (f'matcher "{matcher}" does not contain the tracker prefix {prefix} — Codex '
                f"never sends tracker tool calls to the guard, so the tracker policy is "
                f"not enforced there")
    return None


def fire(command_argv, payload):
    """Run the registered hook command. A probe that cannot start is a FAIL, not a
    traceback: an interpreter that has moved or been uninstalled is exactly the
    silent-failure case this doctor exists to catch, and crashing here skipped the
    remaining checks and the summary line."""
    try:
        return subprocess.run(command_argv, input=payload, capture_output=True,
                              text=True, timeout=30).returncode, ""
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


INDEX_LINE_CAP = 150


def file_lines(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.read().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def index_size_report(claude_path, agents_path):
    """(message, over_cap) for AGENTS.md; None when AGENTS.md cannot be read.

    AGENTS.md is a generated header followed by CLAUDE.md verbatim, so the 150-line
    cap is judged on the body, delimited from the tail: the last len(CLAUDE.md) lines
    must be CLAUDE.md. Delimiting from the first matching line mis-took a header line
    for the body whenever CLAUDE.md opened with a blank line.
    """
    try:
        agent_lines = file_lines(agents_path)
    except OSError:
        return None
    try:
        claude_lines = file_lines(claude_path)
    except OSError:
        claude_lines = []
    body = len(claude_lines)
    if not body or agent_lines[-body:] != claude_lines:
        return (f"AGENTS.md is {len(agent_lines)} lines; the CLAUDE.md body could not be "
                "delimited (CLAUDE.md missing, or AGENTS.md does not end with it) — "
                "regenerate the mirror with the flash drive's scripts/sync_codex_workspace.py"), True
    header = len(agent_lines) - body
    message = (f"AGENTS.md is {len(agent_lines)} lines "
               f"(CLAUDE.md body {body} after a {header}-line generated header)")
    if body > INDEX_LINE_CAP:
        return (message + f" — the CLAUDE.md body is over the {INDEX_LINE_CAP}-line "
                f"cap by {body - INDEX_LINE_CAP}"), True
    return message, False


def main():
    failures = []
    warnings = []

    def warn(message):
        print("WARN " + message)
        warnings.append(message)

    def check(condition, ok, bad):
        print(("PASS " if condition else "FAIL ") + (ok if condition else bad))
        if not condition:
            failures.append(bad)

    claude = os.path.join(WORKSPACE_ROOT, "CLAUDE.md")
    agents = os.path.join(WORKSPACE_ROOT, "AGENTS.md")
    check(os.path.isfile(agents) and os.path.isfile(claude),
          "AGENTS.md and CLAUDE.md are present",
          "AGENTS.md/CLAUDE.md compatibility indexes are incomplete")
    size = index_size_report(claude, agents)
    if size:
        message, over = size
        if over:
            warn(message)
        else:
            print("PASS " + message)

    skill_root = os.path.join(WORKSPACE_ROOT, ".agents", "skills")
    claude_skill_root = os.path.join(WORKSPACE_ROOT, ".claude", "skills")
    source_skills = {name for name in os.listdir(claude_skill_root)
                     if os.path.isfile(os.path.join(claude_skill_root, name, "SKILL.md"))} \
                    if os.path.isdir(claude_skill_root) else set()
    codex_skills = {name for name in os.listdir(skill_root)
                    if os.path.isfile(os.path.join(skill_root, name, "SKILL.md"))} \
                   if os.path.isdir(skill_root) else set()
    check(source_skills == codex_skills and bool(source_skills),
          f"Codex skill mirror has all {len(source_skills)} installed skills",
          f"Codex skill mirror mismatch: missing={sorted(source_skills-codex_skills)}, extra={sorted(codex_skills-source_skills)}")

    codex_agents = os.path.join(WORKSPACE_ROOT, ".codex", "agents")
    profiles = sorted(name for name in os.listdir(codex_agents) if name.endswith(".toml")) \
               if os.path.isdir(codex_agents) else []
    check(bool(profiles), f"Codex custom agents present ({', '.join(profiles)})",
          "no Codex custom agents under .codex/agents")

    leftovers = []
    for root in (os.path.join(WORKSPACE_ROOT, ".agents"),
                 os.path.join(WORKSPACE_ROOT, ".codex"), agents):
        paths = []
        if os.path.isdir(root):
            paths = [os.path.join(base, name) for base, _, names in os.walk(root) for name in names]
        elif os.path.isfile(root):
            paths = [root]
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    text = handle.read()
                if TOKEN.search(text):
                    leftovers.append(os.path.relpath(path, WORKSPACE_ROOT))
            except OSError:
                pass
    check(not leftovers, "no unsubstituted parameters in the Codex layer",
          "unsubstituted parameters in: " + ", ".join(leftovers))

    # The set comparison above only sees skills added or removed. An edit in place
    # — a new rule in a SKILL.md or in CLAUDE.md — leaves the Codex half serving the
    # superseded policy. The generator records what it was generated from, by
    # content; mtimes were no signal: a byte-identical rewrite or a fresh clone
    # made the layer look stale, and regenerating could not clear it.
    changed = stale_sources(WORKSPACE_ROOT)
    check(not changed,
          "Codex layer matches the .claude sources it was generated from",
          "Codex layer is stale (regenerate with the flash drive's "
          "scripts/sync_codex_workspace.py): " + ", ".join(changed))

    config = load_json(PROJECT_HOOKS)
    command, matcher = hook_registration(config)
    prefix = effective_prefix(TRACKER_MCP_PREFIX)
    check(bool(command), "git guard registered in project .codex/hooks.json",
          "git guard is not registered for Codex; regenerate with the flash drive's "
          "scripts/sync_codex_workspace.py")
    if command:
        argv = split_command(command)

        def probe(git_command):
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": git_command},
                                  "cwd": WORKSPACE_ROOT, "permission_mode": "default"})
            code, failure = fire(argv, payload)
            return failure or code

        invariant_results = [(git_command, probe(git_command)) for git_command in
                             ("git commit -m doctor-probe", "git push --force")]
        check(all(code == 2 for _, code in invariant_results),
              "Codex hook contract live-fired: commit and destructive push blocked",
              "Codex hook did not block: " +
              ", ".join(f"{cmd}={code}" for cmd, code in invariant_results))

        push_policy = installed_push_policy()
        if push_policy == "auto":
            protection = recorded_branch_protection()
            check(bool(protection),
                  f"Codex PUSH_POLICY=auto code-host gate on record: {protection}"
                  if protection else "",
                  f'PUSH_POLICY=auto but the SETUP-PLAN does not record "{BRANCH_PROTECTION_ROW}"')
        expected = 0 if push_policy == "auto" else 2
        publication_results = [(git_command, probe(git_command)) for git_command in
                               ("git push", "gh pr create --fill")]
        check(all(code == expected for _, code in publication_results),
              f"Codex publication contract matches PUSH_POLICY={push_policy}",
              f"Codex publication contract disagrees with PUSH_POLICY={push_policy}: " +
              ", ".join(f"{cmd}={code}, expected {expected}"
                        for cmd, code in publication_results))

        problem = matcher_problem(matcher, prefix)
        check(problem is None,
              f'Codex hook matcher "{matcher}" fits the tracker setting',
              f"{problem}; regenerate with the flash drive's scripts/sync_codex_workspace.py")

        if not prefix:
            check(True, "TRACKER_MCP_PREFIX=none — no tracker MCP expected; "
                        "Codex MCP probes skipped", "")
        else:
            def mcp_probe(tool):
                payload = json.dumps({"tool_name": prefix + tool, "tool_input": {},
                                      "cwd": WORKSPACE_ROOT, "permission_mode": "default"})
                code, failure = fire(argv, payload)
                return failure or code

            write_code = mcp_probe("createDoctorProbe")
            check(write_code == 2,
                  "Codex tracker/wiki write tool is blocked by the hook",
                  f"Codex MCP write probe returned {write_code}, expected blocking exit 2")
            tracker_policy = installed_tracker_policy()
            read_expected = 2 if tracker_policy == "block-all" else 0
            read_code = mcp_probe("getDoctorProbe")
            check(read_code == read_expected,
                  f"Codex tracker read tool matches TRACKER_MCP_POLICY={tracker_policy}",
                  f"Codex MCP read probe returned {read_code} under "
                  f"TRACKER_MCP_POLICY={tracker_policy}, expected {read_expected}")

    codex = shutil.which("codex")
    check(bool(codex), "Codex CLI is available", "Codex CLI is not on PATH")
    if codex:
        result = subprocess.run([codex, "doctor", "--json"], cwd=WORKSPACE_ROOT,
                                capture_output=True, text=True, timeout=60)
        check(result.returncode == 0, "codex doctor passed",
              "codex doctor failed; run `codex doctor --summary` for the redacted report")

    print(f"\n{len(failures)} Codex failure(s) · {len(warnings)} warning(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
