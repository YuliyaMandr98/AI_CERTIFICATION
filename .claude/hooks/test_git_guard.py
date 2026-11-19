#!/usr/bin/env python3
"""Unit tests for git-guard.py (kit version). Run: python3 kit/hooks/test_git_guard.py

No dependencies, no network. The guard on disk carries unsubstituted placeholder-token CONFIG
values; these tests import the module and override the CONFIG constants in
memory (a temp dir plays the workspace root) — nothing on disk is substituted.
The guard reads WORKSPACE_PATH at call time precisely so this injection works.
"""
import contextlib, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, unittest

HOOK = os.path.join(os.path.dirname(os.path.realpath(__file__)), "git-guard.py")


def _load_guard():
    spec = importlib.util.spec_from_file_location("git_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()

# --- injected CONFIG: a throwaway dir is the workspace root for every test ---
WORKSPACE_ROOT = tempfile.mkdtemp(prefix="guard-workspace-")
guard.WORKSPACE_PATH = WORKSPACE_ROOT
guard.WORKSPACE_NAME = "TestWS"
# an installed copy carries its own policies; every test starts from the default, and
# CommitPolicy / PushPolicy open it explicitly. The loaded values stay for the
# shipped-default tests.
SHIPPED_COMMIT_POLICY, SHIPPED_PUSH_POLICY = guard.COMMIT_POLICY, guard.PUSH_POLICY
guard.COMMIT_POLICY = guard.PUSH_POLICY = "never"
# the kit file still carries its tokens; an installed copy has none left (the token is
# built at runtime so the installer's substitution cannot rewrite this line)
with open(HOOK, encoding="utf-8") as _f:
    IS_TEMPLATE = "{{" + "WORKSPACE_PATH}}" in _f.read()


def tearDownModule():
    shutil.rmtree(WORKSPACE_ROOT, ignore_errors=True)


def run_hook(command: str, cwd: str):
    """Feed a Bash PreToolUse payload to the guard in-process; return (exit code, stderr)."""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = guard.run(payload)
    return code, err.getvalue()


def run_codex(payload: dict):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = guard.run(payload, runtime="codex")
    return code, err.getvalue()


def make_repo(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True, capture_output=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "--allow-empty", "-m", "init"],
                   check=True, capture_output=True)
    return path


