"""First-install behavior in disposable cloud-agent homes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

import install


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        environment = mock.patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex')})
        environment.start()
        self.addCleanup(environment.stop)

    def test_fresh_install_loads_all_sources(self):
        result = install.install(self.home)
        self.assertEqual(result['status'], 'disk_ready')
        self.assertFalse(result['runtime_verified'])
        self.assertTrue(install.host.check(self.home)['disk_ready'])
        self.assertTrue(install.skill_entries.check(self.home)['disk_ready'])
        for entry in (install.ROOT / 'skills').glob('*/SKILL.md'):
            link = self.home / '.agents/skills' / entry.parent.name
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), entry.parent.resolve())
        for source in (install.DIRECTORY / 'agents').glob('*.toml'):
            target = self.home / '.codex/agents' / source.name
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_bytes(), source.read_bytes())
        hooks = self.home / '.codex/hooks.json'
        self.assertEqual(json.loads(hooks.read_text()), json.loads((install.DIRECTORY / 'hooks.json').read_text()))
        for name, event in [('session-start.py', 'SessionStart'), ('subagent-start.py', 'SubagentStart')]:
            result = subprocess.run([sys.executable, str(self.home / '.codex/hooks' / name)],
                                    input=json.dumps({'hook_event_name': event, 'model': 'gpt-6-astra'}),
                                    text=True, capture_output=True, check=True)
            context = json.loads(result.stdout)['hookSpecificOutput']
            self.assertEqual(context['hookEventName'], event)
            self.assertTrue(context['additionalContext'].strip())

    def test_seeded_provider_config_and_unrelated_entries_are_preserved(self):
        codex = self.home / '.codex'
        codex.mkdir()
        config = codex / 'config.toml'
        original = '# image defaults\nmodel = "example"\n\n[mcp_servers.internal]\nurl = "https://example.test"\n\n  \n'
        config.write_text(original)
        config.chmod(0o640)
        auth = codex / 'auth.json'
        auth.write_text('local-auth-fixture')
        system = codex / 'skills/.system'
        system.mkdir(parents=True)
        (system / 'preserve').write_text('system')
        install.install(self.home)
        self.assertTrue(config.read_text().startswith(original))
        self.assertEqual(config.stat().st_mode & 0o777, 0o640)
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed['mcp_servers']['internal']['url'], 'https://example.test')
        self.assertEqual(parsed['agents']['max_concurrent_threads_per_session'], 20)
        self.assertEqual(auth.read_text(), 'local-auth-fixture')
        self.assertEqual((system / 'preserve').read_text(), 'system')

    def test_conflicts_fail_before_creating_links(self):
        for name, content in [('hooks.json', '{}'), ('config.toml', '[agents]\nmax_threads=2\n'),
                              ('config.toml', 'invalid TOML'), ('AGENTS.override.md', 'local instructions')]:
            with self.subTest(name=name, content=content):
                codex = self.home / '.codex'
                codex.mkdir(exist_ok=True)
                target = codex / name
                target.write_text(content)
                with self.assertRaises(ValueError):
                    install.install(self.home)
                self.assertEqual(target.read_text(), content)
                self.assertFalse((codex / 'AGENTS.md').exists())
                self.assertFalse((self.home / '.agents').exists())
                target.unlink()

    def test_existing_installation_is_not_upgraded(self):
        install.install(self.home)
        config = self.home / '.codex/config.toml'
        before = config.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already configured'):
            install.install(self.home)
        self.assertEqual(config.read_bytes(), before)

    def test_foreign_skill_and_redirected_parent_are_preserved(self):
        skills = self.home / '.agents/skills'
        skills.mkdir(parents=True)
        foreign = skills / 'advance-project'
        foreign.mkdir()
        (foreign / 'SKILL.md').write_text('local skill')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            install.install(self.home)
        self.assertFalse((self.home / '.codex').exists())
        self.assertEqual((foreign / 'SKILL.md').read_text(), 'local skill')
        redirected = self.home / '.codex'
        redirected.symlink_to(self.home / '.agents', target_is_directory=True)
        with self.assertRaises(ValueError):
            install.install(self.home)
        self.assertFalse((self.home / '.agents/AGENTS.md').exists())

    def test_explicit_home_cli_runs_without_agent_or_extra_dependencies(self):
        command = [sys.executable, '-S', str(install.DIRECTORY / 'install.py'), '--home', str(self.home)]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'disk_ready')
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
