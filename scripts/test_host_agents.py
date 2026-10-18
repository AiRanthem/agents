import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("host_agents", Path(__file__).with_name("host_agents.py"))
host_agents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_agents)


def install_fixture(home, host):
    agents = home / f".{host}" / "agents"
    agents.mkdir(parents=True)
    for name in host_agents.ROLES:
        source, _, _ = host_agents.role_config(host, name)
        if host == "codex":
            (agents / source.name).write_bytes(source.read_bytes())
        else:
            (agents / source.name).symlink_to(source)
    skill_root = home / (".agents" if host == "codex" else ".cursor") / "skills"
    skill_root.mkdir(parents=True)
    for name in host_agents.SKILLS:
        (skill_root / name).symlink_to(host_agents.ROOT / "skills" / name)
    return agents, skill_root


class HostAgentTests(unittest.TestCase):
    def test_receipt_helper_preserves_native_evidence_and_derives_result_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            raw = {"arguments": {"path_prefix": "/root/reviewer"}, "result": {"agents": [
                {"agent_name": "/root/reviewer", "agent_status": {"completed": "Actual report ready"}},
                {"agent_name": "/root/reviewer/quality", "agent_status": {"completed": "Reviewed"}}]}}
            (root / "raw.json").write_text(json.dumps(raw))
            context = {"status": "ready", "worker_paused": False, "worker_id": "/root/reviewer",
                       "attempt": "a" * 32, "role": "code-review", "input_binding": {"version": 3},
                       "read": [{"path": "actual-input"}], "approved_contract": {"spec": "approved"},
                       "code_context": {"worktree": "actual-worktree"}}
            (root / "dispatch.json").write_text(json.dumps(context))
            (root / "report.md").write_text("Actual independent report\n")
            argv = ["receipt", "--host", "codex", "--tool", "collaboration.list_agents",
                    "--raw-file", str(root / "raw.json"), "--dispatch-file", str(root / "dispatch.json"),
                    "--report-file", str(root / "report.md"), "--outcome", "pass", "--terminal-status", "completed",
                    "--descendants-stopped", "--output", str(root / "receipt.json")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(host_agents.main(argv), 0)
            captured = json.loads((root / "receipt.json").read_text())
            self.assertEqual(captured["raw"], raw)
            for key in ("attempt", "worker_id", "role", "input_binding"):
                self.assertEqual(captured[key], context[key])
            self.assertNotIn("call_id", captured)
            original = (root / "receipt.json").read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(host_agents.main(argv), 1)
            self.assertEqual((root / "receipt.json").read_bytes(), original)
            for name, mutate in (("wrong_worker", lambda: raw["result"]["agents"].pop(0)),
                                 ("paused_context", lambda: context.update(worker_paused=True))):
                with self.subTest(name=name):
                    mutate()
                    (root / "raw.json").write_text(json.dumps(raw))
                    (root / "dispatch.json").write_text(json.dumps(context))
                    argv[-1] = str(root / (name + ".json"))
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(host_agents.main(argv), 1)
                    self.assertFalse(Path(argv[-1]).exists())

    def test_spawn_receipt_accepts_targeted_followup_without_fabricating_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            raw = {"arguments": {"target": "/root/worker", "message": "Wait for accepted context"}, "result": {}}
            (root / "raw.json").write_text(json.dumps(raw))
            argv = ["receipt", "--host", "codex", "--tool", "collaboration.followup_task",
                    "--worker-id", "/root/worker", "--raw-file", str(root / "raw.json"),
                    "--output", str(root / "spawn.json")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(host_agents.main(argv), 0)
            self.assertEqual(json.loads((root / "spawn.json").read_text())["raw"], raw)
            for failure in ({"error": {"code": "worker_not_found"}}, {"isError": True}):
                with self.subTest(failure=failure):
                    (root / "raw.json").write_text(json.dumps({**raw, "result": failure}))
                    argv[-1] = str(root / "failed.json")
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(host_agents.main(argv), 1)
                    self.assertFalse((root / "failed.json").exists())
            link = root / "linked.json"
            link.symlink_to(root / "raw.json")
            argv[argv.index("--raw-file") + 1] = str(link)
            argv[-1] = str(root / "bad.json")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(host_agents.main(argv), 1)
            self.assertFalse((root / "bad.json").exists())

    def test_missing_installation_reports_roles_and_skill_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            for host in ("codex", "cursor"):
                result = host_agents.check(host, Path(temp))
                self.assertFalse(result["disk_ready"])
                self.assertFalse(result["runtime_verified"])
                self.assertEqual(len(result["missing"]), 4 + len(host_agents.SKILLS))
                self.assertFalse(list(Path(temp).iterdir()))

    def test_installed_agents_are_ready_and_local_modification_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            for host in ("codex", "cursor"):
                agents, _ = install_fixture(home, host)
                self.assertTrue(host_agents.check(host, home)["disk_ready"])
                target = next(agents.iterdir())
                content = target.read_text()
                target.unlink()
                target.write_text(content + "\nLocal custom instruction\n")
                result = host_agents.check(host, home)
                self.assertFalse(result["disk_ready"])
                self.assertEqual(len(result["missing"]), 1)
                self.assertIn("differs" if host == "codex" else "must link to repository", result["missing"][0])
                self.assertEqual(target.read_text(), content + "\nLocal custom instruction\n")

    def test_wrong_skill_link_and_regular_copy_are_rejected(self):
        for host in ("codex", "cursor"):
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

    def test_codex_role_symlink_is_not_native_discovery_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            agents, _ = install_fixture(home, "codex")
            name = "project-design-reviewer"
            source, _, _ = host_agents.role_config("codex", name)
            target = agents / source.name
            target.unlink()
            target.symlink_to(source)
            result = host_agents.check("codex", home)
            self.assertFalse(result["disk_ready"])
            self.assertEqual(len(result["missing"]), 1)
            self.assertIn("regular TOML file", result["missing"][0])

    def test_cursor_requires_the_repository_symlink_even_for_identical_content(self):
        for kind in ("copy", "wrong-link"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                agents, _ = install_fixture(home, "cursor")
                target = agents / "project-implementer.md"
                content = target.read_bytes()
                target.unlink()
                if kind == "copy":
                    target.write_bytes(content)
                else:
                    other = home / "same-content.md"
                    other.write_bytes(content)
                    target.symlink_to(other)
                result = host_agents.check("cursor", home)
                self.assertFalse(result["disk_ready"])
                self.assertEqual(len(result["missing"]), 1)
                self.assertIn("must link to repository", result["missing"][0])

    def test_role_output_preserves_complete_instructions_and_fixed_profiles(self):
        for name in host_agents.ROLES:
            effort = "xhigh" if "reviewer" in name else "medium"
            for host in ("codex", "cursor"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = host_agents.main(["role", "--host", host, "--name", name])
                self.assertEqual(result, 0)
                role = json.loads(output.getvalue())
                self.assertEqual(role["name"], name)
                if host == "codex":
                    self.assertEqual(role["model"], "gpt-6.1-sol")
                    self.assertEqual(role["model_reasoning_effort"], effort)
                else:
                    cursor_effort = "xhigh" if "reviewer" in name else "high"
                    self.assertEqual(role["model"], f"grok-4.7[effort={cursor_effort},fast=false]")
                body = role["developer_instructions"]
                self.assertIn("references/stage-executor.md", body)
                self.assertIn("freely delegate", body)
                self.assertIn("attempt", body)
                if name == "project-implementation-reviewer":
                    self.assertIn("independent code-quality subagent must actually run", body)

    def test_cursor_project_roles_use_the_explicit_source_and_reject_stale_content(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            user_agents, _ = install_fixture(home, "cursor")
            project_agents = home / "project" / ".cursor" / "agents"
            shutil.copytree(user_agents, project_agents)
            target = project_agents / "project-implementer.md"
            # The effective project definition must be checked even with a valid
            # user installation present; discovery is verified by the real host.
            target.write_text(target.read_text().replace("grok-4.7[effort=high,fast=false]", "inherit"))
            result = host_agents.check("cursor", home, agents_dir=project_agents)
            self.assertFalse(result["disk_ready"])
            self.assertEqual(len(result["missing"]), 1)
            self.assertIn("differs", result["missing"][0])
            self.assertEqual(result["roles"]["project-implementer"]["installed"], str(target))
            source, content, _ = host_agents.role_config("cursor", "project-implementer")
            target.write_text(content)
            self.assertTrue(host_agents.check("cursor", home, agents_dir=project_agents)["disk_ready"])
            for path in user_agents.iterdir():
                path.unlink()
            self.assertTrue(host_agents.check("cursor", home, agents_dir=project_agents)["disk_ready"])
            target.unlink()
            result = host_agents.check("cursor", home, agents_dir=project_agents)
            self.assertFalse(result["disk_ready"])
            self.assertIn("missing native agent", result["missing"][0])

    def test_cursor_injected_roles_and_cloud_skill_copies(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            skills = home / "cloud-skills"
            for name in host_agents.SKILLS:
                shutil.copytree(host_agents.ROOT / "skills" / name, skills / name,
                                ignore=shutil.ignore_patterns("__pycache__"))
            manifest = home / "loaded-roles.json"
            roles = {name: {**host_agents.role_config("cursor", name)[2], "source": "native-sdk:" + name}
                     for name in host_agents.ROLES}
            manifest.write_text(json.dumps(roles))
            options = {"roles_file": manifest, "skills_dir": skills}
            result = host_agents.check("cursor", home, **options)
            self.assertTrue(result["disk_ready"], result)
            self.assertFalse(result["runtime_verified"])
            self.assertEqual(result["roles"]["project-fixer"]["installed"], "native-sdk:project-fixer")
            for change in ({"model": "inherit"}, {"source": ""}, {"developer_instructions": "incomplete"}):
                changed = {**roles, "project-fixer": {**roles["project-fixer"], **change}}
                manifest.write_text(json.dumps(changed))
                result = host_agents.check("cursor", home, **options)
                self.assertFalse(result["disk_ready"], result)
                self.assertEqual(len(result["missing"]), 1)
            manifest.write_text(json.dumps(roles))
            (skills / "advance-project" / "references" / "coordinator.md").write_text("stale copy\n")
            result = host_agents.check("cursor", home, **options)
            self.assertFalse(result["disk_ready"])
            self.assertIn("copied skill differs", result["missing"][0])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = host_agents.main(["check", "--host", "cursor", "--home", str(home),
                                           "--roles-file", str(manifest), "--skills-dir", str(skills)])
            self.assertEqual(status, 1)
            self.assertFalse(json.loads(output.getvalue())["disk_ready"])


if __name__ == "__main__":
    unittest.main()