class DestructiveCommands(unittest.TestCase):
    """Rule 1: blocked anywhere inside the workspace, silent outside it."""

    @classmethod
    def setUpClass(cls):
        cls.inside = make_repo(os.path.join(WORKSPACE_ROOT, "client-repo"))
        cls.outside_dir = tempfile.mkdtemp(prefix="guard-outside-")
        cls.outside = make_repo(os.path.join(cls.outside_dir, "other-project"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.inside, ignore_errors=True)
        shutil.rmtree(cls.outside_dir, ignore_errors=True)

    def assert_blocked(self, command, cwd=None):
        code, err = run_hook(command, cwd or self.inside)
        self.assertEqual(code, 2, f"expected BLOCK for: {command}\nstderr: {err}")
        self.assertIn("BLOCKED", err)

    def assert_allowed(self, command, cwd=None):
        code, err = run_hook(command, cwd or self.inside)
        self.assertEqual(code, 0, f"expected ALLOW for: {command}\nstderr: {err}")

    def test_push_variants(self):
        for cmd in ("git push",
                    "git push origin PROJ-459/slug",
                    "git push --force",
                    "git push --force-with-lease origin HEAD",
                    "git -C ../other-client-repo push",
                    "cd /tmp && git push",       # cd does not move the hook's cwd
                    "yarn lint && git push"):
            self.assert_blocked(cmd)

    def test_destructive_push_variants(self):
        # these stay blocked under every PUSH_POLICY; the plain push is the policy's
        for cmd in ("git push --force",
                    "git push -f origin HEAD",
                    "git push -fu origin PROJ-459/slug",
                    "git push --delete origin PROJ-459/slug",
                    "git push -d origin PROJ-459/slug",
                    "git push origin :PROJ-459/slug",
                    "git push origin :refs/heads/PROJ-459/slug",
                    "git push --mirror backup"):
            code, err = run_hook(cmd, self.inside)
            self.assertEqual(code, 2, f"expected BLOCK for: {cmd}\nstderr: {err}")
            self.assertIn("--force / --delete", err, f"wrong rule fired for: {cmd}")

    def test_pr_creation_is_publication(self):
        for cmd in ("gh pr create --fill",
                    "gh pr create --title 'PROJ-459: x' --body-file tasks/PROJ-459/mr.md",
                    "glab mr create --fill --yes",
                    "yarn lint && gh pr create --fill",
                    "git push -u origin HEAD; gh pr create --fill",
                    "(cd client-repo && glab mr create)"):
            self.assert_blocked(cmd)
        _, err = run_hook("gh pr create --fill", self.inside)
        self.assertIn("mr.md", err)

    def test_code_host_reads_are_untouched(self):
        for cmd in ("gh pr view 12",
                    "gh pr list --author @me",
                    "gh pr diff 12",
                    "gh pr checks 12",
                    "gh pr status",
                    "glab mr view 12",
                    "glab mr list",
                    "gh issue view 7",
                    "gh api repos/acme-group/x/pulls/12/comments"):
            self.assert_allowed(cmd)

    def test_history_and_tree_destroyers(self):
        for cmd in ("git reset --hard",
                    "git reset --hard HEAD~3",
                    "git reset --hard origin/main",
                    "git clean -f",
                    "git clean -fd",
                    "git clean -xfd",
                    "git clean --force",
                    "git branch -D PROJ-459/slug",
                    "git branch --delete --force PROJ-459/slug",
                    "git checkout .",
                    "git checkout -- .",
                    "git checkout HEAD -- .",
                    "git restore .",
                    "git restore -- ."):
            self.assert_blocked(cmd)

    def test_workspace_root_is_covered_too(self):
        # the personal repo at the root: no remote, but data/ describes client code
        self.assert_blocked("git push", cwd=WORKSPACE_ROOT)
        self.assert_blocked("git reset --hard", cwd=WORKSPACE_ROOT)

    def test_everyday_git_is_untouched(self):
        for cmd in ("git status",
                    "git diff --cached",
                    "git log --oneline -20",
                    "git add src/app.service.ts",
                    "git reset src/app.service.ts",       # unstage, no --hard
                    "git clean -n",                       # dry run
                    "git branch -d merged-branch",        # safe delete
                    "git checkout PROJ-459/slug",
                    "git checkout -b PROJ-459/slug",
                    "git checkout main -- ./src/app.service.ts",
                    "git restore src/app.service.ts",
                    "git stash"):
            self.assert_allowed(cmd)

    def test_out_of_workspace_is_none_of_our_business(self):
        for cmd in ("git push", "git reset --hard", "git clean -fd",
                    "gh pr create --fill", "glab mr create"):
            self.assert_allowed(cmd, cwd=self.outside)

    def test_dash_c_out_of_workspace_is_not_blocked(self):
        code, _ = run_hook(f"git -C {self.outside} push", self.outside)
        self.assertEqual(code, 0)

    def test_dash_c_into_workspace_from_outside_is_blocked(self):
        self.assert_blocked(f"git -C {self.inside} push", cwd=self.outside)

    def test_file_writing_heredoc_is_data_not_commands(self):
        # tasks/<KEY>/mr.md exists to tell the human which command to run; a guard
        # that blocks the document only teaches the agent to reword the document
        for cmd in ("cat > mr.md <<'EOF'\n# MR\nNot pushed. Run:\ngit push -u origin fix/x\nEOF",
                    "tee mr.md <<EOF\ngit push origin HEAD\nEOF",
                    "cat > notes.md <<'MD'\nnever ours to run: git reset --hard\nMD",
                    "cat >> notes.md <<-'MD'\n\tgit clean -fd is the human's call\n\tMD"):
            self.assert_allowed(cmd)

    def test_interpreter_and_piped_heredocs_are_still_blocked(self):
        # the allowlist is closed by default: anything that can EXECUTE the body
        # keeps the body in scope
        for cmd in ("bash <<'EOF'\ngit push\nEOF",
                    "sh <<EOF\ngit push origin main\nEOF",
                    "cat <<'EOF' | bash\ngit push\nEOF",
                    "python3 - <<'PY'\nimport os\nos.system('git push')\nPY"):
            self.assert_blocked(cmd)

    def test_a_real_command_beside_a_heredoc_is_still_blocked(self):
        self.assert_blocked("cat > mr.md <<'EOF'\ndone\nEOF\ngit push -u origin fix/x")


class CommitGate(unittest.TestCase):
    """Rule 1, commit half: a commit is the human's to ask for.

    The agent's ceiling is to ask or to remind. Staging stays allowed on purpose —
    `git add` is how the work is handed over for review, and rule 2 inspects the
    index, so taking it away would cost more than it buys.
    """

    @classmethod
    def setUpClass(cls):
        cls.inside = make_repo(os.path.join(WORKSPACE_ROOT, "commit-gate-repo"))
        cls.outside_dir = tempfile.mkdtemp(prefix="guard-outside-commit-")
        cls.outside = make_repo(os.path.join(cls.outside_dir, "other-project"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.inside, ignore_errors=True)
        shutil.rmtree(cls.outside_dir, ignore_errors=True)

    def test_commit_variants_are_blocked(self):
        for cmd in ("git commit",
                    "git commit -m 'PROJ-459: add tenant guard'",
                    "git commit -am wip",
                    "git commit --amend --no-edit",
                    "git commit -m x --no-verify",
                    "git add . && git commit -m x",
                    "yarn lint && git commit -m x",
                    "git -C ../other-client-repo commit -m x",
                    "cd /tmp && git commit -m x",
                    "git --no-pager commit -m x",
                    "git -c user.name=nobody commit -m x"):
            code, err = run_hook(cmd, self.inside)
            self.assertEqual(code, 2, f"expected BLOCK for: {cmd}\nstderr: {err}")
            self.assertIn("BLOCKED", err)

    def test_the_block_names_the_two_legal_moves(self):
        _, err = run_hook("git commit -m x", self.inside)
        self.assertIn("ask", err)
        self.assertIn("remind", err)

    def test_commit_inside_an_interpreter_heredoc_is_blocked(self):
        for cmd in ("bash <<'EOF'\ngit commit -m x\nEOF",
                    "cat <<'EOF' | bash\ngit commit -m x\nEOF"):
            code, err = run_hook(cmd, self.inside)
            self.assertEqual(code, 2, f"expected BLOCK for: {cmd}\nstderr: {err}")

    def test_stripping_the_agent_marker_does_not_buy_a_commit(self):
        # the escape hatch is the human's own terminal, not `env -u` in ours
        for cmd in ("env -u CLAUDECODE git commit -m x",
                    "unset CLAUDECODE; git commit -m x"):
            code, err = run_hook(cmd, self.inside)
            self.assertEqual(code, 2, f"expected BLOCK for: {cmd}\nstderr: {err}")

    def test_the_workspace_root_is_covered_too(self):
        code, _ = run_hook("git commit -m x", WORKSPACE_ROOT)
        self.assertEqual(code, 2)

    def test_staging_and_reading_stay_allowed(self):
        for cmd in ("git add src/app.service.ts",
                    "git add -A",
                    "git status --short",
                    "git diff --cached",
                    "git log --oneline -20",
                    "git log --grep=commit",          # reading about commits is reading
                    "git show --stat HEAD",
                    "git stash"):
            code, err = run_hook(cmd, self.inside)
            self.assertEqual(code, 0, f"expected ALLOW for: {cmd}\nstderr: {err}")

    def test_a_draft_quoting_a_commit_command_is_data(self):
        for cmd in ("cat > mr.md <<'EOF'\n# MR\nRun it yourself:\ngit commit -m 'PROJ-459: x'\nEOF",
                    "tee handover.md <<EOF\nstaged and ready — git commit -m x\nEOF"):
            code, err = run_hook(cmd, self.inside)
            self.assertEqual(code, 0, f"expected ALLOW for: {cmd}\nstderr: {err}")

    def test_out_of_workspace_commits_are_none_of_our_business(self):
        for cmd in ("git commit -m x", "git commit -am x"):
            code, err = run_hook(cmd, self.outside)
            self.assertEqual(code, 0, f"expected ALLOW outside for: {cmd}\nstderr: {err}")


class CommitPolicy(unittest.TestCase):
    """COMMIT_POLICY switches the commit half of rule 1, and only on an exact match."""

    @classmethod
    def setUpClass(cls):
        cls.repo = make_repo(os.path.join(WORKSPACE_ROOT, "policy-repo"))
        cls.shipped = guard.COMMIT_POLICY

    @classmethod
    def tearDownClass(cls):
        guard.COMMIT_POLICY = cls.shipped
        shutil.rmtree(cls.repo, ignore_errors=True)

    def tearDown(self):
        guard.COMMIT_POLICY = self.shipped

    def test_on_request_hands_the_gate_to_the_permission_prompt(self):
        guard.COMMIT_POLICY = "on-request"
        code, _ = run_hook("git commit -m 'PROJ-459: add x'", self.repo)
        self.assertEqual(code, 0)

    def test_codex_keeps_commit_mechanically_blocked(self):
        guard.COMMIT_POLICY = "on-request"
        payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
                   "cwd": self.repo}
        code, err = run_codex(payload)
        self.assertEqual(code, 2, err)

    def test_on_request_is_matched_loosely_enough_to_be_usable(self):
        for value in ("on-request", "On-Request", " on-request "):
            guard.COMMIT_POLICY = value
            code, _ = run_hook("git commit -m x", self.repo)
            self.assertEqual(code, 0, f"expected ALLOW for policy {value!r}")

    def test_everything_else_fails_closed(self):
        # a typo, a half-edit, an unsubstituted token — none of them may open the gate
        # the token is built at runtime: the installer substitutes it in this file too
        for value in ("never", "", "on_request", "onrequest", "ask",
                      "{{" + "COMMIT_POLICY}}", "never # decided 2026-09-02"):
            guard.COMMIT_POLICY = value
            code, _ = run_hook("git commit -m x", self.repo)
            self.assertEqual(code, 2, f"expected BLOCK for policy {value!r}")

    def test_the_policy_touches_nothing_but_commits(self):
        guard.COMMIT_POLICY = "on-request"
        for cmd in ("git push", "git reset --hard", "git clean -fd", "git checkout ."):
            code, _ = run_hook(cmd, self.repo)
            self.assertEqual(code, 2, f"expected BLOCK for: {cmd}")

    def test_the_shipped_default_is_gated(self):
        # the kit file carries an unsubstituted token; that must read as "never". An
        # installed copy carries a chosen value, which the doctor live-fires instead.
        if not IS_TEMPLATE:
            self.skipTest(f"installed copy, COMMIT_POLICY={SHIPPED_COMMIT_POLICY!r}")
        guard.COMMIT_POLICY = SHIPPED_COMMIT_POLICY
        code, _ = run_hook("git commit -m x", self.repo)
        self.assertEqual(code, 2)


class PushPolicy(unittest.TestCase):
    """PUSH_POLICY switches the publication half of rule 1 — plain push and PR/MR
    creation — and only on an exact match. Destructive pushes are not on the switch."""

    @classmethod
    def setUpClass(cls):
        cls.repo = make_repo(os.path.join(WORKSPACE_ROOT, "push-policy-repo"))
        cls.shipped = guard.PUSH_POLICY

    @classmethod
    def tearDownClass(cls):
        guard.PUSH_POLICY = cls.shipped
        shutil.rmtree(cls.repo, ignore_errors=True)

    def tearDown(self):
        guard.PUSH_POLICY = self.shipped

    def test_on_request_hands_push_and_pr_creation_to_the_permission_prompt(self):
        guard.PUSH_POLICY = "on-request"
        for cmd in ("git push",
                    "git push -u origin PROJ-459/slug",
                    "git push origin HEAD:PROJ-459/slug",          # a refspec, not a deletion
                    "git push --force-with-lease origin HEAD",     # the safe force
                    "git push --force-if-includes --force-with-lease",
                    "gh pr create --fill",
                    "glab mr create --fill --yes",
                    "git push -u origin HEAD && gh pr create --fill"):
            code, err = run_hook(cmd, self.repo)
            self.assertEqual(code, 0, f"expected ALLOW for: {cmd}\nstderr: {err}")

    def test_auto_lets_the_same_commands_through_with_no_prompt_of_its_own(self):
        # the hook cannot tell "auto" from "on-request" — the difference is the
        # permission bucket (allow vs ask), which the doctor checks; here both pass
        guard.PUSH_POLICY = "auto"
        for cmd in ("git push", "git push -u origin PROJ-459/slug",
                    "gh pr create --fill", "glab mr create --fill --yes",
                    "git push --force-with-lease origin HEAD"):
            code, err = run_hook(cmd, self.repo)
            self.assertEqual(code, 0, f"expected ALLOW for: {cmd}\nstderr: {err}")

    def test_destructive_pushes_stay_blocked_under_every_opened_policy(self):
        for policy in ("on-request", "auto"):
            guard.PUSH_POLICY = policy
            for cmd in ("git push --force",
                        "git push -f origin HEAD",
                        "git push --delete origin PROJ-459/slug",
                        "git push origin :PROJ-459/slug",
                        "git push --mirror backup",
                        "git push -u origin HEAD && git push --force"):
                code, err = run_hook(cmd, self.repo)
                self.assertEqual(code, 2, f"expected BLOCK for: {cmd} under {policy}\nstderr: {err}")
                self.assertIn("any policy", err)

    def test_codex_blocks_on_request_but_honors_auto(self):
        for policy, expected in (("on-request", 2), ("auto", 0)):
            guard.PUSH_POLICY = policy
            for cmd in ("git push", "gh pr create --fill"):
                payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo}
                code, err = run_codex(payload)
                self.assertEqual(
                    code, expected,
                    f"expected Codex rc={expected} for: {cmd} under {policy}\nstderr: {err}",
                )

        guard.PUSH_POLICY = "auto"
        payload = {"tool_name": "Bash", "tool_input": {"command": "git push --force"},
                   "cwd": self.repo}
        code, err = run_codex(payload)
        self.assertEqual(code, 2, f"expected Codex destructive-push BLOCK under auto\nstderr: {err}")

    def test_opened_values_are_matched_loosely_enough_to_be_usable(self):
        for value in ("on-request", "On-Request", " on-request ", "auto", "AUTO", " auto "):
            guard.PUSH_POLICY = value
            code, _ = run_hook("git push", self.repo)
            self.assertEqual(code, 0, f"expected ALLOW for policy {value!r}")

    def test_everything_else_fails_closed(self):
        for value in ("never", "", "on_request", "onrequest", "allow", "yes", "always",
                      "automatic", "{{" + "PUSH_POLICY}}", "on-request # since 2026-09-16"):
            guard.PUSH_POLICY = value
            for cmd in ("git push", "gh pr create --fill"):
                code, _ = run_hook(cmd, self.repo)
                self.assertEqual(code, 2, f"expected BLOCK for {cmd} under policy {value!r}")

    def test_the_policy_touches_nothing_but_publication(self):
        for policy in ("on-request", "auto"):
            guard.PUSH_POLICY = policy
            for cmd in ("git commit -m x", "git reset --hard", "git clean -fd", "git checkout ."):
                code, _ = run_hook(cmd, self.repo)
                self.assertEqual(code, 2, f"expected BLOCK for: {cmd} under {policy}")

    def test_the_two_policies_are_independent(self):
        guard.PUSH_POLICY = "on-request"
        shipped_commit = guard.COMMIT_POLICY
        try:
            guard.COMMIT_POLICY = "never"
            self.assertEqual(run_hook("git commit -m x", self.repo)[0], 2)
            self.assertEqual(run_hook("git push", self.repo)[0], 0)
        finally:
            guard.COMMIT_POLICY = shipped_commit

    def test_the_shipped_default_is_gated(self):
        if not IS_TEMPLATE:
            self.skipTest(f"installed copy, PUSH_POLICY={SHIPPED_PUSH_POLICY!r}")
        guard.PUSH_POLICY = SHIPPED_PUSH_POLICY
        for cmd in ("git push", "gh pr create --fill"):
            code, _ = run_hook(cmd, self.repo)
            self.assertEqual(code, 2)

    def test_out_of_workspace_stays_none_of_our_business(self):
        guard.PUSH_POLICY = "never"
        outside_dir = tempfile.mkdtemp(prefix="guard-outside-push-")
        try:
            outside = make_repo(os.path.join(outside_dir, "other-project"))
            for cmd in ("git push --force", "gh pr create --fill"):
                code, _ = run_hook(cmd, outside)
                self.assertEqual(code, 0, f"expected ALLOW outside for: {cmd}")
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)


