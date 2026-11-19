#!/usr/bin/env python3
"""Unit tests for doctor.py (kit version).
Run: python3 kit/skills/doctor/scripts/test_doctor.py

The doctor on disk carries unsubstituted placeholder CONFIG values. These tests import the
module and reassign the derived globals in memory; nothing on disk is substituted. Importing
doctor.py is side-effect free on purpose — everything above main() is definitions — and these
tests are the thing that keeps it that way.
"""
import contextlib, importlib.util, io, os, shutil, stat, subprocess, sys, tempfile, unittest

DOCTOR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "doctor.py")
DOCTOR_CODEX = os.path.join(os.path.dirname(os.path.realpath(__file__)), "doctor_codex.py")


def _load_doctor():
    spec = importlib.util.spec_from_file_location("doctor_under_test", DOCTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


doctor = _load_doctor()


def _load_doctor_codex():
    # A Claude-only build does not install the Codex companion. Loading it
    # unconditionally made the whole suite fail to import there, and the doctor turned
    # that into a FAIL of its own unit-test check.
    if not os.path.isfile(DOCTOR_CODEX):
        return None
    spec = importlib.util.spec_from_file_location("doctor_codex_under_test", DOCTOR_CODEX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


doctor_codex = _load_doctor_codex()

# --- two workspaces on one machine: the situation the real defect needs ------
WORKSPACES = tempfile.mkdtemp(prefix="doctor-workspaces-")
WS_A = os.path.join(WORKSPACES, "WorkspaceA")
WS_B = os.path.join(WORKSPACES, "WorkspaceB")


def tearDownModule():
    shutil.rmtree(WORKSPACES, ignore_errors=True)


def guard_path(ws):
    return os.path.join(ws, ".claude", "hooks", "git-guard.py")


def make_workspace(ws):
    os.makedirs(os.path.dirname(guard_path(ws)), exist_ok=True)
    with open(guard_path(ws), "w", encoding="utf-8") as fh:
        fh.write("# a stand-in for the guard; these tests never execute it\n")
    return ws


def point_doctor_at(ws):
    """Re-derive at runtime what import time derives from WORKSPACE_PATH.

    Every test must call this — whether from setUp or from the test body itself —
    before touching any other derived global; the isolation between test classes
    rests on that convention, not on anything enforced by the module itself.
    """
    doctor.WORKSPACE_ROOT = os.path.realpath(ws)
    doctor.GUARD_SOURCE = os.path.join(doctor.WORKSPACE_ROOT, ".claude", "hooks",
                                       doctor.GIT_GUARD_HOOK + ".py")


def registration(ws, interpreter=None):
    """One hook dict, spelled the way the kit's settings-workspace.json spells it: quoted,
    forward slashes.

    Defaults to the interpreter running the tests. check_registration probes whatever it
    finds here, and a made-up path would send it down the dead-interpreter branch with a
    30-second subprocess timeout on every call — a different check's failure mode leaking
    into these tests.
    """
    return {"type": "command",
            "command": '"%s" "%s"' % (interpreter or sys.executable,
                                      guard_path(ws).replace(os.sep, "/"))}


def settings_with(*hooks):
    """One PreToolUse entry per hook — the shape settings-workspace.json uses."""
    return {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [h]} for h in hooks]}}


@contextlib.contextmanager
def quiet():
    """The doctor prints as it checks; tests read `results`, not stdout."""
    doctor.results.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        yield doctor.results


class RegistrationIsPerWorkspace(unittest.TestCase):
    def setUp(self):
        make_workspace(WS_A)
        make_workspace(WS_B)
        point_doctor_at(WS_A)

    def match(self, settings):
        return doctor.registered_hook(settings, "PreToolUse",
                                      doctor._is_this_workspaces_guard)

    def test_another_workspaces_registration_is_not_ours(self):
        # The accident, exactly: B is registered, A is not, A's doctor is running.
        self.assertIsNone(self.match(settings_with(registration(WS_B))))

    def test_our_own_registration_is_found_among_foreign_ones(self):
        cmd = self.match(settings_with(registration(WS_B), registration(WS_A)))
        self.assertIn("WorkspaceA", cmd)

    def test_each_workspace_matches_only_itself(self):
        settings = settings_with(registration(WS_A), registration(WS_B))
        self.assertIn("WorkspaceA", self.match(settings))
        point_doctor_at(WS_B)
        self.assertIn("WorkspaceB", self.match(settings))

    def test_an_unregistered_machine_matches_nothing(self):
        self.assertIsNone(self.match({"hooks": {"PreToolUse": []}}))
        self.assertIsNone(self.match({}))
        self.assertIsNone(self.match(None))

    def test_a_hook_that_is_not_the_guard_is_not_a_match(self):
        other = {"type": "command", "command": '"%s" "/opt/lint/checker.py"' % sys.executable}
        self.assertIsNone(self.match(settings_with(other)))

    @unittest.skipUnless(os.name == "nt", "normcase only folds case on Windows")
    def test_case_differences_are_the_same_file_on_windows(self):
        shouty = {"type": "command",
                  "command": '"%s" "%s"' % (sys.executable,
                                            guard_path(WS_A).replace(os.sep, "/").upper())}
        self.assertIsNotNone(self.match(settings_with(shouty)))


