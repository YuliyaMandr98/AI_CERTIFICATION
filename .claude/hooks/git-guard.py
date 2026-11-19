#!/usr/bin/env python3
"""Guards git from under the agent inside the workspace.

Three independent rules — two PreToolUse on Bash, one on Codex tracker tool calls
— all fail-closed *within this
script*: on any internal error — unreadable stdin, a regex that blows up, an
unresolvable path — it returns 2 and blocks with a message rather than staying
silent. A critical prohibition has to be duplicated by mechanics, and a guard that
fails open is worse than no guard.

What that promise does NOT cover, because it cannot: the paths where this script
never runs at all. Claude Code blocks on exit code 2 and treats every other
non-zero code as a non-blocking error, so a missing interpreter, a stub
interpreter, a moved workspace or a backslash in a substituted path all mean the
command proceeds with nothing said. Registration is therefore never proof — the
doctor live-fires this hook and probes the exit-code contract on every run:

1. Commands that are the human's to run are blocked anywhere inside the
   workspace, including the personal repo at the root: publication (push, and
   opening a PR/MR through the code-host CLI), destruction (reset --hard /
   clean -f / branch -D / checkout . / restore . / push --force / push --delete)
   and commits. Rationale: "push is a human action", "never destroy work" and
   "a commit happens only when the human asks" are prompt rules; the hook is
   the mechanical duplicate. Push is blocked at the root too: that repo has no
   remote, so nothing is lost, and the data/ docs in it describe client code —
   it must never leave the machine by an agent's hand.

   Two of these are policies the human sets at install (COMMIT_POLICY and
   PUSH_POLICY below): under "on-request" the plain commit, the plain push and
   the PR/MR creation are handed to the host's permission prompt instead of
   being blocked here; PUSH_POLICY also knows "auto", where the push and the
   PR/MR creation pass with no prompt at all and the code host's branch
   protection is the only gate left. Destructive pushes (--force, --delete, a
   `:ref` deletion refspec, --mirror) are NOT part of either: they rewrite or
   erase history on the remote and stay blocked under every policy. Codex
   cannot express the per-command approval required by "on-request", so it
   keeps that value mechanically blocked. It does honor "auto": that value was
   chosen at install for the workspace, needs no prompt by definition, and uses
   the same recorded code-host gate as Claude.

   `git add` is deliberately NOT blocked. Staging is how work is handed over
   for review, and rule 2 reads the index; taking it away costs more than it
   buys. The commit is the gate, not the staging.

2. Personal AI config files (.claude/, .agents/, .codex/, CLAUDE.md, AGENTS.md,
   .mcp.json, .ai/)
   are blocked from entering client git repos under the workspace. Commits to
   the personal repo at the root are untouched: the condition
   top.startswith(root + os.sep) is true only for repos strictly BELOW it.

3. Tracker/wiki writes are blocked on the Codex path only (--runtime codex).
   Claude expresses the same policy as a deny-list in settings.local.json, where
   an unlisted tool still reaches a permission prompt; behind this hook Codex has
   no prompt to fall back on, so the classification is closed — a tool is allowed
   only when a read verb is recognised in its name (READ_MCP_VERBS) and no write
   verb is (WRITE_MCP_VERBS), and anything unrecognised blocks. TRACKER_MCP_POLICY
   "block-all" closes the reads too; TRACKER_MCP_PREFIX "none" turns the rule off.
   Anchoring on the head of the name is not enough: a server that names tools
   jira_create_issue / confluence_update_page puts its namespace first, so the whole
   name is scanned.

Rules 1 and 2 classify a repo by its shared .git (`--git-common-dir`), not only by
the path of the checkout. A linked worktree has a pointer file for .git and can
be created anywhere; judged by path alone, a worktree of a client repo placed
outside the workspace would be "another project" and both rules would stand
aside. The worktree skill keeps worktrees at <workspace>/worktrees/, but the
guard does not rely on that.

Rule 1 scans commands, not documents: the body of a heredoc redirected into a
file (`cat > tasks/K/mr.md <<'EOF' ... EOF`) is blanked before matching, because a
draft that TELLS the human to push is data. Every other heredoc body stays in
scope — `cat <<EOF | bash` and `bash <<EOF` are real bypasses — so the writer
allowlist is two commands wide and closed by default.

A human running the same command in their own terminal is not affected, and
should not be — the escape hatch is deliberate.
"""
import argparse, json, re, subprocess, sys, os