class AiConfigFiles(unittest.TestCase):
    """Rule 2: personal AI config must not enter a client repo.

    Rule 1 now blocks every commit, so these cases call the rule directly instead of
    going through run(): the point is that rule 2 fires on its own merits, not that a
    commit reaches it.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo = make_repo(os.path.join(WORKSPACE_ROOT, "client-repo-2"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.repo, ignore_errors=True)

    def test_blocks_ai_files_named_in_the_command(self):
        for cmd in ("git add .claude/settings.json",
                    "git add .agents/skills/private/SKILL.md",
                    "git add .codex/hooks.json",
                    "git add CLAUDE.local.md",
                    "git add AGENTS.md",
                    "git add .mcp.json"):
            code, err = run_hook(cmd, self.repo)
            self.assertEqual(code, 2, f"expected BLOCK for: {cmd}")
            self.assertIn("personal AI files", err)


    def test_blocks_staged_ai_files_on_commit(self):
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        with open(os.path.join(self.repo, ".claude", "settings.json"), "w") as f:
            f.write("{}\n")
        subprocess.run(["git", "-C", self.repo, "add", "-f", ".claude/settings.json"],
                       check=True, capture_output=True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = guard._check_ai_files("git commit -m 'wip'", self.repo)
        self.assertEqual(code, 2, err.getvalue())
        self.assertIn("personal AI files", err.getvalue())
        subprocess.run(["git", "-C", self.repo, "reset", "-q"], capture_output=True)

    def test_dash_c_from_workspace_root_cannot_bypass(self):
        # cwd at the workspace root (the personal repo's home): without -C
        # resolution rule 2 would look at the root, not the client repo
        code, err = run_hook("git -C client-repo-2 add .claude/settings.json",
                             WORKSPACE_ROOT)
        self.assertEqual(code, 2, err)
        self.assertIn("personal AI files", err)

    def test_allows_a_claude_md_the_team_already_committed(self):
        repo = make_repo(os.path.join(WORKSPACE_ROOT, "client-repo-3"))
        with open(os.path.join(repo, "CLAUDE.md"), "w") as f:
            f.write("# team doc\n")
        subprocess.run(["git", "-C", repo, "add", "-f", "CLAUDE.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "team doc"],
                       check=True, capture_output=True)
        with open(os.path.join(repo, "CLAUDE.md"), "a") as f:
            f.write("more\n")
        subprocess.run(["git", "-C", repo, "add", "CLAUDE.md"], check=True, capture_output=True)
        code = guard._check_ai_files("git commit -m 'PROJ-459: update team doc'", repo)
        self.assertEqual(code, 0)

    def test_heredoc_body_naming_ai_files_is_not_a_stage(self):
        # writing a doc that MENTIONS .claude/ is not the same as staging it
        code, err = run_hook(
            "cat > notes.md <<'MD'\nthe hook lives in .claude/hooks/git-guard.py\nMD\n"
            "git add notes.md", self.repo)
        self.assertEqual(code, 0, err)

    def test_allows_normal_files(self):
        with open(os.path.join(self.repo, "app.ts"), "w") as f:
            f.write("export const x = 1\n")
        subprocess.run(["git", "-C", self.repo, "add", "app.ts"], check=True, capture_output=True)
        code = guard._check_ai_files("git commit -m 'PROJ-459: add x'", self.repo)
        self.assertEqual(code, 0)


class CodexMcpWrites(unittest.TestCase):
    def setUp(self):
        self.shipped = guard.TRACKER_MCP_PREFIX
        guard.TRACKER_MCP_PREFIX = "mcp__tracker__"

    def tearDown(self):
        guard.TRACKER_MCP_PREFIX = self.shipped

    def _codex(self, operation):
        return run_codex({"tool_name": "mcp__tracker__" + operation,
                          "tool_input": {}, "cwd": WORKSPACE_ROOT})

    def test_mutating_tracker_tools_are_blocked(self):
        # Verb-first names, the official Atlassian scheme this kit documents.
        for operation in ("createIssue", "update_page", "deleteComment", "transitionIssue",
                          "createJiraIssue", "editJiraIssue", "addCommentToJiraIssue",
                          "addWorklogToJiraIssue", "createConfluencePage",
                          "updateConfluencePage", "createConfluenceFooterComment"):
            code, err = self._codex(operation)
            self.assertEqual(code, 2, f"{operation}: {err}")

    def test_namespace_first_writes_are_blocked(self):
        # The community mcp-atlassian scheme puts the server namespace first, so
        # the verb is not at the head of the name. Anchoring there let every one
        # of these through.
        for operation in ("jira_create_issue", "jira_update_issue", "jira_add_comment",
                          "jira_transition_issue", "jira_delete_issue",
                          "confluence_create_page", "confluence_update_page",
                          "confluence_delete_page"):
            code, err = self._codex(operation)
            self.assertEqual(code, 2, f"{operation}: {err}")

    def test_unrecognised_tracker_tools_block(self):
        # Closed by default: Codex has no permission prompt behind this hook, so a
        # name with no recognised verb in it counts as a write. None of these names
        # holds a WRITE_MCP_VERBS word, so they reach the closed branch itself —
        # weakening it to "allow" must fail here, not pass on the write list.
        for operation in ("unwatchIssue", "flagIssue", "notifyIssue", "toggleViewed",
                          "linkIssues", "atlassianUserInfo"):
            self.assertEqual(guard._mcp_verb(operation), (None, ""), operation)
            code, err = self._codex(operation)
            self.assertEqual(code, 2, f"{operation}: {err}")
            self.assertIn("no read verb is recognised", err, operation)

    def test_write_verb_anywhere_beats_a_later_read_verb(self):
        # "First recognised verb wins" let these through: the read word comes after
        # a write one, and each of them changes state.
        for operation in ("markAsRead", "mark_as_read", "reindexSearch", "uploadAttachment",
                          "publishPage"):
            code, err = self._codex(operation)
            self.assertEqual(code, 2, f"{operation}: {err}")
            self.assertIn("marks it as a tracker/wiki write", err, operation)

    def test_tracker_reads_and_other_servers_are_allowed(self):
        for name in ("mcp__tracker__getIssue", "mcp__tracker__search_pages",
                     "mcp__other__createIssue"):
            code, err = run_codex({"tool_name": name, "tool_input": {},
                                   "cwd": WORKSPACE_ROOT})
            self.assertEqual(code, 0, err)

    def test_documented_reads_are_not_false_positives(self):
        # Every read name the kit's own templates and reference plan name, plus
        # reads whose nouns look like verbs (link, bulk, log are not write verbs) and
        # getCreateMeta, a read by exact name in READ_MCP_TOOLS.
        for operation in ("getIssue", "searchIssues", "getPage", "search",
                          "getJiraIssue", "searchJiraIssuesUsingJql",
                          "getConfluencePage", "getAccessibleAtlassianResources",
                          "getVisibleJiraProjects", "jira_get_issue", "jira_search",
                          "getCreateMeta", "getTransitionsForJiraIssue",
                          "jira_link_types_get", "bulkGet", "getIssueLinkTypes",
                          "getJiraIssueRemoteIssueLinks", "getWorklogs",
                          "getConfluenceCommentChildren"):
            code, err = self._codex(operation)
            self.assertEqual(code, 0, f"{operation}: {err}")

    def test_claude_runtime_leaves_mcp_to_settings_permissions(self):
        payload = {"tool_name": "mcp__tracker__createIssue", "tool_input": {},
                   "cwd": WORKSPACE_ROOT}
        self.assertEqual(guard.run(payload), 0)


class TrackerPrefixAndPolicy(unittest.TestCase):
    def setUp(self):
        self.shipped = guard.TRACKER_MCP_PREFIX, guard.TRACKER_MCP_POLICY
        guard.TRACKER_MCP_PREFIX = "mcp__tracker__"
        guard.TRACKER_MCP_POLICY = "drafts-only"

    def tearDown(self):
        guard.TRACKER_MCP_PREFIX, guard.TRACKER_MCP_POLICY = self.shipped

    def _call(self, name, runtime="codex"):
        payload = {"tool_name": name, "tool_input": {}, "cwd": WORKSPACE_ROOT}
        if runtime == "codex":
            return run_codex(payload)
        return guard.run(payload), ""

    def test_prefix_none_means_no_tracker_to_guard(self):
        for prefix in ("none", "NONE", " None ", "none", "", "  "):
            guard.TRACKER_MCP_PREFIX = prefix
            code, err = self._call("mcp__anything__createIssue")
            self.assertEqual(code, 0, f"{prefix!r}: {err}")

    def test_prefix_none_wins_over_block_all(self):
        guard.TRACKER_MCP_PREFIX = "none"
        guard.TRACKER_MCP_POLICY = "block-all"
        code, err = self._call("mcp__tracker__getIssue")
        self.assertEqual(code, 0, err)

    def test_block_all_blocks_a_tracker_read_and_names_the_policy(self):
        guard.TRACKER_MCP_POLICY = "block-all"
        code, err = self._call("mcp__tracker__getIssue")
        self.assertEqual(code, 2)
        self.assertIn("TRACKER_MCP_POLICY=block-all", err)

    def test_block_all_leaves_other_servers_alone(self):
        guard.TRACKER_MCP_POLICY = "block-all"
        code, err = self._call("mcp__other__getIssue")
        self.assertEqual(code, 0, err)

    def test_drafts_only_reads_pass_and_writes_block(self):
        code, err = self._call("mcp__tracker__getIssue")
        self.assertEqual(code, 0, err)
        code, err = self._call("mcp__tracker__createIssue")
        self.assertEqual(code, 2)
        self.assertIn("tracker/wiki write", err)

    def test_policy_value_is_trimmed_and_case_insensitive(self):
        guard.TRACKER_MCP_POLICY = " Block-All "
        code, err = self._call("mcp__tracker__getIssue")
        self.assertEqual(code, 2, err)

    def test_unknown_or_unsubstituted_policy_reads_as_drafts_only(self):
        for policy in ("whatever", "drafts-only", ""):
            guard.TRACKER_MCP_POLICY = policy
            code, err = self._call("mcp__tracker__getIssue")
            self.assertEqual(code, 0, f"{policy!r}: {err}")
            code, _ = self._call("mcp__tracker__createIssue")
            self.assertEqual(code, 2, policy)

    def test_claude_runtime_ignores_block_all(self):
        guard.TRACKER_MCP_POLICY = "block-all"
        code, _ = self._call("mcp__tracker__getIssue", runtime="claude")
        self.assertEqual(code, 0)


class Worktrees(unittest.TestCase):
    """A linked worktree's .git is a pointer file and the checkout can live anywhere.

    Both rules must follow the shared .git (`--git-common-dir`): a worktree of a client
    repo is a client repo wherever it was created, and a foreign repo's worktree stays
    none of our business. Without this, `git worktree add /tmp/x && cd /tmp/x` would
    be a clean exit from the guard.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo = make_repo(os.path.join(WORKSPACE_ROOT, "wt-client-repo"))
        cls.inside = os.path.join(WORKSPACE_ROOT, "worktrees", "wt-client-repo-PROJ-1")
        os.makedirs(os.path.dirname(cls.inside), exist_ok=True)
        subprocess.run(["git", "-C", cls.repo, "worktree", "add", cls.inside, "-b", "PROJ-1/slug"],
                       check=True, capture_output=True)
        cls.outside_dir = tempfile.mkdtemp(prefix="guard-wt-outside-")
        cls.outside = os.path.join(cls.outside_dir, "wt-elsewhere")
        subprocess.run(["git", "-C", cls.repo, "worktree", "add", cls.outside, "-b", "PROJ-2/slug"],
                       check=True, capture_output=True)
        cls.foreign_dir = tempfile.mkdtemp(prefix="guard-foreign-")
        cls.foreign = make_repo(os.path.join(cls.foreign_dir, "foreign"))
        cls.foreign_wt = os.path.join(cls.foreign_dir, "foreign-wt")
        subprocess.run(["git", "-C", cls.foreign, "worktree", "add", cls.foreign_wt, "-b", "x"],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        for d in (cls.outside_dir, cls.foreign_dir, cls.repo,
                  os.path.join(WORKSPACE_ROOT, "worktrees")):
            shutil.rmtree(d, ignore_errors=True)

    def assert_blocked(self, command, cwd):
        code, err = run_hook(command, cwd)
        self.assertEqual(code, 2, f"expected BLOCK for: {command} (cwd {cwd})\nstderr: {err}")

    def assert_allowed(self, command, cwd):
        code, err = run_hook(command, cwd)
        self.assertEqual(code, 0, f"expected ALLOW for: {command} (cwd {cwd})\nstderr: {err}")

    def test_the_worktree_really_has_a_pointer_file(self):
        # the premise of this class: no .git DIRECTORY to key off
        self.assertTrue(os.path.isfile(os.path.join(self.inside, ".git")))
        self.assertTrue(os.path.isfile(os.path.join(self.outside, ".git")))

    def test_worktree_under_the_workspace_is_covered_by_both_rules(self):
        for cmd in ("git push", "git commit -m x", "git reset --hard", "git checkout ."):
            self.assert_blocked(cmd, self.inside)
        code, err = run_hook("git add .claude/settings.json", self.inside)
        self.assertEqual(code, 2, err)
        self.assertIn("personal AI files", err)

    def test_worktree_outside_the_workspace_is_still_the_client_repo(self):
        # the checkout is in /tmp, but its .git points back into the workspace
        for cmd in ("git push", "git commit -m x", "git reset --hard"):
            self.assert_blocked(cmd, self.outside)
        code, err = run_hook("git add .claude/settings.json", self.outside)
        self.assertEqual(code, 2, err)
        self.assertIn("personal AI files", err)
        # and -C from anywhere resolves the same way
        self.assert_blocked(f"git -C {self.outside} push", self.foreign_dir)

    def test_a_foreign_worktree_is_none_of_our_business(self):
        for cmd in ("git push", "git commit -m x", "git add .claude/settings.json"):
            self.assert_allowed(cmd, self.foreign_wt)

    def test_worktree_remove_force_is_blocked_plain_remove_is_not(self):
        for cmd in ("git worktree remove --force ../worktrees/wt-client-repo-PROJ-1",
                    "git worktree remove -f ../worktrees/wt-client-repo-PROJ-1",
                    "git worktree remove ../worktrees/x --force"):
            self.assert_blocked(cmd, self.repo)
        for cmd in ("git worktree add ../worktrees/wt-client-repo-PROJ-3 -b PROJ-3/slug",
                    "git worktree list",
                    "git worktree prune",
                    "git worktree remove ../worktrees/wt-client-repo-PROJ-1",
                    "git worktree lock ../worktrees/x --reason forced-into-the-name"):
            self.assert_allowed(cmd, self.repo)


class FailClosed(unittest.TestCase):
    @staticmethod
    def _main_on(stdin_text, argv):
        """main() with stdin and argv both supplied.

        argv is explicit because main() defaults to sys.argv, which in-process is the
        test runner's own command line — argparse rejected the unknown arguments and
        exited before stdin was ever read, so this class tested nothing for a while.
        """
        err, old_stdin = io.StringIO(), sys.stdin
        sys.stdin = io.StringIO(stdin_text)
        try:
            with contextlib.redirect_stderr(err):
                code = guard.main(argv)
        finally:
            sys.stdin = old_stdin
        return code, err.getvalue()

    def test_unreadable_input_blocks(self):
        code, err = self._main_on("not json", [])
        self.assertEqual(code, 2)
        self.assertIn("blocking", err)

    def test_runtime_flag_reaches_the_hook_body(self):
        """--runtime is what makes Codex block tracker writes; parsing it is not decorative."""
        shipped = guard.TRACKER_MCP_PREFIX
        guard.TRACKER_MCP_PREFIX = "mcp__tracker__"
        payload = json.dumps({"tool_name": "mcp__tracker__createIssue",
                              "tool_input": {}, "cwd": WORKSPACE_ROOT})
        try:
            blocked, err = self._main_on(payload, ["--runtime", "codex"])
            passed, _ = self._main_on(payload, [])
        finally:
            guard.TRACKER_MCP_PREFIX = shipped
        self.assertEqual(blocked, 2, err)
        self.assertEqual(passed, 0)

    def test_non_bash_tools_pass_through(self):
        code, err = 0, io.StringIO()
        with contextlib.redirect_stderr(err):
            code = guard.run({"tool_name": "Read",
                              "tool_input": {"file_path": "/x"},
                              "cwd": WORKSPACE_ROOT})
        self.assertEqual(code, 0)


class InstalledPolicies(unittest.TestCase):
    """This file ships into every workspace, placeholders substituted in both files, and
    runs there against the installed CONFIG (onboard, kit-update, doctor). Every legal
    policy value must keep it green, or a policy the kit offers becomes a permanent
    doctor FAIL."""

    COMBOS = (("never", "never"), ("on-request", "never"), ("never", "on-request"),
              ("on-request", "on-request"), ("never", "auto"), ("on-request", "auto"))

    # built at runtime so the installer's own substitution cannot rewrite them; the
    # workspace values are dummies (the suite injects its own in memory) that make each
    # copy an installed one
    TOKEN = "{{" + "%s}}"

    @unittest.skipUnless(IS_TEMPLATE, "an installed copy: nothing left to substitute")
    def test_the_suite_is_green_under_every_legal_policy(self):
        here = os.path.dirname(os.path.realpath(__file__))
        for commit, push in self.COMBOS:
            with self.subTest(commit=commit, push=push):
                target = tempfile.mkdtemp(prefix="guard-install-")
                self.addCleanup(shutil.rmtree, target, True)
                values = {"COMMIT_POLICY": commit, "PUSH_POLICY": push,
                          "WORKSPACE_PATH": "/nonexistent-workspace",
                          "WORKSPACE_NAME": "InstalledWS"}
                for name in ("git-guard.py", "test_git_guard.py"):
                    with open(os.path.join(here, name), encoding="utf-8") as f:
                        text = f.read()
                    for key, value in values.items():
                        text = text.replace(self.TOKEN % key, value)
                    with open(os.path.join(target, name), "w", encoding="utf-8") as f:
                        f.write(text)
                r = subprocess.run([sys.executable, os.path.join(target, "test_git_guard.py")],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
