import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

DIRECTORY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_host_tests_qoder", DIRECTORY / "host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
spec = importlib.util.spec_from_file_location("native_project_tests_qoder", DIRECTORY / "project.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def install_fixture(home):
    agents = home / ".qoder" / "agents"
    agents.mkdir(parents=True)
    for name in host.ROLES:
        source, _, _ = host.role_config(name)
        (agents / source.name).write_bytes(source.read_bytes())
    skills = home / ".agents" / "skills"
    skills.mkdir(parents=True)
    for name in host.SKILLS:
        (skills / name).symlink_to(host.ROOT / "skills" / name)
    hooks = home / '.qoder' / 'hooks'
    hooks.mkdir(parents=True)
    (hooks / 'session-identity.py').symlink_to(host.ROOT / 'qoder/hooks/session-identity.py')
    (home / '.qoder/settings.json').write_text(json.dumps({'hooks': {'SessionStart': [
        {'hooks': [{'type': 'command', 'command': 'python3 ~/.qoder/hooks/session-identity.py', 'timeout': 10}]}]}}))
    return agents, skills


class NativeHostTest(unittest.TestCase):
    def test_missing_installation_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            result = host.check(Path(temp))
            self.assertFalse(result["disk_ready"])
            self.assertFalse(result["runtime_verified"])
            self.assertEqual(len(result["missing"]), 4 + len(host.SKILLS) + 2)
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
            self.assertEqual(list(role), [name])
            role = role[name]
            self.assertEqual(role['model'], 'qmodel_38max' if 'reviewer' in name else 'dfmodel')
            self.assertEqual(role['effort'], 'xhigh' if 'reviewer' in name else 'max')
            self.assertIsInstance(role['maxTurns'], int)
            self.assertNotIn('developer_instructions', role)
            body = role['prompt']
            self.assertNotIn('freely delegate', body)
            self.assertIn("references/stage-executor.md", body)
            if name == "project-implementation-reviewer":
                self.assertIn("single-agent", body)

    def test_session_and_continuation_use_native_entry(self):
        command = shlex.join([sys.executable, str(Path(entry.core.__file__).resolve()), '--root', '/tmp/project with spaces', 'resume', '--ticket', 'ticket'])
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'native-session', 'FOREIGN_RUNTIME_SESSION': 'foreign'}, clear=True):
            self.assertEqual(host.session(), 'native-session')
            def query(args):
                self.assertEqual(entry.core.project_identity.current_session(), 'native-session')
                return {'status': 'ready', 'finish_command': command, 'external_command': 'git status'}
            output = io.StringIO()
            with mock.patch.object(entry.core, '_query', side_effect=query), contextlib.redirect_stdout(output):
                self.assertEqual(entry.main(['show', 'A']), 0)
            result = json.loads(output.getvalue())
            bound = shlex.split(result['finish_command'])
            index = bound.index(str(DIRECTORY / 'project.py'))
            self.assertEqual(bound[index+1:], shlex.split(command)[2:])
            self.assertIn('PROJECT_SESSION_ID=native-session', bound)
            self.assertEqual(result['external_command'], 'git status')
            self.assertEqual(entry.core.project_identity.current_session(), os.environ.get('PROJECT_SESSION_ID'))

    def test_begin_finish_keeps_identity_and_shared_schema(self):
        import test_project_workflow as workflow_tests
        fixture = workflow_tests.WorkflowTest()
        fixture.setUp()
        try:
            fixture.real_publish = True
            with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'native-session', 'FOREIGN_RUNTIME_SESSION': 'foreign'}, clear=True), mock.patch.object(entry.core, 'publish_changes', side_effect=fixture.publisher):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(entry.main(['--root', str(fixture.a), 'begin', 'requirement-update', 'A']), 0)
                result = json.loads(output.getvalue())
                # The signed workflow payload is authoritative for the session and schema.
                import project_workflow as workflow
                _, ticket = workflow._load(fixture.a, result['ticket'])
                self.assertEqual(ticket['identity']['session'], 'native-session')
                self.assertNotIn('host', ticket['options'])
                fixture.edit(result, 'Native requirement\n')
                arguments = shlex.split(result['finish_command'])
                self.assertIn(str(DIRECTORY / 'project.py'), arguments)
                self.assertIn('PROJECT_SESSION_ID=native-session', arguments)
                # Run the exact returned shell command in a fresh environment with no identity.
                finished = subprocess.run(result['finish_command'], shell=True, capture_output=True, text=True,
                                          env={'PATH': os.defpath}, timeout=60)
                self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
                self.assertEqual(json.loads(finished.stdout)['status'], 'published')
                self.assertEqual((fixture.a / 'workitems/A/requirement.md').read_text(), 'Native requirement\n')
        finally:
            fixture.doCleanups()
            fixture.tearDown()


    def test_overrides_and_identity_hook_validation_are_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            install_fixture(home)
            path = home / '.qoder/settings.json'
            settings = json.loads(path.read_text())
            for override in ({'enabled': False}, {'modelConfig': {'model': 'inherit'}}, {'runConfig': {'maxTurns': 4}}):
                settings['agents'] = {'overrides': {'project-implementer': override}}
                path.write_text(json.dumps(settings))
                before = path.read_bytes()
                result = host.check(home)
                self.assertFalse(result['disk_ready'])
                self.assertEqual(len(result['missing']), 1)
                self.assertEqual(path.read_bytes(), before)
            settings['agents'] = {'overrides': {'project-implementer': {'modelConfig': {'model': 'dfmodel'}}}}
            path.write_text(json.dumps(settings))
            self.assertTrue(host.check(home)['disk_ready'])
            (home / '.qoder/hooks/session-identity.py').unlink()
            self.assertIn('identity hook', host.check(home)['missing'][0])
            path.write_text('[]')
            self.assertIn('unreadable Qoder settings', host.check(home)['missing'][-1])

    def test_invalid_model_cannot_be_injected(self):
        config = host.role_config('project-design-reviewer')[2]
        with mock.patch.object(host, '_markdown_config', return_value={**config, 'model': 'inherit'}):
            with self.assertRaisesRegex(ValueError, 'expected model format'):
                host.injected_role('project-design-reviewer')

    def test_identity_does_not_infer_other_environment(self):
        with mock.patch.dict(os.environ, {'FOREIGN_RUNTIME_SESSION': 'foreign'}, clear=True):
            self.assertIsNone(host.session())


if __name__ == '__main__':
    unittest.main()