# ===========================================================================
# CONFIG — project-specific values. Fill these in when installing the kit.
# Everything below the END CONFIG line is framework mechanics: the fail-closed
# behavior, the -C resolution, and the HEAD-based exception must NOT be
# softened when adapting this file to a new project.
# ===========================================================================

# Absolute path of the workspace root (the directory that holds the client
# repos and the personal layer). No trailing slash.
WORKSPACE_PATH = "/Users/oadmin/PROJECTS/FINCA/qa-api-tests-ai-delegation"

# Short human-readable workspace name, used in block messages.
WORKSPACE_NAME = "qa-cert-wrapper"

# Commit policy, chosen by the human at install time (interview -> SETUP-PLAN):
#   "never"      — the human always commits; the agent's ceiling is to ask or remind.
#   "on-request" — the agent may commit only when the human asks in that session.
#                  The per-commit approval is the permission prompt, so this value is
#                  only honest while prompts actually prompt: `git commit` belongs in
#                  the `ask` bucket and the doctor FAILs when defaultMode auto-approves.
# Any other value — unsubstituted, mistyped, half-edited — reads as "never". A typo
# must not open the gate.
COMMIT_POLICY = "never"

# Push policy, chosen the same way (interview -> SETUP-PLAN), three values:
#   "never"      — publishing is the human's: the agent writes tasks/<KEY>/mr.md and hands
#                  over. `git push` and `gh pr create` / `glab mr create` are blocked here.
#   "on-request" — the agent may push and open a PR/MR, only when the human asks in that
#                  session. The per-action approval is the permission prompt (`git push`
#                  and the PR-create commands sit in the `ask` bucket), so the doctor FAILs
#                  when defaultMode auto-approves.
#   "auto"       — the agent pushes and opens PR/MRs as part of the work, no prompt (the
#                  same commands sit in `allow`). The only gate left is the code host's
#                  branch protection, which this hook cannot see: the doctor FAILs an
#                  "auto" build whose SETUP-PLAN does not record what protects the
#                  default branch. For engineers who open many small PRs a day against a
#                  protected branch; nowhere else.
# Destructive pushes (--force, --delete, `:ref`, --mirror) ignore this value: blocked always.
# Any other value — unsubstituted, mistyped, half-edited — reads as "never".
PUSH_POLICY = "never"

# MCP prefix copied from the live tool names during onboarding. Claude enforces
# the write deny-list in settings.local.json; Codex routes the same tools through
# this hook because its project policy is expressed mechanically here.
TRACKER_MCP_PREFIX = "none"

# Tracker policy for the Codex path, two values:
#   "drafts-only" — a tracker tool whose name carries a read verb passes, everything else
#                   blocks (the classification below): the agent reads, a human publishes.
#   "block-all"   — every tool under TRACKER_MCP_PREFIX blocks, reads included, for
#                   workspaces where the agent must not touch the tracker at all.
# Any other value — unsubstituted, mistyped, half-edited — reads as "drafts-only": the
# strict direction would silently BLOCK the pre-flight read every route starts with, and
# a block with no visible cause is worse than the open side of a read-only classification.
# Codex path only; Claude enforces the same choice through its deny bucket.
TRACKER_MCP_POLICY = "drafts-only"

# Personal AI config files that must never enter a client repo.
# Extend if the project uses other personal tooling files.
FORBIDDEN_AI_FILE_PATTERN = (
    r"(^|/)(\.claude(/|$)|\.agents(/|$)|\.codex(/|$)|CLAUDE\.md$|"
    r"CLAUDE\.local\.md$|AGENTS\.md$|\.mcp\.json$|\.ai/)"
)

# ===========================================================================
# END CONFIG
# ===========================================================================

