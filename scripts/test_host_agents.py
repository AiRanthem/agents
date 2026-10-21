import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("host_agents", Path(__file__).with_name("host_agents.py"))
host_agents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_agents)


def install_fixture(home, host):
    agents = home / f".{host}" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name in host_agents.ROLES:
        source, _, _ = host_agents.role_config(host, name)
        target = agents / source.name
        target.write_bytes(source.read_bytes())
    skill_root = home / ".agents" / "skills"
    skill_root.mkdir(parents=True, exist_ok=True)
    for name in host_agents.SKILLS:
        link = skill_root / name
        expected = host_agents.ROOT / "skills" / name
        if not link.is_symlink() or link.resolve() != expected.resolve():
            link.symlink_to(expected)
    if host == "qoder":
        hooks = home / ".qoder" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        target = hooks / "session-identity.py"
        if not target.exists():
            target.symlink_to(host_agents.ROOT / "qoder" / "hooks" / target.name)
        (home / ".qoder" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": "python3 ~/.qoder/hooks/session-identity.py", "timeout": 10}]}]}}))
    return agents, skill_root


class HostAgentTests(unittest.TestCase):


    def test_missing_installation_reports_roles_and_skill_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            for host in ("codex", "qoder"):
                result = host_agents.check(host, Path(temp))
                self.assertFalse(result["disk_ready"])
                self.assertFalse(result["runtime_verified"])
                self.assertEqual(len(result["missing"]), 4 + len(host_agents.SKILLS) + (2 if host == "qoder" else 0))
                self.assertFalse(list(Path(temp).iterdir()))

    def test_installed_agents_are_ready_and_local_modification_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            for host in ("codex", "qoder"):
                agents, _ = install_fixture(home, host)
                self.assertTrue(host_agents.check(host, home)["disk_ready"])
                target = next(agents.iterdir())
                content = target.read_text()
                target.unlink()
                target.write_text(content + "\nLocal custom instruction\n")
                result = host_agents.check(host, home)
                self.assertFalse(result["disk_ready"])
                self.assertEqual(len(result["missing"]), 1)
                self.assertIn("differs", result["missing"][0])
                self.assertEqual(target.read_text(), content + "\nLocal custom instruction\n")

    def test_wrong_skill_link_and_regular_copy_are_rejected(self):
        for host in ("codex", "qoder"):
            for kind in ("wrong-link", "regular-copy"):
                with self.subTest(host=host, kind=kind), tempfile.TemporaryDirectory() as temp:
                    home = Path(temp)
                    _, skill_root = install_fixture(home, host)
                    self.assertTrue(host_agents.check(host, home)["disk_ready"])
                    target = skill_root / "advance-project"
                    content = (target / "SKILL.md").read_text()
                    target.unlink()
                    if kind == "wrong-link":
                        stale = home / "old-devkit-skill"
                        stale.mkdir()
                        (stale / "SKILL.md").write_text(content)
                        target.symlink_to(stale)
                    else:
                        target.mkdir()
                        (target / "SKILL.md").write_text(content)
                    result = host_agents.check(host, home)
                    self.assertFalse(result["disk_ready"])
                    self.assertEqual(len(result["missing"]), 1)
                    self.assertIn("skill must link to repository directory", result["missing"][0])
                    self.assertEqual((target / "SKILL.md").read_text(), content)

    def test_native_file_role_symlink_is_not_native_discovery_readiness(self):
        for host in ("codex", "qoder"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                agents, _ = install_fixture(home, host)
                name = "project-design-reviewer"
                source, _, _ = host_agents.role_config(host, name)
                target = agents / source.name
                target.unlink()
                target.symlink_to(source)
                result = host_agents.check(host, home)
                self.assertFalse(result["disk_ready"])
                self.assertEqual(len(result["missing"]), 1)
                self.assertIn("regular", result["missing"][0])

    def test_role_output_preserves_complete_instructions_and_fixed_profiles(self):
        for name in host_agents.ROLES:
            reviewer = "reviewer" in name
            for host in ("codex", "qoder"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = host_agents.main(["role", "--host", host, "--name", name])
                self.assertEqual(result, 0)
                role = json.loads(output.getvalue())
                if host == "qoder":
                    self.assertEqual(list(role), [name])
                    role = role[name]
                    self.assertNotIn("developer_instructions", role)
                    self.assertIsInstance(role["maxTurns"], int)
                else:
                    self.assertEqual(role["name"], name)
                if host == "codex":
                    self.assertEqual(role["model"], "gpt-6.1-sol")
                    self.assertEqual(role["model_reasoning_effort"], "xhigh" if reviewer else "medium")
                else:
                    self.assertEqual(role["model"], "qmodel_38max" if reviewer else "dfmodel")
                    self.assertEqual(role["effort"], "xhigh" if reviewer else "max")
                body = role["prompt"] if host == "qoder" else role["developer_instructions"]
                self.assertIn("references/stage-executor.md", body)
                if host == "qoder":
                    self.assertIn("advance-project", body)
                    self.assertNotIn("freely delegate", body)
                else:
                    self.assertIn("direct stage assignment", body)
                    self.assertIn("freely delegate", body)
                self.assertNotIn("composer-2.5", body)
                if name == "project-implementation-reviewer":
                    self.assertIn("single-agent", body)
                    self.assertNotIn("independent code-quality subagent must actually run", body)

    def test_qoder_settings_and_identity_hook_checks_are_read_only_and_host_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            install_fixture(home, "codex")
            install_fixture(home, "qoder")
            path = home / ".qoder" / "settings.json"
            settings = json.loads(path.read_text())
            for override in ({"enabled": False}, {"modelConfig": {"model": "inherit"}},
                             {"runConfig": {"maxTurns": 4}}):
                with self.subTest(override=override):
                    settings["agents"] = {"overrides": {"project-implementer": override}}
                    path.write_text(json.dumps(settings))
                    before = path.read_bytes()
                    result = host_agents.check("qoder", home)
                    self.assertFalse(result["disk_ready"])
                    self.assertEqual(len(result["missing"]), 1)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertTrue(host_agents.check("codex", home)["disk_ready"])
            settings["agents"] = {"overrides": {"project-implementer": {"modelConfig": {"model": "dfmodel"}}}}
            path.write_text(json.dumps(settings))
            self.assertTrue(host_agents.check("qoder", home)["disk_ready"])
            settings.pop("agents")
            settings["hooks"]["SessionStart"][0]["hooks"][0]["statusMessage"] = "Identity"
            path.write_text(json.dumps(settings))
            self.assertTrue(host_agents.check("qoder", home)["disk_ready"])
            (home / ".qoder" / "hooks" / "session-identity.py").unlink()
            self.assertIn("identity hook", host_agents.check("qoder", home)["missing"][0])
            path.write_text("[]")
            self.assertIn("unreadable Qoder settings", host_agents.check("qoder", home)["missing"][-1])

    def test_qoder_invalid_source_model_is_reported_before_injection(self):
        adapter = host_agents.adapter("qoder")
        config = adapter.role_config("project-design-reviewer")[2]
        with mock.patch.object(adapter.common, "markdown_config", return_value={**config, "model": "inherit"}):
            with self.assertRaisesRegex(ValueError, "expected model format"):
                adapter.injected_role("project-design-reviewer")

    def test_host_session_sources_do_not_cross_hosts(self):
        with mock.patch.dict("os.environ", {"CODEX_THREAD_ID": "codex-session", "PROJECT_SESSION_ID": "qoder-session"}, clear=True):
            self.assertEqual(host_agents.adapter("codex").session(), "codex-session")
            self.assertEqual(host_agents.adapter("qoder").session(), "qoder-session")
        with mock.patch.dict("os.environ", {"CODEX_THREAD_ID": "codex-session"}, clear=True):
            self.assertIsNone(host_agents.adapter("qoder").session())
        with mock.patch.dict("os.environ", {"PROJECT_SESSION_ID": "fallback"}, clear=True):
            self.assertEqual(host_agents.adapter("codex").session(), "fallback")


if __name__ == "__main__":
    unittest.main()
