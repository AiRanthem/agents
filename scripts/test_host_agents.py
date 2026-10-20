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
    agents.mkdir(parents=True, exist_ok=True)
    for name in host_agents.ROLES:
        source, _, _ = host_agents.role_config(host, name)
        target = agents / source.name
        if host in ("codex", "qoder"):
            target.write_bytes(source.read_bytes())
        elif not target.is_symlink() or target.resolve() != source.resolve():
            target.symlink_to(source)
    skill_root = home / (".cursor" if host == "cursor" else ".agents") / "skills"
    skill_root.mkdir(parents=True, exist_ok=True)
    for name in host_agents.SKILLS:
        link = skill_root / name
        expected = host_agents.ROOT / "skills" / name
        if not link.is_symlink() or link.resolve() != expected.resolve():
            link.symlink_to(expected)
    return agents, skill_root


class HostAgentTests(unittest.TestCase):


    def test_missing_installation_reports_roles_and_skill_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            for host in ("codex", "cursor", "qoder"):
                result = host_agents.check(host, Path(temp))
                self.assertFalse(result["disk_ready"])
                self.assertFalse(result["runtime_verified"])
                self.assertEqual(len(result["missing"]), 4 + len(host_agents.SKILLS))
                self.assertFalse(list(Path(temp).iterdir()))

    def test_installed_agents_are_ready_and_local_modification_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            for host in ("codex", "cursor", "qoder"):
                agents, _ = install_fixture(home, host)
                self.assertTrue(host_agents.check(host, home)["disk_ready"])
                target = next(agents.iterdir())
                content = target.read_text()
                target.unlink()
                target.write_text(content + "\nLocal custom instruction\n")
                result = host_agents.check(host, home)
                self.assertFalse(result["disk_ready"])
                self.assertEqual(len(result["missing"]), 1)
                self.assertIn("differs" if host in ("codex", "qoder") else "must link to repository", result["missing"][0])
                self.assertEqual(target.read_text(), content + "\nLocal custom instruction\n")

    def test_wrong_skill_link_and_regular_copy_are_rejected(self):
        for host in ("codex", "cursor", "qoder"):
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
            reviewer = "reviewer" in name
            for host in ("codex", "cursor", "qoder"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = host_agents.main(["role", "--host", host, "--name", name])
                self.assertEqual(result, 0)
                role = json.loads(output.getvalue())
                self.assertEqual(role["name"], name)
                if host == "codex":
                    self.assertEqual(role["model"], "gpt-6.1-sol")
                    self.assertEqual(role["model_reasoning_effort"], "xhigh" if reviewer else "medium")
                elif host == "cursor":
                    self.assertEqual(role["model"], f"grok-4.7[effort={'xhigh' if reviewer else 'high'},fast=false]")
                else:
                    self.assertEqual(role["model"],
                                     "[Qwen3.8-Max](qmodel_38max)" if reviewer else "[DeepSeek-Flash](dfmodel)")
                    self.assertEqual(role["effort"], "xhigh" if reviewer else "max")
                body = role["developer_instructions"]
                self.assertIn("references/stage-executor.md", body)
                self.assertIn("direct stage assignment", body)
                if host == "qoder":
                    self.assertNotIn("freely delegate", body)
                else:
                    self.assertIn("freely delegate", body)
                if host == "cursor":
                    self.assertIn("subagent type `composer`", body)
                    self.assertNotIn("composer-2.5-fast", body)
                    self.assertNotIn("composer-2.5[fast=false]", body)
                else:
                    self.assertNotIn("composer-2.5", body)
                if name == "project-implementation-reviewer":
                    self.assertIn("independent code-quality subagent must actually run", body)

    def test_cursor_composer_subagent_pins_the_standard_variant(self):
        _, content, config = host_agents.role_config("cursor", "composer")
        self.assertEqual(config["name"], "composer")
        self.assertEqual(config["model"], "composer-2.5[fast=false]")
        self.assertIn("Use proactively", config["description"])
        self.assertIn("Always use for investigating", config["description"])
        self.assertNotIn("composer-2.5-fast", content)
        self.assertNotIn("fast=true", content)

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