FORBIDDEN = re.compile(FORBIDDEN_AI_FILE_PATTERN)
# Tracker/wiki tool classification, used only on the Codex path (_check_mcp_write).
# Claude gets this policy from the settings.local.json deny-list, where a tool that
# is on neither list still reaches a permission prompt. Behind this hook Codex has
# no such prompt, so the classification is CLOSED: a call is allowed only when a
# read verb is recognised in its name, and anything unrecognised blocks.
READ_MCP_VERBS = frozenset((
    "get", "list", "search", "find", "fetch", "read", "view", "describe",
    "lookup", "query", "show", "count", "download", "export",
))
# Write verbs are kept explicit so a blocked call can say why; an unrecognised
# name blocks on the closed rule above, not on this list.
WRITE_MCP_VERBS = frozenset((
    "create", "update", "delete", "edit", "add", "transition", "move", "archive",
    "remove", "post", "set", "assign", "upload", "attach", "publish",
    "send", "comment", "clone", "write", "put", "patch", "rename", "label",
    "watch", "vote", "start", "close", "rank", "restore", "copy",
    "import", "merge", "apply", "change", "convert", "submit", "approve",
    "reject", "share", "invite", "revert", "mark", "reindex",
))
# Nouns that look like verbs (link types, bulk reads, audit logs) are deliberately
# NOT write verbs: with "any write verb blocks" they would turn reads such as
# jira_link_types_get or bulkGet into false blocks. A name that only has such a
# noun still blocks on the closed rule when no read verb is present.
# Exact operation names that are reads although a write verb appears in them.
READ_MCP_TOOLS = frozenset((
    "getCreateMeta",  # Jira create-metadata: describes the create form, creates nothing
    "getConfluenceCommentChildren",  # official Atlassian server: reads a comment thread
))
# Splits both naming schemes into words: camelCase (createJiraIssue) and
# snake_case with a server namespace in front (jira_create_issue).
MCP_WORD_SPLIT = re.compile(
    r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def _workspace_root() -> str:
    """Resolved workspace root, read at call time (tests override WORKSPACE_PATH)."""
    return os.path.realpath(os.path.expanduser(WORKSPACE_PATH))


# (pattern, what it matched, what to do instead)
HUMAN_ONLY = (
    # Destructive pushes come first so that under PUSH_POLICY=on-request a force-push
    # still meets this rule before the plain-push rule stands aside. `--force-with-lease`
    # is the safe form and is deliberately NOT matched (`--force(?=\s|$)`); a short-flag
    # cluster is matched when it carries f or d (`-f`, `-fu`, `-d`); `:ref` is the
    # deletion refspec (`HEAD:main` has no whitespace before the colon and passes).
    (re.compile(r"\bgit\b[^\n]*?\bpush\b[^\n]*?(?:^|\s)"
                r"(?:--force(?=\s|$)|--delete\b|--mirror\b|-[A-Za-z]*[fd][A-Za-z]*(?=\s|$)|:\S)"),
     "git push --force / --delete",
     "rewriting or deleting remote history is not the agent's call under any policy: "
     "push a new commit instead, or hand the command to the human"),
    (re.compile(r"\bgit\b[^\n]*?\bpush\b"),
     "git push",
     "publishing is a human action under this workspace's PUSH_POLICY: finish the work, "
     "write tasks/<KEY>/mr.md, and ask the human to push"),
    # The code-host CLI opening the MR is the same publication as the push behind it.
    (re.compile(r"(?:^|[\s;&|(`])(?:gh\s+pr|glab\s+mr)\s+create\b"),
     "PR/MR create",
     "opening the PR/MR is publication: write tasks/<KEY>/mr.md (What / Why / How to "
     "test) and hand it to the human"),
    # `commit` has to be the subcommand, not any word after `git` — otherwise
    # `git log --grep=commit` reads as a commit.
    (re.compile(r"\bgit\b(?:\s+-\S+(?:\s+(?!commit\b)\S+)?)*\s+commit\b"),
     "git commit",
     "a commit happens only when the human asks for one in this session: leave the "
     "work staged, then either ask whether to commit or remind the human that it is "
     "waiting — never commit on your own initiative"),
    (re.compile(r"\bgit\b[^\n]*?\breset\b[^\n]*?(?:^|\s)--hard\b"),
     "git reset --hard",
     "this discards uncommitted work irreversibly: use `git stash`, or `git reset` "
     "without --hard, or ask the human"),
    (re.compile(r"\bgit\b[^\n]*?\bclean\b[^\n]*?(?:^|\s)(?:-\w*f|--force)"),
     "git clean -f",
     "this deletes untracked files irreversibly: list them with `git clean -n` "
     "and let the human decide"),
    (re.compile(r"\bgit\b[^\n]*?\bbranch\b[^\n]*?(?:^|\s)(?:-D\b|--delete\s+--force\b|-d\s+--force\b|--force\s+--delete\b)"),
     "git branch -D",
     "force-deleting a branch can drop unmerged commits: use `git branch -d` "
     "(safe) or ask the human"),
    (re.compile(r"\bgit\b[^\n]*?\bcheckout\b[^\n]*?(?:^|\s)(?:--\s+)?\.(?:\s|$)"),
     "git checkout .",
     "this wipes every uncommitted change in the tree: revert the specific files "
     "you touched by path"),
    (re.compile(r"\bgit\b[^\n]*?\brestore\b[^\n]*?(?:^|\s)(?:--\s+)?\.(?:\s|$)"),
     "git restore .",
     "this wipes every uncommitted change in the tree: restore the specific files "
     "you touched by path"),
    (re.compile(r"\bgit\b[^\n]*?\bworktree\b[^\n]*?\bremove\b[^\n]*?(?:^|\s)(?:-f|--force)\b"),
     "git worktree remove --force",
     "this deletes a checkout together with its uncommitted work: run `git worktree "
     "remove` without --force (it refuses while the tree is dirty, which is the "
     "answer) or hand it to the human"),
)

SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
DASH_C = re.compile(r"\bgit\b\s+(?:-\S+\s+)*?-C\s+(\"[^\"]+\"|'[^']+'|\S+)")

# Heredoc whose body is written straight into a file: `cat > f <<'EOF' ... EOF`,
# `tee f <<EOF ... EOF`. The body is prose, so it is blanked before matching.
# Anything else keeps its body: an interpreter heredoc (`bash <<EOF`, `python3 -
# <<PY`) and a piped one (`cat <<EOF | bash`) execute what they carry.
HEREDOC = re.compile(
    r"(?P<head>[^\n]*?)<<-?[ \t]*(?P<q>['\"]?)(?P<tag>[A-Za-z_]\w*)(?P=q)"
    r"(?P<rest>[^\n]*)\n(?P<body>.*?)\n[ \t]*(?P=tag)[ \t]*(?=\n|$)",
    re.S)
WRITER_HEAD = re.compile(r"(?:^|[;&|]|\$\()[ \t]*(?:cat|tee)\b[^|\n]*$")


def _strip_writer_heredocs(cmd: str) -> str:
    """Blank the bodies of file-writing heredocs; leave every other body alone."""
    def repl(m):
        if "|" in m.group("rest") or not WRITER_HEAD.search(m.group("head")):
            return m.group(0)
        start, end = m.span("body")
        base = m.start()
        return m.group(0)[: start - base] + m.group(0)[end - base :]
    try:
        return HEREDOC.sub(repl, cmd)
    except Exception:
        return cmd  # fail-closed: scan the raw command rather than skip the check


def main(argv=None) -> int:
    """`argv=None` reads sys.argv, as the registered hook does. Tests pass their own
    list: calling main() in-process would otherwise hand argparse the test runner's
    arguments, and argparse exits on the unknown ones before stdin is ever read."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime", choices=("claude", "codex"), default="claude")
    args = parser.parse_args(argv)
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("git-guard: could not read input — blocking just in case", file=sys.stderr)
        return 2  # fail-closed
    return run(data, runtime=args.runtime)


def run(data: dict, runtime: str = "claude") -> int:
    """Hook body, separated from stdin handling so tests can call it directly."""
    if data.get("tool_name") != "Bash":
        return _check_mcp_write(data) if runtime == "codex" else 0
    cmd = (data.get("tool_input") or {}).get("command", "")
    cwd = data.get("cwd") or os.getcwd()
    scanned = _strip_writer_heredocs(cmd)

    rc = _check_human_only(scanned, cwd, runtime)
    if rc:
        return rc
    return _check_ai_files(scanned, cwd)


# --- rule 1: git commands that are the human's to run ---------------------

# Which rule-1 labels a policy can hand to the permission prompt. Everything not
# listed here is blocked regardless of how the CONFIG reads.
POLICY_GATES = {
    "git commit": lambda runtime: _commit_is_gated(runtime),
    "git push": lambda runtime: _push_is_gated(runtime),
    "PR/MR create": lambda runtime: _push_is_gated(runtime),
}


def _check_human_only(cmd: str, cwd: str, runtime: str = "claude") -> int:
    for segment in SEGMENT_SPLIT.split(cmd):
        if not re.search(r"\b(?:git|gh|glab)\b", segment):
            continue
        for pattern, label, alternative in HUMAN_ONLY:
            if not pattern.search(segment):
                continue
            gated = POLICY_GATES.get(label)
            if gated is not None and not gated(runtime):
                continue  # policy "on-request": the permission prompt is the gate
            if not _in_workspace(segment, cwd):
                continue  # this workspace only: stay out of other projects
            print(f"git-guard: BLOCKED — {label} is not available to the agent "
                  f"inside the {WORKSPACE_NAME} workspace. {alternative}. If it really has "
                  f"to happen, the human runs it in their own terminal (the hook does not "
                  f"apply there).",
                  file=sys.stderr)
            return 2
    return 0


def _commit_is_gated(runtime: str = "claude") -> bool:
    """Codex always blocks; Claude may delegate an explicit commit to its ask prompt."""
    if runtime == "codex":
        return True
    return (COMMIT_POLICY or "").strip().lower() != "on-request"


def _mcp_verb(operation: str):
    """Classify a tracker tool name as ("read"|"write", verb), or (None, "").

    The whole name is scanned, not just its head: tracker servers name tools
    verb-first (createJiraIssue) or namespace-first (jira_create_issue), and
    anchoring on the head let every namespace-first write through. A write verb
    ANYWHERE decides, before any read verb is looked at: "first verb wins" let
    markAsRead and reindexSearch through, because their read word came after a
    write one. Only READ_MCP_TOOLS overrides that, by exact name.
    """
    if operation in READ_MCP_TOOLS:
        return "read", operation
    words = [word.lower() for word in MCP_WORD_SPLIT.split(operation) if word]
    for word in words:
        if word in WRITE_MCP_VERBS:
            return "write", word
    for word in words:
        if word in READ_MCP_VERBS:
            return "read", word
    return None, ""


def _push_is_gated(runtime: str = "claude") -> bool:
    """Publication policy for one host.

    Claude can hand an explicit push or PR/MR creation to its ask prompt under
    on-request. Codex has no equivalent per-command bucket, so it keeps that value
    blocked. Both hosts honor auto, whose install-time choice deliberately removes
    the prompt. Destructive pushes never reach this helper.
    """
    policy = (PUSH_POLICY or "").strip().lower()
    if runtime == "codex":
        return policy != "auto"
    return policy not in ("on-request", "auto")


def _tracker_prefix() -> str:
    """Effective tracker prefix; "" means the workspace has no tracker MCP."""
    prefix = (TRACKER_MCP_PREFIX or "").strip()
    if not prefix or prefix.lower() == "none" or "{{" in prefix:
        return ""
    return prefix


def _check_mcp_write(data: dict) -> int:
    """Block tracker/wiki mutations in Codex; recognised reads pass through."""
    name = str(data.get("tool_name") or "")
    prefix = _tracker_prefix()
    if not prefix or not name.startswith(prefix):
        return 0
    if (TRACKER_MCP_POLICY or "").strip().lower() == "block-all":
        print(
            f"git-guard: BLOCKED — {name}: the tracker is off-limits to the agent in "
            "this workspace by policy (TRACKER_MCP_POLICY=block-all), reads included.",
            file=sys.stderr,
        )
        return 2
    operation = name[len(prefix):].lstrip("_-")
    kind, verb = _mcp_verb(operation)
    if kind == "read":
        return 0
    if kind == "write":
        why = f"'{verb}' marks it as a tracker/wiki write"
    else:
        why = ("no read verb is recognised in its name, and this hook is the only "
               "gate on the Codex side, so it counts as a write")
    print(
        f"git-guard: BLOCKED — {name}: {why}. The agent may prepare a draft, but a "
        "human publishes it. A read blocked by mistake belongs in READ_MCP_VERBS, "
        "or by exact name in READ_MCP_TOOLS, in this hook.",
        file=sys.stderr,
    )
    return 2


def _in_workspace(segment: str, cwd: str) -> bool:
    """True if the command targets a repo at or below the workspace root.

    `git -C <path>` wins over cwd — otherwise it is a free bypass. An
    unresolvable -C path inside the workspace counts as in scope (fail-closed).
    """
    m = DASH_C.search(segment)
    if m:
        target = m.group(1).strip("\"'")
        target = os.path.expanduser(target)
        if not os.path.isabs(target):
            target = os.path.join(cwd, target)
        return _under_root(target)
    return _under_root(cwd)


def _under_root(path: str) -> bool:
    root = _workspace_root()
    try:
        p = os.path.realpath(path)
    except Exception:
        return True  # fail-closed
    if p == root or p.startswith(root + os.sep):
        return True
    # The path is outside the workspace — but is the REPO? A worktree of a client
    # repo can be checked out anywhere (`git worktree add /tmp/x`), its .git is a
    # pointer file, and a session that `cd`s into it would otherwise be "some
    # other project" to this rule. The common dir does not move with the checkout.
    common = _git_common_dir(p)
    return common is not None and common.startswith(root + os.sep)


def _git_common_dir(base: str):
    """Realpath of the shared .git of the repo at `base`; None when base is not a repo.

    For a plain checkout this is `<repo>/.git`; for a linked worktree it is the
    ORIGINAL repo's .git, wherever the worktree itself lives. Classifying by it is
    what keeps a worktree of a client repo a client repo. A git failure returns
    None rather than blocking: the path check has already answered, and this probe
    only widens scope — the hook is registered globally and must not stall every
    other project on the machine when git is slow.
    """
    try:
        r = subprocess.run(["git", "-C", base, "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    common = r.stdout.strip()
    if r.returncode != 0 or not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(base, common)
    return os.path.realpath(common)


# --- rule 2: personal AI files in client repos ----------------------------

def _check_ai_files(cmd: str, cwd: str) -> int:
    if not re.search(r"\bgit\b.*\b(add|commit)\b", cmd):
        return 0
    # Find the git repo the command targets: `git -C <path>` wins over cwd here
    # exactly as in rule 1 — otherwise `git -C <client-repo> add ...` run from
    # the workspace root resolves to the personal root repo and slips through.
    base = cwd
    m = DASH_C.search(cmd)
    if m:
        target = os.path.expanduser(m.group(1).strip("\"'"))
        base = target if os.path.isabs(target) else os.path.join(cwd, target)
    try:
        top = subprocess.run(["git", "-C", base, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return 0
    if not top:
        return 0
    root = _workspace_root()
    top_real = os.path.realpath(top)
    # A client repo is a checkout strictly below the workspace root — or a worktree
    # whose shared .git is, wherever that worktree was created. The root's own
    # .git is excluded: the personal repo is supposed to track these files.
    common = _git_common_dir(top_real)
    is_client = top_real.startswith(root + os.sep) or (
        common is not None
        and common.startswith(root + os.sep)
        and common != os.path.realpath(os.path.join(root, ".git")))
    if not is_client:
        return 0  # stay out of anything that is not a client repo
    r = subprocess.run(["git", "-C", top, "diff", "--cached", "--name-only"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        # repo without an initial commit: `diff --cached` has no HEAD to compare against
        r = subprocess.run(["git", "-C", top, "ls-files", "--cached"],
                           capture_output=True, text=True, timeout=5)
    staged = r.stdout.splitlines()
    # for `git add`, also inspect the command arguments
    candidates = staged + re.findall(r"[\w./\\-]+", cmd)
    hits = sorted({p for p in candidates if FORBIDDEN.search(p)})
    # exception: a team-tracked CLAUDE.md is already in the repo — edits to it are legal
    hits = [h for h in hits if not _committed(top, h)]
    if hits:
        print("git-guard: BLOCKED — personal AI files in a client repo: "
              + ", ".join(hits) + ". They belong in the personal workspace layer "
              "(workspace root or its .claude/).",
              file=sys.stderr)
        return 2
    return 0


def _committed(top: str, path: str) -> bool:
    """Is the path already in HEAD?

    Deliberately NOT `git ls-files`: that reads the index, so a file the agent
    has just staged would count as "already tracked" and exempt itself. The
    exception only covers files the team committed before us.
    """
    r = subprocess.run(["git", "-C", top, "cat-file", "-e", f"HEAD:{path}"],
                       capture_output=True, timeout=5)
    return r.returncode == 0


if __name__ == "__main__":
    sys.exit(main())
