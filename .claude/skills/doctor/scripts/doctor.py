#!/usr/bin/env python3
"""Doctor: self-test of this workspace's Claude Code wiring. Run: python3 .claude/skills/doctor/scripts/doctor.py

Answers one question in ~30 seconds: are the safety mechanisms still connected?
It fires the real hooks the way Claude Code fires them (a sandbox git repo, JSON
on stdin, the command string read out of the live settings) instead of trusting
that a config file means what it says. The incident that motivated it: the deny
list named an MCP server that did not exist, so the "drafts only" guarantee had
nothing behind it for a month and nobody noticed.

It fixes NOTHING. Every FAIL prints the exact command to run by hand — several of
them (OAuth) are not available to an agent at all, and a safety net that rewrites
itself is worse than a broken one.

Exit code: 1 if anything FAILed, 0 otherwise (WARN does not fail the run).
"""
import importlib.util, json, os, re, shutil, stat, subprocess, sys, tempfile

# =============================================================================
# CONFIG — fill every UPPER_SNAKE placeholder token when installing this kit into a workspace.
# Everything below this block is workspace-agnostic logic; edit only if the
# workspace genuinely lacks a mechanism (then delete its check, don't stub it).
# =============================================================================

# Absolute path of the outstaff workspace root (e.g. C:/Users/you/Code/Acme).
WORKSPACE_ROOT = os.path.realpath(os.path.expanduser("/Users/oadmin/PROJECTS/FINCA/qa-api-tests-ai-delegation"))

# Human-readable workspace name (e.g. Acme), used in report messages.
WORKSPACE_NAME = "qa-cert-wrapper"

# Short slug used in artifact and sandbox names (skills install under their
# kit names, unprefixed; the hook is registered in the workspace's own
# settings.local.json with absolute paths).
PROJECT_PREFIX = "qa-cert"

# Issue tracker (e.g. Jira) and its MCP tool prefix (e.g. mcp__atlassian__).
# The server name is derived from the prefix for `claude mcp list` matching.
TRACKER_NAME = "номера в названиях тестов (без live-трекера)"
TRACKER_MCP_PREFIX = "none"

# Fallback only. Which MCP tool is a write is decided by the installed git-guard
# (READ_MCP_VERBS / WRITE_MCP_VERBS / READ_MCP_TOOLS) — the list the Codex hook
# enforces — so the two installed files cannot disagree. These head-anchored verbs
# are used only when the guard cannot be loaded or predates that classifier.
MUTATING_VERBS = ["create", "update", "delete", "edit", "add", "transition",
                  "move", "archive", "remove", "post", "set", "assign"]

# =============================================================================
# Derived paths and constants — no per-workspace values below this line.
# =============================================================================

GIT_GUARD_HOOK = "git-guard"      # PreToolUse/Bash hook basename (kit installs unprefixed)

NO_TRACKER_LINE = ("TRACKER_MCP_PREFIX=none — no tracker MCP expected; "
                   "tracker wiring checks skipped")


def effective_prefix(raw):
    """The tracker prefix as the guard reads it: empty, `none` in any case, or an
    unsubstituted `{{...}}` token all mean there is no tracker MCP in this workspace."""
    value = (raw or "").strip()
    if not value or value.lower() == "none" or "{{" in value:
        return ""
    return value


def server_name_of(prefix):
    return prefix.removeprefix("mcp__").rstrip("_")


TRACKER_SERVER_NAME = server_name_of(effective_prefix(TRACKER_MCP_PREFIX))


def expected_mcp_servers():
    """MCP servers the routes expect, checked by `claude mcp list` name. Built at check
    time from the current CONFIG, so a workspace with no tracker simply has no tracker
    entry. `level` is what a missing or unconnected server costs: FAIL stops the run,
    WARN only reports it. Several matching servers are a WARN at any level.
    `consequence` and `add_hint` finish the message and the runbook line."""
    prefix = effective_prefix(TRACKER_MCP_PREFIX)
    if not prefix:
        return []
    server = server_name_of(prefix)
    return [
        {"name": TRACKER_NAME, "level": "FAIL", "prefix": prefix,
         "consequence": f"the {TRACKER_NAME} routes cannot run pre-flight",
         "add_hint": f"claude mcp add --transport http {server} <server-url> "
                     f"&& /mcp   # OAuth is interactive, a human has to do it"},
    ]

GLOBAL_SETTINGS = os.path.expanduser("~/.claude/settings.json")
CLAUDE_JSON = os.path.expanduser("~/.claude.json")
LOCAL_SETTINGS = os.path.join(WORKSPACE_ROOT, ".claude", "settings.local.json")
GUARD_TESTS_BASENAME = "test_" + GIT_GUARD_HOOK.replace("-", "_") + ".py"
GUARD_TESTS = os.path.join(WORKSPACE_ROOT, ".claude", "hooks", GUARD_TESTS_BASENAME)
GUARD_SOURCE = os.path.join(WORKSPACE_ROOT, ".claude", "hooks", GIT_GUARD_HOOK + ".py")
# Built from __file__, not WORKSPACE_ROOT like GUARD_TESTS above: the doctor's own tests
# are its sibling on disk, so this keeps resolving even when WORKSPACE_PATH is wrong —
# exactly the situation the doctor exists to diagnose.
DOCTOR_TESTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "test_doctor.py")

SANDBOX = os.path.join(WORKSPACE_ROOT, ".doctor-sandbox")
OUTSIDE_SANDBOX = os.path.join(tempfile.gettempdir(), PROJECT_PREFIX + "-doctor-outside")

MUTATING = re.compile(r"^(" + "|".join(MUTATING_VERBS) + r")", re.IGNORECASE)

results = []   # (status, message, runbook)


def report(status, message, runbook=""):
    results.append((status, message, runbook))
    print(f"{status:<5} {message}")


def ok(msg):
    report("PASS", msg)


def fail(msg, runbook):
    report("FAIL", msg, runbook)


def warn(msg, runbook=""):
    report("WARN", msg, runbook)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sh(command, **kw):
    return subprocess.run(command, shell=isinstance(command, str), capture_output=True,
                          text=True, timeout=kw.pop("timeout", 30), **kw)


COMMAND_TOKEN = re.compile(r'''"([^"]*)"|'([^']*)'|(\S+)''')


