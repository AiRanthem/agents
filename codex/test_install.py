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
        self.assertTrue(install.skill_entries.check(self.home)['disk_ready'])
        shared = install.DIRECTORY.parent / 'skills'
        native = install.DIRECTORY / 'skills'
        shared_names = {path.parent.name for path in shared.glob('*/SKILL.md')}
        native_names = {'adapt-agent-routing'}
        for source, target, names in ((shared, self.home / '.agents/skills', shared_names),
                                      (native, self.home / '.codex/skills', native_names)):
            self.assertEqual({path.name for path in target.iterdir()}, names)
            for name in names:
                self.assertEqual((target / name).readlink(), source / name)
        config = tomllib.loads((self.home / '.codex/config.toml').read_text())
        expected = {str(source / name / 'SKILL.md') for name in shared_names & native_names
                    for source in (shared, self.home / '.agents/skills')}
        disabled = config['skills']['config']
        self.assertTrue(all(item['enabled'] is False for item in disabled))
        self.assertEqual({item['path'] for item in disabled}, expected)
        self.assertFalse((self.home / '.codex/agents').exists())
        hooks = self.home / '.codex/hooks.json'
        definitions = json.loads(hooks.read_text())
        self.assertEqual(definitions, json.loads((install.DIRECTORY / 'hooks.json').read_text()))
        self.assertEqual(set(definitions['hooks']), {'SessionStart'})
        hook_directory = self.home / '.codex/hooks'
        self.assertEqual({path.name for path in hook_directory.iterdir()}, {'session-start.py'})
        result = subprocess.run([sys.executable, str(hook_directory / 'session-start.py')],
                                input=json.dumps({'hook_event_name': 'SessionStart', 'model': 'gpt-6-astra'}),
                                text=True, capture_output=True, check=True)
        context = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(context['hookEventName'], 'SessionStart')
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
        local_role = codex / 'agents/personal.toml'
        local_role.parent.mkdir()
        local_role.write_text('name = "personal"\n')
        install.install(self.home)
        self.assertTrue(config.read_text().startswith(original))
        self.assertEqual(config.stat().st_mode & 0o777, 0o640)
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed['mcp_servers']['internal']['url'], 'https://example.test')
        self.assertEqual(parsed['agents']['max_concurrent_threads_per_session'], 20)
        self.assertEqual(auth.read_text(), 'local-auth-fixture')
        self.assertEqual((system / 'preserve').read_text(), 'system')
        self.assertEqual(local_role.read_text(), 'name = "personal"\n')
        self.assertEqual(list(local_role.parent.iterdir()), [local_role])

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

    def test_missing_routing_source_fails_bootstrap_and_check(self):
        name = 'adapt-agent-routing'
        skill_entries = install.skill_entries
        skills = skill_entries._skills
        for scope, source_root, problem in (
            ('native', install.DIRECTORY / 'skills', f'missing native skill adapter: {name}'),
            ('shared', install.DIRECTORY.parent / 'skills', f'missing shared source for native skill adapter: {name}'),
        ):
            def skills_without_routing(root):
                found = skills(root)
                if root == source_root:
                    found.pop(name)
                return found

            with self.subTest(scope=scope), mock.patch.object(skill_entries, '_skills', skills_without_routing):
                with self.assertRaisesRegex(ValueError, problem):
                    install.install(self.home)
                self.assertFalse((self.home / '.codex').exists())
                self.assertFalse((self.home / '.agents').exists())

                # Simulate an otherwise valid installation of the reduced source inventory.
                check_home = self.home / scope
                lines = []
                for entry in skill_entries.entries(check_home, bootstrap=True):
                    target = Path(entry['target'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(entry['source'])
                    for setting in entry['config']:
                        lines += ['[[skills.config]]', 'path = ' + json.dumps(setting['path']), 'enabled = false']
                config = check_home / '.codex/config.toml'
                config.parent.mkdir(exist_ok=True)
                config.write_text('\n'.join(lines))
                result = skill_entries.check(check_home)
                self.assertFalse(result['disk_ready'])
                self.assertEqual(result['missing'], [problem])

    def test_routing_adapter_must_allow_implicit_invocation(self):
        install.install(self.home)
        metadata = install.DIRECTORY / 'skills/adapt-agent-routing/agents/openai.yaml'
        read_text = Path.read_text

        def read_with_explicit_only_routing(path, *args, **kwargs):
            if path == metadata:
                return ('interface:\n  display_name: "Adapt Agent Routing"\n'
                        'policy:\n  allow_implicit_invocation: false\n')
            return read_text(path, *args, **kwargs)

        with mock.patch.object(Path, 'read_text', read_with_explicit_only_routing):
            problem = 'routing adapter must allow implicit invocation'
            with self.assertRaisesRegex(ValueError, problem):
                install.install(self.home)
            result = install.skill_entries.check(self.home)
            self.assertFalse(result['disk_ready'])
            self.assertEqual(result['missing'], [f'invalid native skill metadata: {metadata}: {problem}'])

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
        foreign = skills / 'explore-design'
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