class SymlinkedWorkspaces(unittest.TestCase):
    def setUp(self):
        make_workspace(WS_A)
        self.link = os.path.join(WORKSPACES, "link-to-a")
        if os.path.exists(self.link):
            return
        try:
            os.symlink(WS_A, self.link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as exc:
            if os.name == "nt" and subprocess.run(
                    ["cmd", "/c", "mklink", "/J", self.link, WS_A],
                    capture_output=True).returncode == 0:
                return
            self.skipTest("cannot create a symlink or junction here: %s" % exc)

    def test_a_workspace_reached_through_a_symlink_still_matches(self):
        # WORKSPACE_ROOT resolves the link; the registration carries the literal path.
        point_doctor_at(self.link)
        cmd = doctor.registered_hook(settings_with(registration(self.link)),
                                     "PreToolUse", doctor._is_this_workspaces_guard)
        self.assertIsNotNone(cmd)


class ForeignWorkspacesAreVisible(unittest.TestCase):
    def setUp(self):
        make_workspace(WS_A)
        make_workspace(WS_B)
        point_doctor_at(WS_A)

    def test_our_own_registration_is_not_foreign(self):
        self.assertEqual([], doctor.foreign_guard_registrations(
            settings_with(registration(WS_A))))

    def test_another_workspaces_guard_is_named(self):
        found = doctor.foreign_guard_registrations(
            settings_with(registration(WS_A), registration(WS_B)))
        self.assertEqual(1, len(found))
        self.assertIn("WorkspaceB", found[0])

    def test_an_unrelated_hook_is_not_a_kit_workspace(self):
        mine = {"type": "command", "command": '"%s" "/opt/lint/checker.py"' % sys.executable}
        self.assertEqual([], doctor.foreign_guard_registrations(settings_with(mine)))

    @unittest.skipUnless(os.name == "nt", "normcase only folds case on Windows")
    def test_a_differently_cased_foreign_path_is_still_foreign(self):
        shouty = {"type": "command",
                  "command": '"%s" "%s"' % (sys.executable,
                                            guard_path(WS_B).replace(os.sep, "/").upper())}
        found = doctor.foreign_guard_registrations(
            settings_with(registration(WS_A), shouty))
        self.assertEqual(1, len(found))


class NearMissRegistrationsAreNamedInTheFailure(unittest.TestCase):
    """A registration whose path is another workspace's — a copied workspace with a stale
    WORKSPACE_PATH — must FAIL and name the path it found, not just say "NOT registered"."""

    def setUp(self):
        make_workspace(WS_A)
        make_workspace(WS_B)
        point_doctor_at(WS_A)

    def test_a_near_miss_is_named_in_the_fail_text(self):
        with quiet() as results:
            doctor.check_registration(settings_with(registration(WS_B)))
        fails = [m for s, m, _ in results if s == "FAIL"]
        self.assertTrue(any("WorkspaceB" in m and "NOT registered" in m for m in fails))

    def test_a_matched_registration_is_not_failed_by_a_stranger_beside_it(self):
        with quiet() as results:
            guard = doctor.check_registration(settings_with(registration(WS_A), registration(WS_B)))
        self.assertIn("WorkspaceA", guard)
        self.assertFalse(any(s == "FAIL" for s, _, _ in results))

    def test_no_registrations_at_all_stays_the_plain_message(self):
        with quiet() as results:
            doctor.check_registration({"hooks": {"PreToolUse": []}})
        fails = [m for s, m, _ in results if s == "FAIL"]
        self.assertIn(f"{doctor.GIT_GUARD_HOOK} (PreToolUse/Bash) is NOT registered in "
                      ".claude/settings.local.json", fails)

    def test_a_missing_workspace_settings_file_is_a_fail_not_a_crash(self):
        with quiet() as results:
            self.assertIsNone(doctor.check_registration(None))
        self.assertTrue(any(s == "FAIL" for s, _, _ in results))


class ALegacyGlobalRegistrationIsAWarning(unittest.TestCase):
    """Earlier kit versions registered the guard in ~/.claude/settings.json. The workspace
    entry is the one that counts now; the global line is named as a leftover, by hand."""

    def setUp(self):
        make_workspace(WS_A)
        make_workspace(WS_B)
        point_doctor_at(WS_A)

    def test_a_global_guard_line_warns_and_does_not_fail(self):
        with quiet() as results:
            doctor.check_registration(settings_with(registration(WS_A)),
                                      settings_with(registration(WS_A)))
        self.assertTrue(any(s == "WARN" and "~/.claude/settings.json" in m for s, m, _ in results))
        self.assertFalse(any(s == "FAIL" for s, _, _ in results))

    def test_another_workspaces_global_line_is_also_named(self):
        with quiet() as results:
            doctor.check_registration(settings_with(registration(WS_A)),
                                      settings_with(registration(WS_B)))
        self.assertTrue(any(s == "WARN" and "WorkspaceB" in m for s, m, _ in results))

    def test_no_global_settings_means_no_warning(self):
        with quiet() as results:
            doctor.check_registration(settings_with(registration(WS_A)), None)
        self.assertFalse(any(s == "WARN" for s, _, _ in results))

    def test_an_unrelated_global_hook_is_not_a_leftover(self):
        mine = {"type": "command", "command": '"%s" "/opt/lint/checker.py"' % sys.executable}
        with quiet() as results:
            doctor.check_registration(settings_with(registration(WS_A)), settings_with(mine))
        self.assertFalse(any(s == "WARN" for s, _, _ in results))


class AttributionLivesInTheWorkspaceSettings(unittest.TestCase):
    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)

    def statuses(self, settings, local):
        with quiet() as results:
            doctor.check_git_hygiene(settings, local)
        return [(s, m) for s, m, _ in results if "includeCoAuthoredBy" in m]

    def test_false_in_the_workspace_file_passes(self):
        self.assertEqual(["PASS"], [s for s, _ in self.statuses({}, {"includeCoAuthoredBy": False})])

    def test_false_only_in_the_global_file_is_a_warning(self):
        self.assertEqual(["WARN"], [s for s, _ in self.statuses({"includeCoAuthoredBy": False}, {})])

    def test_absent_everywhere_fails(self):
        self.assertEqual(["FAIL"], [s for s, _ in self.statuses({}, {})])


class AnUppercaseExtensionIsStillOurScript(unittest.TestCase):
    """check_registration's own `script = next(... os.path.normcase(t).endswith(".py"))`
    is a second, independent case fold from the one _is_this_workspaces_guard uses. Without
    it, a shouty-cased registration is still matched as ours (that match goes through
    _same_path, unaffected), but the token that IS the script can no longer be picked out
    of argv, so the missing-file check silently never runs — a genuinely deleted script
    would read as a clean PASS instead of a FAIL."""

    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)

    @unittest.skipUnless(os.name == "nt", "normcase only folds case on Windows")
    def test_an_uppercase_py_extension_on_an_existing_script_is_not_a_false_fail(self):
        shouty = {"type": "command",
                  "command": '"%s" "%s"' % (sys.executable,
                                            guard_path(WS_A).replace(os.sep, "/").upper())}
        with quiet() as results:
            doctor.check_registration(settings_with(shouty))
        self.assertFalse(any(s == "FAIL" and "missing file" in m for s, m, _ in results))

    @unittest.skipUnless(os.name == "nt", "normcase only folds case on Windows")
    def test_an_uppercase_py_extension_on_a_missing_script_still_fails(self):
        os.remove(guard_path(WS_A))
        shouty = {"type": "command",
                  "command": '"%s" "%s"' % (sys.executable,
                                            guard_path(WS_A).replace(os.sep, "/").upper())}
        with quiet() as results:
            doctor.check_registration(settings_with(shouty))
        self.assertTrue(any(s == "FAIL" and "missing file" in m for s, m, _ in results),
                        "a script that genuinely does not exist must FAIL, extension "
                        "case notwithstanding")


class TheLiveFireCannotTargetAForeignGuard(unittest.TestCase):
    """check_guard_fires runs whatever check_registration handed it. When that was the
    first basename match, it could be another workspace's guard — which scopes itself to
    its own root, stays silent, and turned 'outside the workspace' into a PASS for a check
    that exercised nothing."""

    def setUp(self):
        make_workspace(WS_A)
        make_workspace(WS_B)
        point_doctor_at(WS_A)

    def test_a_foreign_registration_yields_no_live_fire_target(self):
        with quiet() as results:
            guard = doctor.check_registration(settings_with(registration(WS_B)))
        self.assertIsNone(guard)
        self.assertTrue(any(s == "FAIL" and "NOT registered" in m for s, m, _ in results),
                        "an unregistered workspace must FAIL, not pass on a neighbour")

    def test_without_a_target_the_live_fire_refuses_instead_of_passing(self):
        with quiet() as results:
            doctor.check_guard_fires(None)
        self.assertTrue(any(s == "FAIL" and "cannot live-fire" in m for s, m, _ in results))
        self.assertFalse(any(s == "PASS" for s, _, _ in results),
                         "nothing was fired, so nothing may report a pass")

    def test_our_own_registration_is_what_gets_handed_on(self):
        with quiet():
            guard = doctor.check_registration(
                settings_with(registration(WS_B), registration(WS_A)))
        self.assertIsNotNone(guard)
        self.assertIn("WorkspaceA", guard)