def split_command(cmd):
    """Tokenise a registered hook command into argv.

    shlex is the obvious tool and the wrong one here: posix=True eats the backslashes
    in a Windows path, posix=False leaves the quotes inside the token. A hook command
    is just quoted-or-bare paths, so match them as that and nothing else.
    """
    return [next(g for g in m.groups() if g is not None)
            for m in COMMAND_TOKEN.finditer(cmd)]


def interpreter_identifies_itself(path):
    """Does this interpreter actually run? (None if it cannot even be attempted.)

    The Microsoft Store redirector answers to the name `python3` and opens the Store
    instead of running anything, so a registered hook can be present and dead. Never
    probe a path that looks like the redirector — asking it would launch the Store.
    """
    if "WindowsApps" in path or "AppInstallerPythonRedirector" in path:
        return False
    try:
        r = subprocess.run([path, "-c", "import sys; print(sys.version_info[0])"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "3"


# The values each policy can take besides "never" — the guard's own vocabulary.
POLICY_VALUES = {"COMMIT_POLICY": ("on-request",), "PUSH_POLICY": ("on-request", "auto"),
                 "TRACKER_MCP_POLICY": ("drafts-only", "block-all")}
RAW_POLICIES = ("TRACKER_MCP_POLICY",)


def installed_policy(name):
    """A CONFIG policy (COMMIT_POLICY, PUSH_POLICY) as the installed guard actually
    carries it, or None if unreadable — including a guard that predates the parameter.

    Read from the guard source, not from the SETUP-PLAN: the plan records what was
    decided, this reports what is running, and the gap between the two is the whole
    reason to check. Anything that is not exactly one of the parameter's opened values
    reads as never, matching the guard's own fail-closed parsing.
    """
    try:
        with open(GUARD_SOURCE, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"""^%s\s*=\s*["']([^"']*)["']""" % re.escape(name), text, re.M)
    if not m:
        return None
    value = m.group(1).strip().lower()
    if name in RAW_POLICIES:
        return value
    return value if value in POLICY_VALUES.get(name, ()) else "never"


def mcp_write_verb(operation):
    """The write verb in a tracker tool name, judged by the installed guard, or None.

    Loads the guard's own classifier so this doctor and the Codex hook share one
    verb list. A name the guard does not recognise is not reported here: on the
    Claude side an unlisted tool still reaches a permission prompt.
    """
    classify = None
    # The doctor writes nothing: importing would drop a __pycache__ beside the guard.
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("installed_git_guard", GUARD_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        classify = getattr(module, "_mcp_verb", None)
    except Exception:
        classify = None
    finally:
        sys.dont_write_bytecode = previous
    if classify:
        kind, verb = classify(operation)
        return verb if kind == "write" else None
    m = MUTATING.search(operation)
    return m.group(1).lower() if m else None


def installed_commit_policy():
    return installed_policy("COMMIT_POLICY")


def installed_push_policy():
    return installed_policy("PUSH_POLICY")


BRANCH_PROTECTION_ROW = "What protects the default branch"


def recorded_branch_protection():
    """The SETUP-PLAN §1 answer to "what protects the default branch", or None.

    None when no `*-SETUP-PLAN.md` sits at the workspace root, when the row is
    missing, or when it still carries the template's `<FILL: ...>`. PUSH_POLICY=auto
    hands the whole gate to the code host, so the doctor demands that the plan at
    least names what that gate is — it cannot verify the protection itself.
    """
    try:
        plans = sorted(n for n in os.listdir(WORKSPACE_ROOT) if n.endswith("-SETUP-PLAN.md"))
    except OSError:
        return None
    for name in plans:
        try:
            with open(os.path.join(WORKSPACE_ROOT, name), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        m = re.search(r"^\|\s*" + re.escape(BRANCH_PROTECTION_ROW) + r"\s*\|([^|\n]*)\|",
                      text, re.M)
        if not m:
            continue
        value = m.group(1).strip()
        if value and "<FILL" not in value and value.lower() not in ("nothing", "none", "-", "—"):
            return value
    return None


# --- section 1: hook registration ----------------------------------------

def _same_path(a, b):
    """Two spellings of one file.

    normcase folds case on Windows and is a no-op on POSIX; normpath folds separators,
    which matters because the onboarder substitutes every path with forward slashes,
    on every platform (SKILL.md step 7a) — these values land inside Python string
    literals, where a backslash is a SyntaxError, and a hook that cannot parse exits 1,
    which does not block, so the guard would fail open while looking installed. realpath
    is the second chance and never the first: it touches the filesystem and on Windows
    can hand back an extended-length or junction-resolved spelling, so a literal match is
    tried before it. That ordering means realpath can only ever add a match, never take
    one away.
    """
    def n(p):
        return os.path.normcase(os.path.normpath(p))
    if n(a) == n(b):
        return True
    return n(os.path.realpath(a)) == n(os.path.realpath(b))


def _is_this_workspaces_guard(cmd):
    """True for the registration that runs OUR guard, not some other workspace's.

    The kit installs hook filenames unprefixed on purpose and lets the absolute path in
    the registration say which workspace it belongs to (MANIFEST.md). Matching the
    basename throws that away — a copied workspace whose WORKSPACE_PATH was never
    re-substituted would read as registered while its hook points elsewhere.
    """
    return any(_same_path(tok, GUARD_SOURCE)
               for tok in split_command(cmd) if os.path.normcase(tok).endswith(".py"))


def registered_hook(settings, event, matches):
    """The command string Claude Code would run FOR THIS WORKSPACE, or None."""
    for entry in ((settings or {}).get("hooks", {}) or {}).get(event, []) or []:
        for hook in entry.get("hooks", []) or []:
            cmd = hook.get("command", "")
            if matches(cmd):
                return cmd
    return None


def foreign_guard_registrations(settings, event="PreToolUse"):
    """git-guard registrations in this settings object that do NOT resolve to this
    workspace's script — in the workspace file that is a copied or moved workspace whose
    WORKSPACE_PATH was never re-substituted; in ~/.claude/settings.json it is a line an
    earlier kit version wrote machine-wide."""
    found = []
    want = os.path.normcase(GIT_GUARD_HOOK + ".py")
    for entry in ((settings or {}).get("hooks", {}) or {}).get(event, []) or []:
        for hook in entry.get("hooks", []) or []:
            script = next((t for t in split_command(hook.get("command", ""))
                           if os.path.normcase(os.path.basename(t)) == want), None)
            if script and not _same_path(script, GUARD_SOURCE):
                found.append(script)
    return found


def check_registration(local, settings=None):
    """The guard is registered in the workspace's own .claude/settings.local.json and
    nowhere else. Project settings load only for a session started at the workspace
    root, which is where sessions start; a session inside a client repo runs without
    the layer, by the developer's own choice. Nothing of the build is machine-wide.
    Returns the command string to live-fire, or None."""
    name = f"{GIT_GUARD_HOOK} (PreToolUse/Bash)"
    where = ".claude/settings.local.json"
    runbook = (f"add the hooks entry from the kit's settings-workspace.json to {where} — an "
               f"ABSOLUTE interpreter path and the absolute, forward-slashed path to "
               f".claude/hooks/{GIT_GUARD_HOOK}.py")
    if local is None:
        fail(f"{LOCAL_SETTINGS} is missing or not valid JSON",
             f"restore it from the personal git: git checkout {where}")
        return None

    guard = registered_hook(local, "PreToolUse", _is_this_workspaces_guard)
    strangers = foreign_guard_registrations(local)
    if guard:
        argv = split_command(guard)
        interp = argv[0] if argv else ""
        script = next((t for t in argv if os.path.normcase(t).endswith(".py")), "")
        if script and not os.path.exists(script):
            fail(f"{name} is registered but points at a missing file: {script}",
                 f"re-substitute WORKSPACE_PATH in {where} (and in the hook and the doctor) "
                 f"— the workspace was moved or copied")
        elif "/" not in interp and os.sep not in interp:
            fail(f"{name} is registered against the bare interpreter name '{interp}' — "
                 f"that name can resolve to a stub, and a hook that cannot run exits "
                 f"non-2, which does NOT block: the guard would fail open",
                 f"substitute PYTHON_PATH with an absolute interpreter path in {where}")
        elif not interpreter_identifies_itself(interp):
            fail(f"{name}'s interpreter does not identify itself as Python 3: {interp}",
                 f"point the hook in {where} at a real Python 3 interpreter")
        else:
            ok(f"{name} registered in {where}, interpreter verified")
    elif strangers:
        fail(f"{name} is NOT registered for this workspace — the entry in {where} points "
             f"at {', '.join(strangers)}: a copied or moved workspace whose WORKSPACE_PATH "
             f"was never re-substituted",
             f"fix the script path in {where} to {GUARD_SOURCE}")
    else:
        fail(f"{name} is NOT registered in {where}", runbook)

    # An earlier kit version registered the guard machine-wide. From this workspace it now
    # fires twice; from every unrelated project a stale line errors on each Bash call.
    legacy = registered_hook(settings, "PreToolUse", lambda cmd: any(
        os.path.normcase(os.path.basename(t)) == os.path.normcase(GIT_GUARD_HOOK + ".py")
        for t in split_command(cmd)))
    if legacy:
        warn(f"a {GIT_GUARD_HOOK} is also registered machine-wide in ~/.claude/settings.json "
             f"(an earlier kit version put it there): {legacy}",
             "remove that hook entry from ~/.claude/settings.json by hand — the workspace "
             "registration above is the one that counts")
    return guard


# --- section 2: the guard actually fires ---------------------------------

def remove_tree(path, causes=None):
    """Remove a sandbox tree; True when the path is gone.

    Squeezr, 2026-10-19: git writes loose objects read-only, and on Windows rmtree
    cannot delete a read-only file — with errors swallowed the sandbox survived
    silently and the next run found the old repo. The handler clears the bit and
    retries once; a second failure ends the walk, the survivor is judged by the
    path, and the exception text goes to `causes` so a held-open file is not
    blamed on read-only objects.
    """
    def clear_and_retry(func, target, _error):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        kwargs = {"onexc": clear_and_retry}
    else:
        kwargs = {"onerror": clear_and_retry}
    try:
        shutil.rmtree(path, **kwargs)
    except OSError as exc:
        if causes is not None:
            causes.append(f"{type(exc).__name__}: {exc}")
    return not os.path.exists(path)


def remove_sandboxes():
    for path in (SANDBOX, OUTSIDE_SANDBOX):
        causes = []
        if not remove_tree(path, causes):
            detail = f" ({causes[0]})" if causes else ""
            fail(f"sandbox survived removal: {path}{detail}",
                 f"rm -rf {path}   # read-only git objects the doctor could not remove")


def make_sandbox_repo(path):
    os.makedirs(path, exist_ok=True)
    sh(["git", "init", "-q", path])
    sh(["git", "-C", path, "config", "user.email", "doctor@local"])
    sh(["git", "-C", path, "config", "user.name", "doctor"])
    sh(["git", "-C", path, "commit", "-q", "--allow-empty", "-m", "init"])
    return path


def fire(guard_cmd, command, cwd):
    # shell=False on purpose. With shell=True, Python routes through COMSPEC on
    # Windows — cmd.exe — while Claude Code runs hooks through Git Bash, so the
    # strongest check in this file would exercise a shell production never uses.
    # An argv list has no shell in it to disagree about, and it survives the spaces
    # in "C:/Program Files/...".
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run(split_command(guard_cmd), input=payload, capture_output=True,
                       text=True, cwd=cwd, timeout=30)
    return r.returncode


def check_guard_fires(guard_cmd):
    if not guard_cmd:
        fail("cannot live-fire the guard: it is not registered",
             "register it in .claude/settings.local.json (see the kit's settings-workspace.json)")
        return
    repo = make_sandbox_repo(os.path.join(SANDBOX, "client-repo"))
    # deliberately outside WORKSPACE_ROOT: the guard scopes itself to the workspace and
    # must keep its hands off everything else on the machine (`git -C` and absolute paths
    # reach other repos from a session that started here)
    outside = make_sandbox_repo(os.path.join(OUTSIDE_SANDBOX, "other-project"))

    os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
    with open(os.path.join(repo, ".claude", "settings.json"), "w", encoding="utf-8") as f:
        f.write("{}\n")
    sh(["git", "-C", repo, "add", "-f", ".claude/settings.json"])

    runbook = (f"python3 .claude/hooks/{GUARD_TESTS_BASENAME}   # find which rule broke, "
               f"then fix .claude/hooks/{GIT_GUARD_HOOK}.py")

    cases_blocked = [
        # `git add`, not `git commit`: since the commit gate landed, a commit is blocked
        # by rule 1 before rule 2 is reached, so probing with one would report a pass
        # while leaving the C2 mechanic — AI config entering a client repo — unverified.
        ("staged .claude/settings.json in a client repo (rule 2)",
         "git add .claude/settings.json", repo),
        # destructive pushes are outside every policy — they rewrite or erase history
        # on the remote, so they stay blocked even when the plain push is handed over
        ("git push --force", "git push --force", repo),
        ("git push --delete", "git push --delete origin some-branch", repo),
        ("git reset --hard", "git reset --hard HEAD~1", repo),
        ("git clean -fd", "git clean -fd", repo),
        ("git branch -D", "git branch -D some-branch", repo),
        ("git checkout .", "git checkout .", repo),
        # the heredoc exemption must not become a bypass: a body that can be
        # EXECUTED is still a command
        ("git reset --hard inside an interpreter heredoc",
         "bash <<'EOF'\ngit reset --hard\nEOF", repo),
    ]
    # Under COMMIT_POLICY=never the guard blocks commits outright; under on-request the
    # permission prompt is the gate, so the guard must NOT block them.
    commit_cases = [
        ("git commit", "git commit -m 'DOCTOR-1: add x'", repo),
        ("git commit -am", "git commit -am wip", repo),
        ("git commit behind a chained command", "lint && git commit -m x", repo),
        ("git commit inside an interpreter heredoc",
         "bash <<'EOF'\ngit commit -m x\nEOF", repo),
    ]
    if installed_commit_policy() != "on-request":
        cases_blocked += commit_cases
    # Same shape for publication. A guard that predates PUSH_POLICY has no PR-create
    # rule at all: the plain push is still blocked by it, but PR/MR creation is
    # prompt-only there — named as a WARN, not sprung on it as a FAIL.
    push_policy = installed_push_policy()
    push_cases = [
        ("git push", "git push origin HEAD", repo),
        ("git push -u", "git push -u origin doctor-probe", repo),
        ("git push inside an interpreter heredoc",
         "bash <<'EOF'\ngit push\nEOF", repo),
    ]
    pr_cases = [
        ("PR/MR create (gh)", "gh pr create --fill", repo),
        ("PR/MR create (glab)", "glab mr create --fill", repo),
        ("PR/MR create behind a chained command", "git push -u origin HEAD && gh pr create --fill", repo),
    ]
    if push_policy is None:
        cases_blocked += push_cases
        warn(f"the installed guard has no PUSH_POLICY — it predates the publish gate, so "
             f"PR/MR creation (`gh pr create` / `glab mr create`) is prompt-only here",
             "update .claude/hooks/git-guard.py from the kit (/kit-update from the flash drive)")
    elif push_policy == "never":
        cases_blocked += push_cases + pr_cases
    for label, command, cwd in cases_blocked:
        rc = fire(guard_cmd, command, cwd)
        if rc == 2:
            ok(f"guard blocks {label}")
        elif rc == 0:
            fail(f"guard ran and ALLOWED {label} — the rule is missing from the hook", runbook)
        else:
            # Claude Code blocks on exit 2 and treats every other non-zero code as a
            # non-blocking error, so this is the dangerous case: the hook is registered,
            # it fell over, and the command went through with nothing said.
            fail(f"guard FAILED OPEN on {label}: the hook exited {rc}, and only exit 2 "
                 f"blocks — the command would have proceeded silently",
                 f"run the registered command by hand and read its error: {guard_cmd}")

    sh(["git", "-C", repo, "reset", "-q"])
    with open(os.path.join(repo, "app.ts"), "w", encoding="utf-8") as f:
        f.write("export const x = 1\n")
    sh(["git", "-C", repo, "add", "app.ts"])
    # Staging and reading are the work; only the commit is gated. `git log --grep`
    # is here because a lazy commit pattern reads it as a commit.
    if installed_commit_policy() == "on-request":
        for label, command, cwd in commit_cases:
            if fire(guard_cmd, command, cwd) == 0:
                ok(f"guard lets {label} through (COMMIT_POLICY=on-request)")
            else:
                fail(f"guard blocks {label} while COMMIT_POLICY says on-request — the "
                     f"policy and the hook disagree", runbook)
    if push_policy in ("on-request", "auto"):
        for label, command, cwd in push_cases + pr_cases:
            if fire(guard_cmd, command, cwd) == 0:
                ok(f"guard lets {label} through (PUSH_POLICY={push_policy})")
            else:
                fail(f"guard blocks {label} while PUSH_POLICY says {push_policy} — the "
                     f"policy and the hook disagree", runbook)

    for label, command in (("git add", "git add app.ts"),
                           ("git status", "git status --short"),
                           ("git log --grep=commit", "git log --grep=commit"),
                           ("git push --force-with-lease is not a force-push",
                            "git push --force-with-lease origin HEAD")
                           if push_policy in ("on-request", "auto") else
                           ("gh pr view (a code-host read)", "gh pr view 12")):
        if fire(guard_cmd, command, repo) == 0:
            ok(f"guard lets {label} through (no false positive)")
        else:
            fail(f"guard blocks {label} — it will get in the way of every ticket", runbook)

    draft = ("cat > mr.md <<'MD'\n# MR draft\nStaged, not committed. The human runs:\n"
             "git commit -m 'PROJ-1: x' && git push -u origin some-branch\nMD")
    if fire(guard_cmd, draft, repo) == 0:
        ok("guard lets a draft that mentions a blocked command through (mr.md is data)")
    else:
        fail("guard blocks writing an mr.md draft that quotes `git commit`/`git push` — the "
             "deliverable of every route becomes unwritable", runbook)

    if fire(guard_cmd, "git push --force", outside) == 0:
        ok("guard stays out of projects outside the workspace")
    else:
        fail(f"guard fires outside the {WORKSPACE_NAME} workspace — it must scope itself to "
             f"the workspace root, not to whatever repo a command names", runbook)

    # The exit-code contract, probed directly. Everything above assumes "registered"
    # means "blocks"; this is the assumption itself under test. A command that cannot
    # run must not read as a pass, so a synthetic broken registration is fired on
    # purpose and any non-2 answer is reported as fail-open rather than as a block.
    broken = split_command(guard_cmd)
    if broken:
        probe = '"%s" "%s"' % (broken[0], os.path.join(SANDBOX, "no-such-guard.py"))
        rc = fire(probe, "git push", repo)
        if rc == 2:
            ok("exit-code contract: a broken hook command still blocks")
        else:
            warn(f"exit-code contract: a hook command pointing at a missing script exits "
                 f"{rc}, not 2 — Claude Code would NOT block, so any breakage of this hook "
                 f"is silent. This is why registration is never taken as proof",
                 "nothing to fix here; it is why this doctor live-fires instead of reading "
                 "the config, and why PYTHON_PATH must be an absolute verified interpreter")

    if os.path.exists(GUARD_TESTS):
        try:
            r = sh([sys.executable, GUARD_TESTS], timeout=180)
        except subprocess.TimeoutExpired:
            fail("guard unit tests timed out after 180s",
                 f"python3 {os.path.relpath(GUARD_TESTS, WORKSPACE_ROOT)}   # find the hang by hand")
        else:
            if r.returncode == 0:
                n = re.search(r"Ran (\d+) tests", r.stderr or "")
                ok(f"guard unit tests green ({n.group(1) if n else '?'} tests)")
            else:
                fail("guard unit tests fail", f"python3 {os.path.relpath(GUARD_TESTS, WORKSPACE_ROOT)}")
    else:
        warn("no unit tests next to the guard", f"restore .claude/hooks/{GUARD_TESTS_BASENAME}")


def check_own_tests():
    """The doctor asserts the guard; this is what asserts the doctor.

    Structurally cannot recurse: the child run carries DOCTOR_SELF_TEST, and a doctor that
    sees it skips this check. Without that, a test exercising this function would spawn a
    suite that spawns a suite.
    """
    if os.environ.get("DOCTOR_SELF_TEST"):
        return
    if not os.path.exists(DOCTOR_TESTS):
        warn("no unit tests next to the doctor",
             f"restore {os.path.basename(DOCTOR_TESTS)} from the kit")
        return
    try:
        r = sh([sys.executable, DOCTOR_TESTS], timeout=180,
               env=dict(os.environ, DOCTOR_SELF_TEST="1"))
    except subprocess.TimeoutExpired:
        fail("doctor unit tests timed out after 180s",
             f"python3 {os.path.basename(DOCTOR_TESTS)}   # find the hang by hand")
        return
    if r.returncode == 0:
        n = re.search(r"Ran (\d+) tests", r.stderr or "")
        ok(f"doctor unit tests green ({n.group(1) if n else '?'} tests)")
    else:
        fail("doctor unit tests fail — this doctor's own assertions are broken, so nothing "
             "else it reports can be trusted",
             f"python3 {os.path.basename(DOCTOR_TESTS)}")


# --- section 3: git hygiene ----------------------------------------------

def client_repos():
    """Every repo checked out directly under the workspace root — the ones the
    personal layer must stay invisible to. The workspace's own repo is excluded
    on purpose: its whitelist .gitignore is meant to TRACK the personal layer."""
    out = []
    try:
        names = sorted(os.listdir(WORKSPACE_ROOT))
    except OSError:
        return out
    for name in names:
        path = os.path.join(WORKSPACE_ROOT, name)
        if name.startswith(".") or not os.path.isdir(path):
            continue
        if os.path.exists(os.path.join(path, ".git")):
            out.append(path)
    # Linked worktrees the worktree skill parked under worktrees/: their .git is a
    # pointer file, their exclude is the original's (shared common dir), and they need
    # the same skill links — so they are client repos for every check that follows.
    wt_root = os.path.join(WORKSPACE_ROOT, "worktrees")
    if os.path.isdir(wt_root):
        for name in sorted(os.listdir(wt_root)):
            path = os.path.join(wt_root, name)
            if os.path.isdir(path) and os.path.exists(os.path.join(path, ".git")):
                out.append(path)
    return out


def check_git_hygiene(settings, local):
    """What the layer must never do to a client repo, checked from the wrapper.

    Nothing of the layer is written into client repos — not a link, not a line in
    .git/info/exclude. The guard hook (section 2) is the mechanism; this section covers
    the settings around it and reports, read-only, the traces earlier kit versions left.
    """
    repos = client_repos()

    # A workspace root named the same as one of the repos inside it is legal and
    # harmless mechanically, but it makes every later sentence about that name
    # ambiguous — and the boundary it straddles is the one that decides whether the
    # AI-file rule applies (the guard exempts the root itself and treats every repo
    # strictly below it as a client repo). Observed on a real rollout, where a RETRO
    # recorded its own location as if it were inside a client repo. Warn, do not fail.
    root_name = os.path.basename(WORKSPACE_ROOT.rstrip(os.sep))
    if any(os.path.basename(r) == root_name for r in repos):
        warn(f"the workspace root and a client repo inside it are both named "
             f"'{root_name}' — nothing breaks, but every path discussion about "
             f"'{root_name}' becomes ambiguous, on either side of the boundary that "
             f"decides where the AI-file rule applies",
             f"rename the workspace root (the client repo's name is not yours to change), "
             f"then re-substitute WORKSPACE_PATH in the hook, the doctor and settings.local.json")
    if not repos:
        warn(f"no client repos directly under {WORKSPACE_ROOT} — is WORKSPACE_PATH right?",
             "clone the client repos into the workspace root")

    # Traces of earlier kit versions inside client repos: an exclude block written into
    # each repo's .git/info/exclude, and skills/agents symlinked in. The kit writes nothing
    # there any more and removes nothing either — the human decides, by hand.
    marker = "personal AI layer (managed by .claude/setup/install.sh)"
    traces = []
    for repo in repos:
        rname = os.path.basename(repo)
        gitdir = sh(["git", "-C", repo, "rev-parse", "--git-common-dir"]).stdout.strip()
        if gitdir:
            if not os.path.isabs(gitdir):
                gitdir = os.path.join(repo, gitdir)
            try:
                with open(os.path.join(gitdir, "info", "exclude"), encoding="utf-8", errors="replace") as fh:
                    if marker in fh.read():
                        traces.append(f"{rname}: .git/info/exclude block")
            except OSError:
                pass
        for name in ("agents", "skills"):
            d = os.path.join(repo, ".claude", name)
            if os.path.islink(d) or getattr(os.path, "isjunction", lambda _p: False)(d):
                traces.append(f"{rname}: .claude/{name} link")
            elif os.path.isdir(d):
                traces.extend(f"{rname}: .claude/{name}/{e} link" for e in sorted(os.listdir(d))
                              if os.path.islink(os.path.join(d, e)))
    if traces:
        warn(f"earlier kit versions left {len(traces)} trace(s) inside client repos: "
             f"{'; '.join(traces)}",
             "the kit no longer writes into client repos and does not clean up either — remove "
             "them by hand if you want them gone: delete the marked block from .git/info/exclude, "
             "delete the .claude/skills and .claude/agents links")
    elif repos:
        ok(f"no kit traces inside the {len(repos)} client repo(s) — nothing is written there by design")

    # Drift from the pre-local build: a leftover global excludesFile silently ignores
    # .claude/ in every repo on the machine, including ones that are supposed to track it.
    path = os.path.expanduser(sh(["git", "config", "--global", "core.excludesFile"]).stdout.strip())
    if path and os.path.exists(path):
        try:
            body = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            body = ""
        # Match the pattern exactly, not as a substring: a narrow personal line
        # like `**/.claude/settings.local.json` is the user's business and hides
        # nothing wholesale — only a bare `.claude/` blankets every repo.
        blankets = {".claude", ".claude/", "/.claude", "/.claude/", "**/.claude", "**/.claude/"}
        patterns = {l.strip() for l in body.splitlines()
                    if l.strip() and not l.lstrip().startswith("#")}
        if patterns & blankets:
            warn(f"{path} still ignores .claude/ globally — a leftover from an earlier build; "
                 f"the kit sets nothing machine-wide",
                 f"remove the AI patterns from {path} (drop the file and "
                 f"`git config --global --unset core.excludesFile` if nothing else of yours uses it)")

    # Attribution is part of the build, so it lives in the workspace settings and travels
    # with them. Project settings take precedence over the user file, so a false here holds.
    if (local or {}).get("includeCoAuthoredBy") is False:
        ok("includeCoAuthoredBy: false in .claude/settings.local.json (no AI trailers in client commits)")
    elif (settings or {}).get("includeCoAuthoredBy") is False:
        warn("includeCoAuthoredBy is false only in ~/.claude/settings.json — an earlier kit version "
             "put it there; the build should carry it itself so it survives a new machine",
             'add "includeCoAuthoredBy": false to .claude/settings.local.json')
    else:
        fail("includeCoAuthoredBy is not false — commits will carry an AI co-author trailer",
             'add "includeCoAuthoredBy": false to .claude/settings.local.json')


# --- section 4: MCP wiring (the incident this doctor exists for) ---------

def live_mcp_servers():
    r = sh("claude mcp list", timeout=120)
    if r.returncode != 0 and not r.stdout:
        return None
    servers = {}
    for line in r.stdout.splitlines():
        # "name: <url> [(TYPE)] - <status>"; the name may contain spaces, never a colon
        m = re.match(r"^(?P<name>[^:]+):\s+\S+.*?\s+-\s+(?P<status>.+)$", line.strip())
        if m:
            servers[m.group("name").strip()] = m.group("status").strip()
    return servers


def tool_prefixes(perms):
    out = set()
    for bucket in ("allow", "ask", "deny"):
        for entry in perms.get(bucket, []) or []:
            m = re.match(r"^mcp__([^_]+(?:_[^_]+)*?)(?:__|$)", entry)
            if m:
                out.add(m.group(1))
    return out


def check_expected_mcp(entry, servers, connectors):
    name, server_name = entry["name"], server_name_of(entry["prefix"])
    # Only an explicit WARN softens the check: a mistyped level stays fail-closed.
    missing = warn if entry["level"] == "WARN" else fail
    # Substring matching is why the tracker check used to pass by coincidence: server
    # name "atlassian" is contained in the display name "claude.ai Atlassian Rovo", so a
    # connector satisfied a check meant for a registered server. Keep both, but say
    # which one was found — and never let an unauthenticated one read as a pass.
    found = [n for n in servers if server_name.lower() in n.lower()]
    if len(found) == 1:
        source = found[0]
        via = "claude.ai connector" if source in connectors else "registered server"
        if "Connected" in servers[source]:
            ok(f"exactly one {name} MCP source ({source}, {via}, {servers[source]})")
        else:
            missing(f"the only {name} MCP source ({source}, {via}) is {servers[source]} — "
                    f"{entry['consequence']}",
                    "/mcp   # authenticate; OAuth is interactive, a human has to do it")
    elif not found:
        missing(f"no {name} MCP server — {entry['consequence']}", entry["add_hint"])
    else:
        warn(f"{len(found)} {name} MCP servers: {', '.join(found)} — tool names "
             f"differ per server, so the deny list may cover only one of them",
             "claude mcp list   # keep one, remove the rest, or extend deny to both prefixes")


def _mcp_entries(perms):
    return [e for bucket in ("allow", "ask", "deny") for e in perms.get(bucket, []) or []
            if e.startswith("mcp__")]


def check_mcp(local):
    perms = (local or {}).get("permissions", {}) or {}
    no_tracker = not effective_prefix(TRACKER_MCP_PREFIX)
    if no_tracker:
        ok(NO_TRACKER_LINE)
    if no_tracker and not _mcp_entries(perms):
        servers = {}
    else:
        servers = live_mcp_servers()
    if servers is None:
        warn("`claude mcp list` returned nothing — cannot verify MCP wiring",
             "claude mcp list   # run by hand and compare with .claude/settings.local.json")
        return

    connected = {n for n, s in servers.items() if "Connected" in s}
    local_names = {n for n in servers if not n.lower().startswith("claude.ai ")}

    # `claude mcp list` DOES list account connectors, one per line as "claude.ai <Name>"
    # with a health status — an earlier version of this comment said they were invisible,
    # which was stale. What the listing gives is the connector's DISPLAY NAME, though,
    # while permission entries address it by the `mcp__<uuid>__` tool prefix. So the uuid
    # still needs a live session; only the blanket "invisible" was wrong.
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    connectors = {n: st for n, st in servers.items() if n.lower().startswith("claude.ai ")}
    unauthenticated = {n: st for n, st in connectors.items() if "Connected" not in st}

    for prefix in sorted(tool_prefixes(perms)):
        if prefix in connected:
            ok(f"permission entries mcp__{prefix}__* match a live connected server")
        elif uuid_re.match(prefix):
            if not connectors:
                warn(f"permission entries mcp__{prefix}__* look like a claude.ai connector "
                     f"id, but `claude mcp list` shows no connectors at all under this "
                     f"login — the rules may be enforcing nothing",
                     "claude mcp list   # if the connectors belong to another account, "
                     "log in as the one the workspace was set up for")
            elif unauthenticated:
                warn(f"permission entries mcp__{prefix}__* target a claude.ai connector; "
                     f"{len(unauthenticated)} connector(s) need authentication "
                     f"({', '.join(sorted(unauthenticated))}). The uuid itself is not in the "
                     f"CLI listing, so match it in a live session",
                     "/mcp   # authenticate, then check the tool prefix inside a session")
            else:
                warn(f"permission entries mcp__{prefix}__* target a claude.ai connector — "
                     f"connectors are listed and authenticated, but the listing gives display "
                     f"names, not uuids, so confirm this id inside a live session",
                     "in a session with connectors enabled, check the tool prefix matches")
        elif prefix in servers:
            fail(f"server '{prefix}' is registered but {servers[prefix]}",
                 f"claude mcp get {prefix}   # then re-authenticate in the browser")
        else:
            fail(f"permission entries name mcp__{prefix}__* but no such server exists "
                 f"(live: {', '.join(sorted(local_names)) or 'none'}) — these allow/deny rules "
                 f"match nothing and enforce nothing",
                 "claude mcp list   # take the exact server name and rewrite the prefixes "
                 "in .claude/settings.local.json")

    for entry in expected_mcp_servers():
        check_expected_mcp(entry, servers, connectors)

    mutating_allowed = [e for e in perms.get("allow", []) or []
                        if e.startswith("mcp__") and mcp_write_verb(e.split("__")[-1])]
    if mutating_allowed:
        fail(f"allow list contains write-looking MCP tools: {', '.join(mutating_allowed)} "
             f"— the drafts-only rule says a human publishes",
             "move them to deny in .claude/settings.local.json")
    else:
        ok("allow list is read-only tools (drafts-only: a human publishes)")

    if not (perms.get("deny") or []):
        if no_tracker:
            fail("deny list is empty — the git deny entries are gone, so only the guard "
                 "hook stands between the agent and a commit or push",
                 "restore the deny block in .claude/settings.local.json")
        else:
            fail(f"deny list is empty — nothing stops a write to {TRACKER_NAME} or the wiki",
                 "restore the deny block in .claude/settings.local.json")
    else:
        ok(f"deny list holds {len(perms['deny'])} entries")

    root = load_json(CLAUDE_JSON) or {}
    if root.get("mcpServers"):
        warn(f"global mcpServers is not empty ({', '.join(root['mcpServers'])}) — every session "
             f"everywhere pays for those tool schemas",
             "claude mcp remove <name> -s user   # keep MCP servers project-scoped")
    else:
        ok("global mcpServers is empty (MCP stays project-scoped)")


# --- section 5: model / effort policy ------------------------------------

def _prompts_are_real(settings):
    mode = ((settings or {}).get("permissions", {}) or {}).get("defaultMode")
    return mode, mode not in ("acceptEdits", "auto", "bypassPermissions")


def check_gate_policy(settings, local, param, what, entries, noun, verb):
    """One CONFIG policy against the permission layers that could undo it.

    param   — "COMMIT_POLICY" / "PUSH_POLICY"
    what    — the command as the human knows it: "git commit" / "git push"
    entries — the permission entries that name it
    noun    — "commit" / "push"; verb — "commits" / "pushes"

    The gate is the hook's job. A permission entry cannot BE the gate — it is
    prefix-matched, and a mode that auto-approves dissolves it — but it can quietly
    re-open one, and under on-request it is the only approval left, so it must exist
    and must actually prompt.
    """
    perms = (local or {}).get("permissions", {}) or {}
    allow, ask, deny = (set(perms.get(b, []) or []) for b in ("allow", "ask", "deny"))
    policy = installed_policy(param)
    mode, prompts_are_real = _prompts_are_real(settings)
    listed = " and ".join(sorted(entries))

    if policy is None:
        warn(f"cannot read {param} from .claude/hooks/{GIT_GUARD_HOOK}.py",
             "check the CONFIG block at the top of the guard; a guard from an older kit "
             "lacks the parameter — update it from the kit")
    elif policy == "auto":
        # No prompt by design: the permission layer must not re-introduce one that the
        # human chose to drop (deny), and the gate the human relied on instead — the code
        # host's branch protection — must at least be on record, because nothing on this
        # machine can check it.
        protection = recorded_branch_protection()
        if protection is None:
            fail(f"{param}=auto but the SETUP-PLAN does not record what protects the "
                 f"default branch — the agent {verb} with no gate anyone has named",
                 f'fill the "{BRANCH_PROTECTION_ROW}" row in <WS>-SETUP-PLAN.md §1 with the '
                 f"code host's actual branch rules, or set {param}=on-request / never")
        elif entries & deny:
            fail(f"{param}=auto but the permission layer DENIES `{what}` — the policy "
                 "says no gate and the settings say a wall",
                 f"move {listed} from deny to allow, or set {param} to what the settings "
                 "actually enforce")
        elif entries <= allow:
            ok(f"{param}=auto, `{what}` in ALLOW, code-host gate on record: {protection}")
        elif entries & ask:
            warn(f"{param}=auto but `{what}` sits in ASK — the prompt the policy dropped "
                 "is still there (harmless, but the two disagree)",
                 f"move {listed} to allow, or set {param}=on-request")
        else:
            warn(f"{param}=auto and `{what}` is in no permission bucket, so it falls back "
                 "to a prompt",
                 f"add {listed} to allow")
        return
    elif policy == "on-request":
        if not prompts_are_real:
            fail(f'{param}=on-request but permissions.defaultMode is "{mode}" — the '
                 f"per-{noun} approval is auto-clicked, so the agent {verb} unasked",
                 f"either set {param}=never in the guard's CONFIG, or switch "
                 "defaultMode to one that actually prompts")
        elif entries & allow:
            fail(f"{param}=on-request but `{what}` is in ALLOW — there is no "
                 "approval left to give",
                 f"move {listed} from allow to ask")
        elif entries <= deny:
            warn(f"{param}=on-request but the permission layer DENIES `{what}` — "
                 "the human can never say yes",
                 f"move {listed} from deny to ask, or set {param}=never so the two "
                 "layers agree")
        elif entries & ask:
            ok(f"{param}=on-request, `{what}` in ASK, prompts are real — the prompt is "
               f"the per-{noun} approval")
        else:
            warn(f"{param}=on-request and `{what}` is in no permission bucket",
                 f"add {listed} to ask")
        return

    if entries & allow:
        fail(f"`{what}` is in the permission ALLOW list — the agent {verb} without "
             "even a prompt",
             f"move {listed} from allow to deny in .claude/settings.local.json")
    elif entries & ask:
        warn(f"`{what}` sits in ASK rather than DENY under {param}=never — a prompt is "
             "not a gate: it is prefix-matched, and an auto-approving permission mode "
             "dissolves it",
             f"move {listed} to deny; the hook is what enforces the rule")
    elif entries <= deny:
        ok(f"`{what}` denied in the permission layer (the hook is the gate, this is the net)")
    else:
        warn(f"`{what}` is in no permission bucket, so it falls back to a prompt",
             f"add {listed} to deny in .claude/settings.local.json")


def check_commit_policy(settings, local):
    check_gate_policy(settings, local, "COMMIT_POLICY", "git commit",
                      {"Bash(git commit)", "Bash(git commit:*)"}, "commit", "commits")


def check_push_policy(settings, local):
    check_gate_policy(settings, local, "PUSH_POLICY", "git push",
                      {"Bash(git push)", "Bash(git push:*)"}, "push", "pushes")


def check_tracker_policy(local):
    prefix = effective_prefix(TRACKER_MCP_PREFIX)
    if not prefix:
        return
    policy = installed_policy("TRACKER_MCP_POLICY")
    if policy is None:
        warn(f"cannot read TRACKER_MCP_POLICY from .claude/hooks/{GIT_GUARD_HOOK}.py",
             "check the CONFIG block at the top of the guard; a guard from an older kit "
             "lacks the parameter — update it from the kit")
    elif policy == "drafts-only":
        ok("TRACKER_MCP_POLICY=drafts-only (tracker reads pass, writes are a human's)")
    elif policy == "block-all":
        perms = (local or {}).get("permissions", {}) or {}
        server_entry = "mcp__" + server_name_of(prefix)
        opened = [e for bucket in ("allow", "ask") for e in perms.get(bucket, []) or []
                  if e.startswith(prefix) or e == server_entry]
        denied = [e for e in perms.get("deny", []) or []
                  if e.startswith(prefix) or e == server_entry]
        if opened:
            fail(f"TRACKER_MCP_POLICY=block-all but allow/ask still names the tracker "
                 f"({', '.join(opened)}) — the policy says no tracker call at all and the "
                 f"permission layer lets one through",
                 f"remove those entries from allow/ask in .claude/settings.local.json and "
                 f"deny {server_entry}")
        if not denied:
            fail(f"TRACKER_MCP_POLICY=block-all but deny holds neither {server_entry} nor "
                 f"any {prefix}* entry — only the hook stops a tracker call",
                 f'add "{server_entry}" to deny in .claude/settings.local.json')
        if not opened and denied:
            ok(f"TRACKER_MCP_POLICY=block-all, {', '.join(denied)} denied, nothing opens the tracker")
    else:
        warn(f'TRACKER_MCP_POLICY is "{policy}" — not a value the guard knows, so it '
             f"reads it as drafts-only and tracker reads stay open",
             "set TRACKER_MCP_POLICY in .claude/hooks/git-guard.py to drafts-only or block-all")


def check_prompt_mode(settings):
    mode, prompts_are_real = _prompts_are_real(settings)
    if not prompts_are_real:
        warn(f'permissions.defaultMode is "{mode}" — prompts are auto-approved, so every '
             f"`ask` entry on this machine is decoration",
             "the hook still holds; do not rely on an `ask` entry while this mode is set")
    elif mode:
        ok(f"permissions.defaultMode: {mode} (ask entries actually prompt)")


def check_policy(settings):
    s = settings or {}
    if s.get("model") and s.get("effortLevel"):
        ok(f"model/effort defaults set ({s['model']} / {s['effortLevel']})")
    else:
        warn("model or effortLevel is not pinned in ~/.claude/settings.json",
             "set \"model\" and \"effortLevel\" per the workspace token policy")


INDEX_LINE_CAP = 150


def check_index_size():
    path = os.path.join(WORKSPACE_ROOT, "CLAUDE.md")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().split("\n")
    except OSError:
        return
    if lines and lines[-1] == "":
        lines.pop()
    lines = len(lines)
    if lines <= INDEX_LINE_CAP:
        ok(f"CLAUDE.md is {lines} lines (cap {INDEX_LINE_CAP})")
    else:
        warn(f"CLAUDE.md is {lines} lines — over the {INDEX_LINE_CAP}-line cap "
             f"by {lines - INDEX_LINE_CAP}",
             "trim CLAUDE.md: details belong in data/<service>.md, "
             f"the index stays ≤{INDEX_LINE_CAP} lines")


def main():
    print(f"{PROJECT_PREFIX} doctor — {WORKSPACE_ROOT}\n")
    settings = load_json(GLOBAL_SETTINGS)
    local = load_json(LOCAL_SETTINGS)
    if local is None:
        fail(".claude/settings.local.json is missing or not valid JSON",
             "restore it from git: git checkout .claude/settings.local.json")

    try:
        guard_cmd = check_registration(local, settings)
        check_guard_fires(guard_cmd)
        check_own_tests()
        check_git_hygiene(settings, local)
        check_mcp(local)
        check_commit_policy(settings, local)
        check_push_policy(settings, local)
        check_tracker_policy(local)
        check_prompt_mode(settings)
        check_policy(settings)
        check_index_size()
    finally:
        remove_sandboxes()

    failures = [r for r in results if r[0] == "FAIL"]
    warnings = [r for r in results if r[0] == "WARN"]
    print(f"\n{len(results) - len(failures) - len(warnings)} pass · "
          f"{len(warnings)} warn · {len(failures)} fail")
    if failures or warnings:
        print("\nRUNBOOK (nothing above was fixed automatically):")
        for status, message, runbook in failures + warnings:
            if runbook:
                print(f"  [{status}] {message}\n        {runbook}")
    if failures:
        print("\nA failed safety net is not a warning: do not start a ticket until it is green.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
