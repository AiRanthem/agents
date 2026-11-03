import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

DIRECTORY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_host_tests_codex", DIRECTORY / "host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def install_fixture(home):
    agents = home / ".codex" / "agents"
    agents.mkdir(parents=True)
    for name in host.ROLES:
        source, _, _ = host.role_config(name)
        (agents / source.name).write_bytes(source.read_bytes())
    skills = home / ".agents" / "skills"
    skills.mkdir(parents=True)
    for name in host.SKILLS:
        (skills / name).symlink_to(host.ROOT / "skills" / name)

    return agents, skills


class NativeHostTest(unittest.TestCase):
    def test_missing_installation_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            result = host.check(Path(temp))
            self.assertFalse(result["disk_ready"])
            self.assertFalse(result["runtime_verified"])
            self.assertEqual(len(result["missing"]), 4 + len(host.SKILLS) + 0)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_local_role_edits_and_symlinks_are_rejected(self):
        for kind in ("edited", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                agents, _ = install_fixture(home)
                self.assertTrue(host.check(home)["disk_ready"])
                source, content, _ = host.role_config("project-design-reviewer")
                target = agents / source.name
                target.unlink()
                if kind == "edited":
                    target.write_text(content + "\nLocal custom instruction\n")
                else:
                    target.symlink_to(source)
                before = target.read_bytes()
                result = host.check(home)
                self.assertFalse(result["disk_ready"])
                self.assertEqual(len(result["missing"]), 1)
                self.assertEqual(target.read_bytes(), before)

    def test_skill_links_require_current_repository(self):
        for kind in ("wrong-link", "regular-copy"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                _, skills = install_fixture(home)
                target = skills / "advance-project"
                content = (target / "SKILL.md").read_text()
                target.unlink()
                stale = home / "stale-skill" if kind == "wrong-link" else target
                stale.mkdir()
                (stale / "SKILL.md").write_text(content)
                if kind == "wrong-link":
                    target.symlink_to(stale)
                result = host.check(home)
                self.assertFalse(result["disk_ready"])
                self.assertEqual(len(result["missing"]), 1)
                self.assertIn("skill must link", result["missing"][0])

    def test_role_output_keeps_complete_instructions_and_fixed_profiles(self):
        for name in host.ROLES:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(host.main(["role", "--name", name]), 0)
            role = json.loads(output.getvalue())
            self.assertEqual(role['name'], name)
            self.assertEqual(role['model'], 'gpt-6-astra' if name == 'project-design-reviewer' else 'gpt-6.1-sol')
            self.assertEqual(role['model_reasoning_effort'], 'xhigh' if 'reviewer' in name else 'medium')
            body = role['developer_instructions']
            self.assertIn('direct stage assignment', body)
            self.assertIn('freely delegate', body)
            self.assertIn("references/stage-executor.md", body)
            if name == "project-implementation-reviewer":
                self.assertIn("single-agent", body)

    def test_native_skill_installation_checks_links_and_duplicate_discovery(self):
        spec = importlib.util.spec_from_file_location('native_skill_entries', DIRECTORY / 'skill_entries.py')
        entries = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entries)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.assertFalse(entries.check(home)['disk_ready'])
            lines = []
            for item in entries.entries(home):
                target = Path(item['target'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(item['source'])
                for config in item['config']:
                    lines += ['[[skills.config]]', 'path = ' + json.dumps(config['path']), 'enabled = false']
            path = home / '.codex/config.toml'
            path.write_text('\n'.join(lines))
            self.assertTrue(entries.check(home)['disk_ready'])
            path.write_text('\n'.join(lines).replace('enabled = false', 'enabled = true', 1))
            before = path.read_bytes()
            self.assertFalse(entries.check(home)['disk_ready'])
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