class TheDoctorWritesNothing(unittest.TestCase):
    """The doctor fixes nothing by design; the registration section reads the workspace
    and must never acquire a side effect on the way past."""

    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)

    @staticmethod
    def snapshot(root):
        return {os.path.join(base, name): os.stat(os.path.join(base, name)).st_size
                for base, _dirs, files in os.walk(root) for name in files}

    def test_check_registration_leaves_the_workspace_alone(self):
        before = self.snapshot(WS_A)
        with quiet():
            doctor.check_registration(settings_with(registration(WS_A)))
        self.assertEqual(before, self.snapshot(WS_A))


def guard_with(ws, *config_lines):
    """Overwrite the stand-in guard with a CONFIG block the policy reader can parse."""
    with open(guard_path(ws), "w", encoding="utf-8") as fh:
        fh.write("# stand-in guard\n" + "".join(line + "\n" for line in config_lines))


class PoliciesAreReadFromTheInstalledGuard(unittest.TestCase):
    """The doctor reports what is RUNNING, so both policies come out of the guard's
    CONFIG, and a guard from before a parameter existed reads as unknown, not as never."""

    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)

    def test_both_policies_are_read_independently(self):
        guard_with(WS_A, 'COMMIT_POLICY = "never"', 'PUSH_POLICY = "on-request"')
        self.assertEqual("never", doctor.installed_commit_policy())
        self.assertEqual("on-request", doctor.installed_push_policy())

    def test_anything_but_an_opened_value_reads_as_never(self):
        for value in ("never", "", "on_request", "never", "ALLOW", "always"):
            guard_with(WS_A, 'PUSH_POLICY = "%s"' % value)
            self.assertEqual("never", doctor.installed_push_policy(), value)
        guard_with(WS_A, "PUSH_POLICY = 'On-Request'")
        self.assertEqual("on-request", doctor.installed_push_policy())
        guard_with(WS_A, "PUSH_POLICY = ' Auto '")
        self.assertEqual("auto", doctor.installed_push_policy())

    def test_auto_is_a_push_value_only(self):
        guard_with(WS_A, 'COMMIT_POLICY = "auto"', 'PUSH_POLICY = "auto"')
        self.assertEqual("never", doctor.installed_commit_policy())
        self.assertEqual("auto", doctor.installed_push_policy())

    def test_a_guard_that_predates_the_parameter_is_unknown(self):
        guard_with(WS_A, 'COMMIT_POLICY = "never"')
        self.assertEqual("never", doctor.installed_commit_policy())
        self.assertIsNone(doctor.installed_push_policy())

    def test_a_missing_guard_is_unknown(self):
        os.remove(guard_path(WS_A))
        self.assertIsNone(doctor.installed_push_policy())


class WriteToolsAreJudgedByTheInstalledGuard(unittest.TestCase):
    """The allow-list check and the Codex hook must agree on what a write is, so the
    doctor asks the installed guard instead of keeping a verb list of its own."""

    KIT_GUARD = os.path.join(os.path.dirname(DOCTOR), "..", "..", "..", "hooks", "git-guard.py")

    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)

    def test_namespace_first_and_late_writes_are_caught(self):
        shutil.copy(self.KIT_GUARD, guard_path(WS_A))
        for operation, verb in (("jira_create_issue", "create"), ("markAsRead", "mark"),
                                ("createJiraIssue", "create")):
            self.assertEqual(verb, doctor.mcp_write_verb(operation), operation)
        for operation in ("getIssue", "jira_link_types_get", "getCreateMeta", "atlassianUserInfo"):
            self.assertIsNone(doctor.mcp_write_verb(operation), operation)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(guard_path(WS_A)),
                                                     "__pycache__")),
                         "loading the guard's classifier wrote bytecode into the workspace")

    def test_a_guard_without_the_classifier_falls_back_to_the_head_verbs(self):
        # make_workspace's stand-in has no _mcp_verb, like a guard from before it.
        self.assertEqual("create", doctor.mcp_write_verb("createIssue"))
        self.assertIsNone(doctor.mcp_write_verb("getIssue"))


def use_tracker_prefix(case, prefix):
    """Set the tracker prefix the way a substituted install carries it. The kit copy holds
    the literal token, which now means "no tracker", so every test that needs a tracker
    says which one."""
    previous = doctor.TRACKER_MCP_PREFIX, doctor.TRACKER_SERVER_NAME
    doctor.TRACKER_MCP_PREFIX = prefix
    doctor.TRACKER_SERVER_NAME = doctor.server_name_of(doctor.effective_prefix(prefix))
    case.addCleanup(lambda: setattr(doctor, "TRACKER_MCP_PREFIX", previous[0]))
    case.addCleanup(lambda: setattr(doctor, "TRACKER_SERVER_NAME", previous[1]))


class ExpectedMcpServersAreAList(unittest.TestCase):
    """The tracker used to be a hand-built block; a second expected server (a WARN one)
    must be an entry, not a copy of that block — and the tracker's lines must not move."""

    def setUp(self):
        use_tracker_prefix(self, "mcp__tracker__")

    DOCS = {"name": "Docs", "level": "WARN", "prefix": "mcp__docs__",
            "consequence": "library behavior is guessed from memory",
            "add_hint": "claude mcp add docs <server-url>"}

    def statuses(self, entry, servers, connectors=()):
        with quiet() as results:
            doctor.check_expected_mcp(entry, servers, set(connectors))
        return list(results)

    def tracker(self):
        return next(e for e in doctor.expected_mcp_servers()
                    if e["prefix"] == doctor.TRACKER_MCP_PREFIX)

    def test_the_tracker_is_the_only_entry_and_it_fails_hard(self):
        self.assertEqual([self.tracker()], doctor.expected_mcp_servers())
        self.assertEqual("FAIL", self.tracker()["level"])

    def test_a_mistyped_level_stays_fail_closed(self):
        results = self.statuses(dict(self.DOCS, level="Warn"), {})
        self.assertEqual(["FAIL"], [s for s, _, _ in results])

    def test_check_mcp_checks_every_entry(self):
        live = {doctor.TRACKER_SERVER_NAME: "✔ Connected"}
        original_live, original_build = doctor.live_mcp_servers, doctor.expected_mcp_servers
        doctor.live_mcp_servers = lambda: live
        doctor.expected_mcp_servers = lambda: original_build() + [self.DOCS]
        try:
            with quiet() as results:
                doctor.check_mcp({"permissions": {"deny": ["x"]}})
        finally:
            doctor.live_mcp_servers, doctor.expected_mcp_servers = original_live, original_build
        messages = [(s, m) for s, m, _ in results if "MCP s" in m]
        self.assertIn("PASS", [s for s, m in messages if doctor.TRACKER_NAME in m])
        self.assertEqual(["WARN"], [s for s, m in messages if "Docs" in m])

    def test_a_missing_fail_entry_fails_with_the_same_words_as_before(self):
        name, server = doctor.TRACKER_NAME, doctor.TRACKER_SERVER_NAME
        self.assertEqual(
            [("FAIL", f"no {name} MCP server — the {name} routes cannot run pre-flight",
              f"claude mcp add --transport http {server} <server-url> "
              f"&& /mcp   # OAuth is interactive, a human has to do it")],
            self.statuses(self.tracker(), {}))

    def test_a_missing_warn_entry_warns_and_fails_nothing(self):
        results = self.statuses(self.DOCS, {"other": "✔ Connected"})
        self.assertEqual(["WARN"], [s for s, _, _ in results])
        self.assertIn("library behavior is guessed from memory", results[0][1])
        self.assertEqual("claude mcp add docs <server-url>", results[0][2])

    def test_a_disconnected_warn_entry_warns(self):
        results = self.statuses(self.DOCS, {"docs": "✘ Failed to connect"})
        self.assertEqual(["WARN"], [s for s, _, _ in results])

    def test_a_disconnected_fail_entry_fails(self):
        results = self.statuses(self.tracker(), {doctor.TRACKER_SERVER_NAME: "✘ Failed to connect"})
        self.assertEqual(["FAIL"], [s for s, _, _ in results])

    def test_a_disconnected_connector_does_not_pass(self):
        connector = f"claude.ai {doctor.TRACKER_SERVER_NAME}"
        results = self.statuses(self.tracker(), {connector: "⚠ Needs authentication"}, (connector,))
        self.assertEqual(["FAIL"], [s for s, _, _ in results])

    def test_a_disconnected_tracker_keeps_the_same_words_as_before(self):
        name, server = doctor.TRACKER_NAME, doctor.TRACKER_SERVER_NAME
        for source, connectors, via in ((server, (), "registered server"),
                                        (f"claude.ai {server}", (f"claude.ai {server}",),
                                         "claude.ai connector")):
            self.assertEqual(
                [("FAIL", f"the only {name} MCP source ({source}, {via}) is ✘ Failed to connect — "
                          f"the {name} routes cannot run pre-flight",
                  "/mcp   # authenticate; OAuth is interactive, a human has to do it")],
                self.statuses(self.tracker(), {source: "✘ Failed to connect"}, connectors), via)

    def test_several_tracker_servers_keep_the_same_words_as_before(self):
        name, server = doctor.TRACKER_NAME, doctor.TRACKER_SERVER_NAME
        servers = {server: "✔ Connected", f"claude.ai {server}": "✔ Connected"}
        self.assertEqual(
            [("WARN", f"2 {name} MCP servers: {server}, claude.ai {server} — tool names "
                      f"differ per server, so the deny list may cover only one of them",
              "claude mcp list   # keep one, remove the rest, or extend deny to both prefixes")],
            self.statuses(self.tracker(), servers))

    def test_a_connected_tracker_names_its_source(self):
        name, server = doctor.TRACKER_NAME, doctor.TRACKER_SERVER_NAME
        self.assertEqual(
            [("PASS", f"exactly one {name} MCP source ({server}, registered server, ✔ Connected)", "")],
            self.statuses(self.tracker(), {server: "✔ Connected"}))

    def test_a_connected_entry_passes(self):
        for entry, servers, connectors in (
                (self.DOCS, {"docs": "✔ Connected"}, ()),
                (self.DOCS, {"claude.ai Docs": "✔ Connected"}, ("claude.ai Docs",))):
            results = self.statuses(entry, servers, connectors)
            self.assertEqual(["PASS"], [s for s, _, _ in results], servers)

    def test_two_matching_servers_warn_whatever_the_level(self):
        for entry, server in ((self.DOCS, "docs"), (self.tracker(), doctor.TRACKER_SERVER_NAME)):
            results = self.statuses(entry, {server: "✔ Connected",
                                            f"claude.ai {server}": "✔ Connected"})
            self.assertEqual(["WARN"], [s for s, _, _ in results], entry["name"])


class NoTrackerWorkspaceSkipsTheTrackerWiring(unittest.TestCase):
    NONE_LINE = "TRACKER_MCP_PREFIX=none — no tracker MCP expected; tracker wiring checks skipped"

    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)
        use_tracker_prefix(self, "none")
        self.addCleanup(setattr, doctor, "CLAUDE_JSON", doctor.CLAUDE_JSON)
        self.addCleanup(setattr, doctor, "live_mcp_servers", doctor.live_mcp_servers)
        doctor.CLAUDE_JSON = os.path.join(WORKSPACES, "no-claude.json")
        self.calls = 0

    def stub_live(self, servers):
        def live():
            self.calls += 1
            return servers
        doctor.live_mcp_servers = live

    def test_effective_prefix_follows_the_guards_rule(self):
        for raw in ("none", " NONE ", "", "   ", "none", None):
            self.assertEqual("", doctor.effective_prefix(raw), raw)
        self.assertEqual("mcp__atlassian__", doctor.effective_prefix(" mcp__atlassian__ "))

    def test_no_mcp_entries_means_no_tracker_source_line_and_no_listing_call(self):
        self.stub_live({"unrelated": "✔ Connected"})
        with quiet() as results:
            doctor.check_mcp({"permissions": {"allow": ["Bash(git status:*)"],
                                              "deny": ["Bash(git commit:*)"]}})
        self.assertEqual([], [r for r in results if r[0] in ("FAIL", "WARN")])
        self.assertEqual([("PASS", self.NONE_LINE, "")],
                         [r for r in results if "tracker" in r[1].lower() and "MCP" in r[1]])
        self.assertEqual(0, self.calls)
        self.assertFalse(any("MCP source" in m or "MCP server" in m for _, m, _ in results))

    def test_an_empty_deny_list_still_fails_without_naming_a_tracker(self):
        self.stub_live({})
        with quiet() as results:
            doctor.check_mcp({"permissions": {}})
        failures = [m for s, m, _ in results if s == "FAIL"]
        self.assertEqual(1, len(failures))
        self.assertIn("git deny entries are gone", failures[0])
        self.assertNotIn(doctor.TRACKER_NAME, failures[0])

    def test_a_stray_mcp_entry_for_a_missing_server_still_fails(self):
        self.stub_live({"other": "✔ Connected"})
        with quiet() as results:
            doctor.check_mcp({"permissions": {"deny": ["mcp__foo__bar"]}})
        self.assertEqual(1, self.calls)
        self.assertTrue(any(s == "FAIL" and "match nothing and enforce nothing" in m
                            for s, m, _ in results))

    def test_tool_prefixes_reads_server_level_and_tool_level_entries_alike(self):
        perms = {"deny": ["mcp__foo", "mcp__foo__bar"], "allow": ["mcp__my_srv__x"],
                 "ask": ["mcp__overmind"]}
        self.assertEqual({"foo", "my_srv", "overmind"}, doctor.tool_prefixes(perms))
        self.assertEqual({"foo"}, doctor.tool_prefixes({"deny": ["mcp__foo"]}))
        self.assertEqual({"foo"}, doctor.tool_prefixes({"deny": ["mcp__foo__bar"]}))

    def test_a_server_level_deny_entry_resolves_against_the_live_list(self):
        self.stub_live({"overmind": "✔ Connected"})
        with quiet() as results:
            doctor.check_mcp({"permissions": {"deny": ["mcp__overmind"]}})
        self.assertFalse(any(s == "FAIL" for s, _, _ in results))
        self.assertTrue(any("mcp__overmind__*" in m and s == "PASS" for s, m, _ in results))

    def test_the_tracker_policy_check_is_silent_without_a_tracker(self):
        with quiet() as results:
            doctor.check_tracker_policy({"permissions": {}})
        self.assertEqual([], results)


class TrackerMcpPolicyIsCrossCheckedAgainstThePermissionLayer(unittest.TestCase):
    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)
        use_tracker_prefix(self, "mcp__tracker__")

    def run_check(self, policy_line, permissions):
        if policy_line is None:
            guard_with(WS_A, 'PUSH_POLICY = "never"')
        else:
            guard_with(WS_A, policy_line)
        with quiet() as results:
            doctor.check_tracker_policy({"permissions": permissions})
        return [(s, m) for s, m, _ in results]

    BLOCK_ALL = 'TRACKER_MCP_POLICY = "block-all"'

    def test_block_all_fails_when_a_prefixed_entry_is_allowed_or_asked(self):
        for bucket in ("allow", "ask"):
            out = self.run_check(self.BLOCK_ALL, {bucket: ["mcp__tracker__getIssue"],
                                                  "deny": ["mcp__tracker"]})
            self.assertEqual(["FAIL"], [s for s, _ in out], bucket)

    def test_block_all_fails_when_deny_names_neither_server_nor_prefix(self):
        out = self.run_check(self.BLOCK_ALL, {"deny": ["Bash(git commit:*)"]})
        self.assertEqual(["FAIL"], [s for s, _ in out])
        self.assertIn("mcp__tracker", out[0][1])

    def test_block_all_passes_with_the_server_level_deny_entry(self):
        out = self.run_check(self.BLOCK_ALL, {"deny": ["mcp__tracker"]})
        self.assertEqual(["PASS"], [s for s, _ in out])
        self.assertIn("block-all", out[0][1])

    def test_block_all_passes_with_a_prefixed_deny_entry(self):
        out = self.run_check(self.BLOCK_ALL, {"deny": ["mcp__tracker__createIssue"]})
        self.assertEqual(["PASS"], [s for s, _ in out])

    def test_drafts_only_passes_and_changes_nothing_else(self):
        out = self.run_check('TRACKER_MCP_POLICY = "drafts-only"',
                             {"allow": ["mcp__tracker__getIssue"]})
        self.assertEqual(["PASS"], [s for s, _ in out])
        self.assertIn("drafts-only", out[0][1])

    def test_an_unrecognised_value_warns_and_names_it(self):
        out = self.run_check('TRACKER_MCP_POLICY = "Strict"', {})
        self.assertEqual(["WARN"], [s for s, _ in out])
        self.assertIn("strict", out[0][1])
        self.assertIn("drafts-only", out[0][1])

    def test_a_guard_without_the_parameter_warns(self):
        out = self.run_check(None, {})
        self.assertEqual(["WARN"], [s for s, _ in out])
        self.assertIn("TRACKER_MCP_POLICY", out[0][1])

    def test_the_probes_no_longer_interpolate_a_ticket_key_pattern(self):
        with open(DOCTOR, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("TICKET_KEY", text)


@unittest.skipIf(doctor_codex is None, "Codex companion not installed in this build")
class CodexMatcherFollowsTheTrackerSetting(unittest.TestCase):
    def test_none_accepts_exactly_bash(self):
        self.assertIsNone(doctor_codex.matcher_problem("Bash", ""))

    def test_none_rejects_a_matcher_that_still_routes_mcp(self):
        self.assertIn("Bash", doctor_codex.matcher_problem("Bash|mcp__x__.*", ""))

    def test_a_real_prefix_must_appear_in_the_matcher(self):
        self.assertIsNone(doctor_codex.matcher_problem("Bash|mcp__x__.*", "mcp__x__"))
        self.assertIn("mcp__x__", doctor_codex.matcher_problem("Bash", "mcp__x__"))

    def test_the_registration_returns_the_matcher_with_the_command(self):
        previous = doctor_codex.GUARD
        self.addCleanup(setattr, doctor_codex, "GUARD", previous)
        make_workspace(WS_A)
        doctor_codex.GUARD = guard_path(WS_A)
        command = '"%s" "%s"' % (sys.executable, guard_path(WS_A).replace(os.sep, "/"))
        config = {"hooks": {"PreToolUse": [{"matcher": "Bash|mcp__x__.*",
                                            "hooks": [{"command": command}]}]}}
        self.assertEqual((command, "Bash|mcp__x__.*"), doctor_codex.hook_registration(config))
        self.assertEqual((None, None), doctor_codex.hook_registration({}))

    def test_the_tracker_policy_fails_open_to_drafts_only(self):
        previous = doctor_codex.GUARD
        self.addCleanup(setattr, doctor_codex, "GUARD", previous)
        make_workspace(WS_A)
        doctor_codex.GUARD = guard_path(WS_A)
        for line, expected in (('TRACKER_MCP_POLICY = "block-all"', "block-all"),
                               ('TRACKER_MCP_POLICY = "weird"', "drafts-only"),
                               ('PUSH_POLICY = "never"', "drafts-only")):
            guard_with(WS_A, line)
            self.assertEqual(expected, doctor_codex.installed_tracker_policy(), line)
        os.remove(guard_path(WS_A))
        self.assertEqual("drafts-only", doctor_codex.installed_tracker_policy())


@unittest.skipIf(doctor_codex is None, "Codex companion not installed in this build")
class CodexPublicationPolicy(unittest.TestCase):
    def setUp(self):
        make_workspace(WS_A)
        self.previous_guard = doctor_codex.GUARD
        self.previous_root = doctor_codex.WORKSPACE_ROOT
        self.plan = os.path.join(WS_A, "WorkspaceA-SETUP-PLAN.md")
        if os.path.exists(self.plan):
            os.remove(self.plan)
        doctor_codex.GUARD = guard_path(WS_A)
        doctor_codex.WORKSPACE_ROOT = WS_A

    def tearDown(self):
        doctor_codex.GUARD = self.previous_guard
        doctor_codex.WORKSPACE_ROOT = self.previous_root
        if os.path.exists(self.plan):
            os.remove(self.plan)

    def test_auto_is_the_only_codex_value_that_opens_publication(self):
        for value, expected in (("auto", "auto"), (" Auto ", "auto"),
                                ("on-request", "on-request"), ("never", "never"),
                                ("never", "never")):
            guard_with(WS_A, f'PUSH_POLICY = "{value}"')
            self.assertEqual(expected, doctor_codex.installed_push_policy(), value)

    def test_an_older_or_missing_guard_fails_closed(self):
        guard_with(WS_A, 'COMMIT_POLICY = "never"')
        self.assertEqual("never", doctor_codex.installed_push_policy())
        os.remove(guard_path(WS_A))
        self.assertEqual("never", doctor_codex.installed_push_policy())

    def test_auto_requires_a_real_recorded_code_host_gate(self):
        for value in ("", "<FILL: rules>", "nothing", "none", "-", "—"):
            with open(self.plan, "w", encoding="utf-8") as handle:
                handle.write(f"| What protects the default branch | {value} |\n")
            self.assertIsNone(doctor_codex.recorded_branch_protection(), value)
        with open(self.plan, "w", encoding="utf-8") as handle:
            handle.write("| What protects the default branch | required CI + 1 approval |\n")
        self.assertEqual("required CI + 1 approval",
                         doctor_codex.recorded_branch_protection())


class ThePushPolicyIsCrossCheckedAgainstThePermissionLayer(unittest.TestCase):
    """Same contract as the commit policy: under on-request the `ask` prompt is the only
    approval left, so it must exist and must actually prompt; under never a prompt is not
    a gate and the entries belong in deny."""

    PUSH = {"Bash(git push)", "Bash(git push:*)"}

    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)

    def run_check(self, policy, bucket, mode=None):
        guard_with(WS_A, 'PUSH_POLICY = "%s"' % policy)
        local = {"permissions": {bucket: sorted(self.PUSH)}} if bucket else {"permissions": {}}
        settings = {"permissions": {"defaultMode": mode}} if mode else {}
        with quiet() as results:
            doctor.check_push_policy(settings, local)
        return [(s, m) for s, m, _ in results]

    def statuses(self, *a, **kw):
        return [s for s, _ in self.run_check(*a, **kw)]

    def test_on_request_with_ask_and_real_prompts_passes(self):
        self.assertEqual(["PASS"], self.statuses("on-request", "ask", "default"))

    def test_on_request_under_an_auto_approving_mode_fails(self):
        for mode in ("acceptEdits", "auto", "bypassPermissions"):
            out = self.run_check("on-request", "ask", mode)
            self.assertEqual(["FAIL"], [s for s, _ in out], mode)
            self.assertIn("pushes unasked", out[0][1])

    def test_on_request_with_push_in_allow_fails(self):
        self.assertEqual(["FAIL"], self.statuses("on-request", "allow", "default"))

    def test_on_request_with_push_denied_warns(self):
        self.assertEqual(["WARN"], self.statuses("on-request", "deny", "default"))

    def test_on_request_with_no_bucket_warns(self):
        self.assertEqual(["WARN"], self.statuses("on-request", None, "default"))

    def test_never_with_push_denied_passes(self):
        self.assertEqual(["PASS"], self.statuses("never", "deny", "default"))

    def test_never_with_push_in_ask_warns(self):
        self.assertEqual(["WARN"], self.statuses("never", "ask", "default"))

    def test_never_with_push_in_allow_fails(self):
        self.assertEqual(["FAIL"], self.statuses("never", "allow", "default"))

    def test_an_older_guard_without_the_parameter_warns_and_points_at_the_kit(self):
        guard_with(WS_A, 'COMMIT_POLICY = "never"')
        with quiet() as results:
            doctor.check_push_policy({}, {"permissions": {"deny": sorted(self.PUSH)}})
        # the WARN names the missing parameter; the layer check then runs as `never`,
        # which is what an older guard actually enforces
        self.assertEqual(["WARN", "PASS"], [s for s, _, _ in results])
        self.assertIn("PUSH_POLICY", results[0][1])
        self.assertIn("update it from the kit", results[0][2])

    # --- auto: no prompt by design; the code host's branch protection is the gate ---

    PLAN = os.path.join(WS_A, "Smoke-SETUP-PLAN.md")

    def plan_with(self, protection):
        row = "" if protection is None else "| %s | %s |\n" % (doctor.BRANCH_PROTECTION_ROW, protection)
        with open(self.PLAN, "w", encoding="utf-8") as fh:
            fh.write("# plan\n\n| Fact | Value |\n|---|---|\n| Workspace root | x |\n" + row)
        self.addCleanup(self.drop_plan)

    def drop_plan(self):
        if os.path.exists(self.PLAN):
            os.remove(self.PLAN)

    def test_auto_with_allow_and_a_recorded_code_host_gate_passes(self):
        self.plan_with("protected main: 1 approval + green CI required")
        out = self.run_check("auto", "allow", "auto")
        self.assertEqual(["PASS"], [s for s, _ in out])
        self.assertIn("green CI", out[0][1])

    def test_auto_does_not_care_about_the_permission_mode(self):
        self.plan_with("protected main")
        for mode in ("default", "acceptEdits", "bypassPermissions", None):
            self.assertEqual(["PASS"], self.statuses("auto", "allow", mode), mode)

    def test_auto_without_a_recorded_gate_fails(self):
        for plan in (None, "<FILL: branch protection>", "", "nothing"):
            if plan is None:
                self.drop_plan()
            else:
                self.plan_with(plan)
            out = self.run_check("auto", "allow", "default")
            self.assertEqual(["FAIL"], [s for s, _ in out], repr(plan))
            self.assertIn("protects the default branch", out[0][1])

    def test_auto_with_push_denied_fails(self):
        self.plan_with("protected main")
        self.assertEqual(["FAIL"], self.statuses("auto", "deny", "default"))

    def test_auto_with_push_in_ask_warns(self):
        self.plan_with("protected main")
        self.assertEqual(["WARN"], self.statuses("auto", "ask", "default"))

    def test_a_missing_plan_reads_as_no_recorded_gate(self):
        self.assertIsNone(doctor.recorded_branch_protection())

    def test_the_commit_check_still_speaks_about_commits(self):
        guard_with(WS_A, 'COMMIT_POLICY = "on-request"', 'PUSH_POLICY = "never"')
        with quiet() as results:
            doctor.check_commit_policy({"permissions": {"defaultMode": "auto"}},
                                       {"permissions": {"ask": ["Bash(git commit)",
                                                                "Bash(git commit:*)"]}})
        self.assertEqual(["FAIL"], [s for s, _, _ in results])
        self.assertIn("commits unasked", results[0][1])


class SandboxRemovalSurvivesReadOnlyObjects(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="doctor-remove-")
        self.addCleanup(shutil.rmtree, self.base, True)

    @staticmethod
    def _read_only_file(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("x")
        os.chmod(path, stat.S_IREAD)

    def test_read_only_files_are_removed(self):
        tree = os.path.join(self.base, "tree")
        self._read_only_file(os.path.join(tree, "top.txt"))
        self._read_only_file(os.path.join(tree, "a", "b", "nested.txt"))
        self.assertTrue(doctor.remove_tree(tree))
        self.assertFalse(os.path.exists(tree))

    def test_a_real_git_repo_is_removed(self):
        repo = os.path.join(self.base, "repo")
        with quiet():
            doctor.make_sandbox_repo(repo)
        self.assertTrue(os.path.isdir(os.path.join(repo, ".git")))
        self.assertTrue(doctor.remove_tree(repo))
        self.assertFalse(os.path.exists(repo))

    def test_a_missing_path_counts_as_gone(self):
        self.assertTrue(doctor.remove_tree(os.path.join(self.base, "never-existed")))

    def test_a_survivor_is_a_fail_naming_the_path(self):
        doctor.SANDBOX = os.path.join(self.base, "sandbox")
        doctor.OUTSIDE_SANDBOX = os.path.join(self.base, "outside")
        real = doctor.remove_tree
        doctor.remove_tree = lambda path, causes=None: False
        self.addCleanup(setattr, doctor, "remove_tree", real)
        with quiet() as results:
            doctor.remove_sandboxes()
        self.assertEqual(["FAIL", "FAIL"], [s for s, _, _ in results])
        self.assertIn("sandbox survived removal: " + doctor.SANDBOX, results[0][1])
        self.assertIn("rm -rf " + doctor.SANDBOX, results[0][2])
        self.assertNotIn("(", results[0][1])

    def test_a_survivor_carries_the_exception_that_stopped_rmtree(self):
        doctor.SANDBOX = os.path.join(self.base, "sandbox")
        doctor.OUTSIDE_SANDBOX = os.path.join(self.base, "outside")
        real = doctor.remove_tree

        def stubborn(path, causes=None):
            causes.append("PermissionError: held open")
            return False

        doctor.remove_tree = stubborn
        self.addCleanup(setattr, doctor, "remove_tree", real)
        with quiet() as results:
            doctor.remove_sandboxes()
        self.assertTrue(results[0][1].endswith("(PermissionError: held open)"))

    def test_remove_tree_hands_back_the_exception_it_swallowed(self):
        tree = os.path.join(self.base, "tree")
        os.makedirs(tree)
        real = shutil.rmtree

        def refuse(path, **kwargs):
            raise PermissionError("held open")

        shutil.rmtree = refuse
        self.addCleanup(setattr, shutil, "rmtree", real)
        causes = []
        self.assertFalse(doctor.remove_tree(tree, causes))
        self.assertEqual(["PermissionError: held open"], causes)

    def test_nothing_is_reported_when_both_are_gone(self):
        doctor.SANDBOX = os.path.join(self.base, "sandbox")
        doctor.OUTSIDE_SANDBOX = os.path.join(self.base, "outside")
        os.makedirs(doctor.SANDBOX)
        with quiet() as results:
            doctor.remove_sandboxes()
        self.assertEqual([], results)


class ASurvivingSandboxFailsTheRun(unittest.TestCase):
    CHECKS = ("check_registration", "check_guard_fires", "check_own_tests",
              "check_git_hygiene", "check_mcp", "check_commit_policy",
              "check_push_policy", "check_tracker_policy", "check_prompt_mode",
              "check_policy", "check_index_size", "load_json", "remove_tree")

    def test_main_reports_both_survivors_in_the_summary_and_exits_nonzero(self):
        ws = tempfile.mkdtemp(prefix="doctor-main-")
        self.addCleanup(shutil.rmtree, ws, True)
        point_doctor_at(ws)
        doctor.SANDBOX = os.path.join(ws, "sandbox")
        doctor.OUTSIDE_SANDBOX = os.path.join(ws, "outside")
        for name in self.CHECKS:
            self.addCleanup(setattr, doctor, name, getattr(doctor, name))
            setattr(doctor, name, lambda *args, **kwargs: None)
        doctor.load_json = lambda path: {}
        doctor.remove_tree = lambda path, causes=None: False
        doctor.results.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor.main()
        text = out.getvalue()
        self.assertEqual(1, code)
        self.assertIn("0 pass \u00b7 0 warn \u00b7 2 fail", text)
        self.assertIn("[FAIL] sandbox survived removal: " + doctor.SANDBOX, text)
        self.assertIn("rm -rf " + doctor.OUTSIDE_SANDBOX, text)


class ClaudeMdIsHeldToTheLineCap(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="doctor-cap-")
        self.addCleanup(shutil.rmtree, self.ws, True)
        point_doctor_at(self.ws)

    def _write(self, name, count, first="# index"):
        lines = [first] + ["line %d" % i for i in range(count - 1)]
        with open(os.path.join(self.ws, name), "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def test_exactly_the_cap_passes(self):
        self._write("CLAUDE.md", 150)
        with quiet() as results:
            doctor.check_index_size()
        self.assertEqual(["PASS"], [s for s, _, _ in results])
        self.assertIn("150 lines (cap 150)", results[0][1])

    def test_one_over_warns_by_one(self):
        self._write("CLAUDE.md", 151)
        with quiet() as results:
            doctor.check_index_size()
        self.assertEqual(["WARN"], [s for s, _, _ in results])
        self.assertIn("over the 150-line cap by 1", results[0][1])

    def test_a_missing_file_is_silent(self):
        with quiet() as results:
            doctor.check_index_size()
        self.assertEqual([], results)

    def test_a_trailing_newline_is_not_a_line(self):
        for ending in ("", "\n"):
            body = "\n".join("l%d" % i for i in range(150)) + ending
            with open(os.path.join(self.ws, "CLAUDE.md"), "w", encoding="utf-8",
                      newline="") as handle:
                handle.write(body)
            with quiet() as results:
                doctor.check_index_size()
            self.assertEqual(["PASS"], [s for s, _, _ in results], repr(ending))
            self.assertIn("150 lines", results[0][1])

    def test_a_form_feed_inside_a_line_does_not_split_it(self):
        with open(os.path.join(self.ws, "CLAUDE.md"), "w", encoding="utf-8",
                  newline="") as handle:
            handle.write("\n".join(["a\x0cb"] * 150) + "\n")
        with quiet() as results:
            doctor.check_index_size()
        self.assertEqual(["PASS"], [s for s, _, _ in results])
        self.assertIn("150 lines", results[0][1])


@unittest.skipIf(doctor_codex is None, "Claude-only build")
class AgentsMdBodyIsHeldToTheLineCap(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="doctor-codex-cap-")
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.claude = os.path.join(self.ws, "CLAUDE.md")
        self.agents = os.path.join(self.ws, "AGENTS.md")

    def _pair(self, body, header=4, first="# index"):
        body_lines = [first] + ["line %d" % i for i in range(body - 1)]
        with open(self.claude, "w", encoding="utf-8") as handle:
            handle.write("\n".join(body_lines) + "\n")
        head = ["generated %d" % i for i in range(header)]
        with open(self.agents, "w", encoding="utf-8") as handle:
            handle.write("\n".join(head + body_lines) + "\n")

    def _run_main(self):
        self.addCleanup(setattr, doctor_codex, "WORKSPACE_ROOT", doctor_codex.WORKSPACE_ROOT)
        self.addCleanup(setattr, doctor_codex.shutil, "which", doctor_codex.shutil.which)
        doctor_codex.WORKSPACE_ROOT = self.ws
        doctor_codex.shutil.which = lambda name: None
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor_codex.main()
        return code, out.getvalue()

    def test_main_prints_the_warning_and_counts_it_in_the_summary(self):
        self._pair(151)
        code, output = self._run_main()
        self.assertIn("WARN AGENTS.md is 155 lines", output)
        self.assertRegex(output, r"\d+ Codex failure\(s\) \u00b7 1 warning\(s\)")
        self.assertNotIn("PASS AGENTS.md is", output)

    def test_main_prints_a_pass_without_a_warning_inside_the_cap(self):
        self._pair(150)
        code, output = self._run_main()
        self.assertIn("PASS AGENTS.md is 154 lines", output)
        self.assertRegex(output, r"\u00b7 0 warning\(s\)")

    def test_header_plus_150_passes(self):
        self._pair(150)
        message, over = doctor_codex.index_size_report(self.claude, self.agents)
        self.assertFalse(over)
        self.assertIn("CLAUDE.md body 150 after a 4-line generated header", message)

    def test_header_plus_151_warns(self):
        self._pair(151)
        message, over = doctor_codex.index_size_report(self.claude, self.agents)
        self.assertTrue(over)
        self.assertIn("over the 150-line cap by 1", message)

    def test_an_undelimited_body_warns(self):
        self._pair(10)
        os.remove(self.claude)
        message, over = doctor_codex.index_size_report(self.claude, self.agents)
        self.assertTrue(over)
        self.assertIn("could not be delimited", message)

    def test_a_tail_that_is_not_claude_md_warns_it_cannot_delimit(self):
        self._pair(10)
        with open(self.agents, "w", encoding="utf-8") as handle:
            handle.write("unrelated\n")
        message, over = doctor_codex.index_size_report(self.claude, self.agents)
        self.assertTrue(over)
        self.assertIn("could not be delimited", message)
        self.assertIn("regenerate the mirror", message)

    def test_a_blank_first_line_still_delimits_the_body(self):
        self._pair(150, first="")
        message, over = doctor_codex.index_size_report(self.claude, self.agents)
        self.assertFalse(over)
        self.assertIn("CLAUDE.md body 150 after a 4-line generated header", message)

    def test_a_first_line_equal_to_a_header_line_still_delimits(self):
        self._pair(150, first="generated 1")
        message, over = doctor_codex.index_size_report(self.claude, self.agents)
        self.assertFalse(over)
        self.assertIn("CLAUDE.md body 150 after a 4-line generated header", message)

    def test_a_trailing_newline_does_not_add_a_line(self):
        self._pair(150)
        for path in (self.claude, self.agents):
            with open(path, encoding="utf-8") as handle:
                text = handle.read().rstrip("\n")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
        message, over = doctor_codex.index_size_report(self.claude, self.agents)
        self.assertFalse(over)
        self.assertIn("AGENTS.md is 154 lines", message)

    def test_a_missing_agents_file_reports_nothing(self):
        self.assertIsNone(doctor_codex.index_size_report(self.claude, self.agents))


class TheDoctorTestsItself(unittest.TestCase):
    def setUp(self):
        make_workspace(WS_A)
        point_doctor_at(WS_A)
        self.original = doctor.DOCTOR_TESTS
        self.addCleanup(setattr, doctor, "DOCTOR_TESTS", self.original)
        prior = os.environ.pop("DOCTOR_SELF_TEST", None)
        if prior is None:
            self.addCleanup(os.environ.pop, "DOCTOR_SELF_TEST", None)
        else:
            self.addCleanup(os.environ.__setitem__, "DOCTOR_SELF_TEST", prior)

    def _stub(self, name, body):
        path = os.path.join(WORKSPACES, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        doctor.DOCTOR_TESTS = path
        return path

    def test_doctor_tests_is_derived_from_file_not_workspace_root(self):
        # point_doctor_at(WS_A) above moved WORKSPACE_ROOT; DOCTOR_TESTS must not have
        # followed it — it is this test file's own sibling on disk, which is the
        # entire reason it keeps resolving when WORKSPACE_PATH is wrong.
        expected = os.path.join(os.path.dirname(os.path.realpath(DOCTOR)), "test_doctor.py")
        self.assertEqual(os.path.realpath(expected), os.path.realpath(self.original))

    def test_green_tests_report_the_count(self):
        self._stub("stub_pass.py", 'import sys\nsys.stderr.write("Ran 42 tests\\n")\n')
        with quiet() as results:
            doctor.check_own_tests()
        self.assertTrue(any(s == "PASS" and "42" in m for s, m, _ in results))

    def test_failing_tests_are_a_FAIL_not_a_warning(self):
        self._stub("stub_fail.py", "import sys\nsys.exit(1)\n")
        with quiet() as results:
            doctor.check_own_tests()
        self.assertTrue(any(s == "FAIL" for s, _, _ in results))

    def test_missing_tests_warn_rather_than_pass(self):
        doctor.DOCTOR_TESTS = os.path.join(WORKSPACES, "no-such-test-file.py")
        with quiet() as results:
            doctor.check_own_tests()
        self.assertEqual(["WARN"], [s for s, _, _ in results])

    def test_the_recursion_guard_short_circuits(self):
        self._stub("stub_should_not_run.py", "raise SystemExit(1)\n")
        os.environ["DOCTOR_SELF_TEST"] = "1"
        self.addCleanup(os.environ.pop, "DOCTOR_SELF_TEST", None)
        with quiet() as results:
            doctor.check_own_tests()
        self.assertEqual([], results)

    def test_the_child_run_actually_carries_the_recursion_guard(self):
        # If check_own_tests ever stopped passing DOCTOR_SELF_TEST into the child's
        # environment, this stub would see it unset and exit 1 — a FAIL, not a silent
        # PASS — so the "structurally cannot recurse" claim has something behind it.
        self._stub("stub_needs_env.py",
                    'import os, sys\n'
                    'sys.exit(0 if os.environ.get("DOCTOR_SELF_TEST") == "1" else 1)\n')
        with quiet() as results:
            doctor.check_own_tests()
        self.assertTrue(any(s == "PASS" for s, _, _ in results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
