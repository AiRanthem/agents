"""Integration checks with isolated bare Git authority and a stateful fake backend."""
import argparse
import contextlib
import io
import errno
import copy
import shlex
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import project
import project_runtime as runtime
import project_store as store
from project_aone import AoneAdapter
import test_project_runtime as fixtures

git, text = fixtures.git, fixtures.text


class FakeAdapter:
    def __init__(self, testcase):
        self.testcase = testcase
        self.remote_items = {}
        self.creates = []
        self.fail_after_create = set()
        self.drift = set()
        self.preflights = 0
        self.mutation_receipts = []

    def preflight(self):
        self.preflights += 1

    def prepare_sync(self, item, files, receipt):
        identifier = item['id']
        if identifier in self.drift:
            raise runtime.ProjectError('Aone managed-field drift: title')
        if receipt['state'] == 'unknown':
            if identifier not in self.remote_items:
                raise runtime.ProjectError('unknown create has 0 candidates; reconcile without recreating')
            action = 'adopt'
        else:
            action = 'update' if receipt['external_id'] else 'create'
        return {'action': action, 'item': identifier, 'receipt': copy.deepcopy(receipt), 'title': item['title']}

    def execute(self, plan):
        identifier = plan['item']
        files = runtime._tree_files(self.testcase.remote, self.testcase.remote_head())
        durable = json.loads(files[f'.project/sync/{identifier}.json'])
        self.testcase.assertEqual(durable['state'], 'unknown')
        self.testcase.assertEqual(durable['operation']['action'], plan['action'])
        self.testcase.assertEqual(durable['intent_id'], plan['receipt']['intent_id'])
        self.mutation_receipts.append({key: json.loads(value)['state'] for key, value in files.items()
                                       if key.startswith('.project/sync/')})
        if plan['action'] == 'create':
            self.creates.append(identifier)
        self.remote_items[identifier] = plan['title']
        if identifier in self.fail_after_create:
            self.fail_after_create.remove(identifier)
            raise runtime.ProjectError('lost create response')
        receipt = copy.deepcopy(plan['receipt'])
        receipt.update(state='verified', external_id='external-' + identifier,
                       baseline_fields={'title': plan['title']}, checked_at='2026-10-16T00:00:00Z')
        return receipt


class V2Adapter:
    """Stateful backend using the production projection and physical receipts."""
    def __init__(self, testcase, config):
        self.testcase = testcase
        self.projection = AoneAdapter(config)
        self.items = {}
        self.creates = []
        self.fail_after_create = set()
        self.preflights = 0

    def desired(self, *args):
        return self.projection.desired(*args)

    def preflight(self):
        self.preflights += 1

    def prepare_sync(self, item, files, receipt):
        identifier = item['id']
        fields = self.desired(item, files, receipt['git_source_commit'])
        if receipt['state'] == 'unknown':
            if self.items.get(identifier) != fields:
                raise runtime.ProjectError('unknown create has 0 candidates; reconcile without recreating')
            action = 'adopt'
        else:
            action = 'update' if receipt['external_id'] else 'create'
        return {'action': action, 'item': identifier, 'fields': fields, 'receipt': copy.deepcopy(receipt)}

    def execute(self, plan):
        identifier = plan['item']
        files = runtime._tree_files(self.testcase.remote, self.testcase.remote_head())
        durable = store.receipt(files, identifier)
        self.testcase.assertEqual(durable['state'], 'unknown')
        self.testcase.assertEqual(durable['intent_id'], plan['receipt']['intent_id'])
        self.testcase.assertEqual(durable['operation']['action'], plan['action'])
        if plan['action'] == 'create':
            self.creates.append(identifier)
        self.items[identifier] = plan['fields']
        if identifier in self.fail_after_create:
            self.fail_after_create.remove(identifier)
            raise runtime.ProjectError('lost response')
        receipt = copy.deepcopy(plan['receipt'])
        receipt.update(state='verified', external_id='external-' + identifier,
                       baseline_fields=plan['fields'], checked_at='2026-10-16T00:00:00Z')
        return receipt


class ProjectCliTest(unittest.TestCase):
    # Reuse fixture helpers without inheriting and rerunning runtime tests.
    setUp = fixtures.WorkspaceTest.setUp
    configure = fixtures.WorkspaceTest.configure
    write = fixtures.WorkspaceTest.write
    remote_head = fixtures.WorkspaceTest.remote_head

    def request(self, *identifiers):
        return {'session': 'session-one', 'token': 'claim-one', 'machine': 'machine-one',
                'message': 'Align requirements', 'operations': [
                    {'op': 'update', 'item': identifier, 'set': {'title': identifier + ' changed'}}
                    for identifier in identifiers]}

    def enable_aone(self):
        config = copy.deepcopy(self.project)
        config['backends']['aone'] = {'space_id': 'space', 'type': 'type', 'category': 'Req',
                                     'status_map': {value: value for value in runtime.STATUSES}}
        self.write(self.a, '.project/project.json', text(config))
        for identifier in ('A', 'B'):
            self.write(self.a, f'workitems/{identifier}/requirement.md', '# Requirement\n\nAccepted outcome.\n')
        git(self.a, 'add', '.')
        git(self.a, 'commit', '--quiet', '-m', 'Enable Aone')
        git(self.a, 'push', '--quiet', 'origin', 'main')
        self.backend = FakeAdapter(self)
        return lambda config: self.backend

    def test_git_batch_once_and_noop_without_network(self):
        with mock.patch.object(project, '_publish', wraps=project._publish) as publish:
            result = project.apply(self.a, self.request('A', 'B'))
        self.assertEqual(result['status'], 'published')
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(self.remote_head(), result['commit'])
        before = git(self.a, 'rev-parse', 'HEAD')
        with mock.patch.object(project, '_publish', side_effect=AssertionError('no network')):
            result = project.apply(self.a, self.request('A', 'B'))
        self.assertEqual(result['status'], 'no_op')
        self.assertEqual(git(self.a, 'rev-parse', 'HEAD'), before)
        self.assertEqual(git(self.a, 'status', '--porcelain'), '')

    def test_dry_run_aone_does_not_preflight_or_write(self):
        factory = self.enable_aone()
        before = self.remote_head()
        with mock.patch.object(project, '_publish', side_effect=AssertionError('no publication')):
            result = project.apply(self.a, self.request('A', 'B'), dry_run=True, adapter_factory=factory)
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(self.backend.preflights, 0)
        self.assertFalse((self.a / '.project-local').exists())
        self.assertEqual(self.remote_head(), before)
        self.assertNotIn('bundle', result)

    def test_aone_three_checkpoints_remote_writeahead_and_release(self):
        factory = self.enable_aone()
        with mock.patch.object(project, '_publish', wraps=project._publish) as publish:
            result = project.apply(self.a, self.request('A', 'B'), adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(publish.call_count, 3)
        self.assertEqual(self.backend.creates, ['A', 'B'])
        self.assertTrue(all(state == 'unknown' for state in self.backend.mutation_receipts[0].values()))
        for identifier in ('A', 'B'):
            receipt = runtime.read_json(self.a / f'.project/sync/{identifier}.json')
            self.assertEqual(receipt['state'], 'verified')
            self.assertEqual(receipt['content_sha256'], runtime.item_digest(self.a, identifier))
            self.assertIsNone(runtime.read_json(self.a / f'workitems/{identifier}/item.json')['owner'])
            self.assertIn(identifier + ' changed', git(self.a, 'show', receipt['git_source_commit'] + ':workitems/' + identifier + '/item.json'))
        self.assertEqual(runtime.validate_project(self.a), [])

    def test_partial_create_retains_owner_resume_never_creates_twice(self):
        factory = self.enable_aone()
        self.backend.fail_after_create.add('B')
        result = project.apply(self.a, self.request('A', 'B'), adapter_factory=factory)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['synchronized'], ['A'])
        self.assertEqual(runtime.read_json(self.a / '.project/sync/B.json')['state'], 'unknown')
        self.assertEqual(runtime.read_json(self.a / 'workitems/B/item.json')['owner']['token'], 'claim-one')
        result = project.resume(self.a, 'session-one', 'claim-one', ['B'], adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(self.backend.creates, ['A', 'B'])
        self.assertIsNone(runtime.read_json(self.a / 'workitems/B/item.json')['owner'])

    def test_drift_keeps_pending_and_source_for_resume(self):
        factory = self.enable_aone()
        self.backend.drift.add('A')
        result = project.apply(self.a, self.request('A'), adapter_factory=factory)
        self.assertEqual(result['status'], 'partial')
        receipt = runtime.read_json(self.a / '.project/sync/A.json')
        self.assertEqual(receipt['state'], 'pending')
        self.assertIsNotNone(receipt['git_source_commit'])
        self.assertEqual(self.backend.creates, [])
        with mock.patch.object(project, '_publish', side_effect=AssertionError('no redundant checkpoint')):
            unchanged = project.apply(self.a, self.request('A'), adapter_factory=factory)
        self.assertEqual(unchanged['status'], 'partial')
        self.backend.drift.clear()
        result = project.resume(self.a, 'session-one', 'claim-one', adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(self.backend.creates, ['A'])

    def test_unknown_without_candidates_never_reports_success(self):
        factory = self.enable_aone()
        self.backend.fail_after_create.add('A')
        project.apply(self.a, self.request('A'), adapter_factory=factory)
        self.backend.remote_items.clear()
        result = project.resume(self.a, 'session-one', 'claim-one', adapter_factory=factory)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.backend.creates, ['A'])
        self.assertEqual(runtime.read_json(self.a / '.project/sync/A.json')['state'], 'unknown')

    def test_verified_owner_release_needs_no_sync(self):
        factory = self.enable_aone()
        request = self.request('A')
        request['operations'] += [{'op': 'claim', 'item': 'A', 'stage': 'preparation'}]
        result = project.apply(self.a, request, adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertIsNotNone(runtime.read_json(self.a / 'workitems/A/item.json')['owner'])
        before = self.backend.preflights
        request['operations'] = [{'op': 'release', 'item': 'A'}]
        with mock.patch.object(project, '_publish', wraps=project._publish) as publish:
            result = project.apply(self.a, request, adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(self.backend.preflights, before)

    def test_other_owner_and_stale_guard_rejected(self):
        factory = self.enable_aone()
        self.backend.drift.add('A')
        project.apply(self.a, self.request('A'), adapter_factory=factory)
        request = self.request('A')
        request['session'], request['token'] = 'other', 'other'
        with self.assertRaisesRegex(runtime.ProjectError, 'owned by another'):
            project.apply(self.a, request, adapter_factory=factory)
        with self.assertRaisesRegex(runtime.ProjectError, 'owned by another'):
            project.resume(self.a, 'other', 'other', ['A'], adapter_factory=factory)
        runtime.refresh_project(self.b)
        bundle = fixtures.WorkspaceTest.bundle(self, self.b, 'B', {'title': 'B remote'})
        project._publish(self.b, bundle)
        # B's remote byte guard changed behind A's snapshot. Its pending result is
        # explicit, and no external mutation may follow the failed first publish.
        result = project.apply(self.a, self.request('B'), adapter_factory=factory)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('byte check conflict', result['error'])
        self.assertEqual(self.backend.creates, [])

    def test_crash_after_first_checkpoint_recovers_business_source(self):
        factory = self.enable_aone()
        with mock.patch.object(project, '_sync', side_effect=runtime.ProjectError('coordinator stopped')):
            result = project.apply(self.a, self.request('A'), adapter_factory=factory)
        self.assertEqual(result['status'], 'partial')
        receipt = runtime.read_json(self.a / '.project/sync/A.json')
        self.assertIsNone(receipt['git_source_commit'])
        business_commit = self.remote_head()
        result = project.resume(self.a, 'session-one', 'claim-one', ['A'], adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        receipt = runtime.read_json(self.a / '.project/sync/A.json')
        self.assertEqual(receipt['git_source_commit'], business_commit)

    def test_legacy_summary_dependency_blockers_and_noop(self):
        request = self.request('A')
        request['operations'][0]['set']['depends_on'] = ['B']
        payload = project.apply(self.a, request, dry_run=True)
        summary = payload['item_summaries'][0]
        self.assertEqual((summary['id'], summary['title'], summary['status']), ('A', 'A changed', 'new'))
        self.assertEqual(summary['blocked_by'], ['B'])
        effect = next(row for row in payload['dependency_effects'] if row['id'] == 'A')
        self.assertFalse(effect['dependency_ready'])
        self.assertEqual(effect['blocked_by'], ['B'])
        self.assertNotIn('owner', summary)
        self.assertNotIn('token', summary)
        request['operations'][0]['set'] = {'title': 'A'}
        result = project.apply(self.a, request)
        self.assertEqual(result['status'], 'no_op')
        self.assertEqual(result['item_summaries'], [])
        self.assertEqual(result['dependency_effects'], [])

    def test_cli_stdin_documents_raw_hash_and_session_error(self):
        path = self.a / 'workitems/A/requirement.md'
        path.write_text('# Supplied requirement\n', encoding='utf-8')
        git(self.a, 'add', '.')
        git(self.a, 'commit', '--quiet', '-m', 'Requirement')
        git(self.a, 'push', '--quiet', 'origin', 'main')
        command = [sys.executable, str(Path(project.__file__).resolve()), '--root', str(self.a)]
        proc = subprocess.run(command + ['apply', '--request', '-', '--dry-run'], input=text(self.request('A')),
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['code'], 'handwritten_apply_disabled')
        proc = subprocess.run(command + ['show', 'A', '--documents', 'requirement.md'], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        document = json.loads(proc.stdout)['documents']['workitems/A/requirement.md']
        self.assertEqual(document['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(document['text'], path.read_text())
        request = self.request('A')
        request.pop('session')
        with mock.patch.dict(project.os.environ, {}, clear=True), self.assertRaisesRegex(runtime.ProjectError, 'request.session'):
            project.apply(self.a, request)


class ProjectV2PublishTest(unittest.TestCase):
    setUp = fixtures.WorkspaceTest.setUp
    configure = fixtures.WorkspaceTest.configure
    write = fixtures.WorkspaceTest.write
    remote_head = fixtures.WorkspaceTest.remote_head
    identity = {'session': 'session-one', 'token': 'token-one', 'machine': 'machine-one'}

    def v2(self, aone=False):
        files = runtime._working_files(self.a)
        config = copy.deepcopy(self.project)
        config['schema_version'] = 2
        if aone:
            config['backends']['aone'] = {'space_id': 'space', 'type': 'type', 'category': 'Req',
                                         'status_map': {value: value for value in runtime.STATUSES}}
        self.write(self.a, '.project/project.yaml', store.dump_yaml(config))
        (self.a / '.project/project.json').unlink()
        newfiles = runtime._working_files(self.a)
        for identifier in ('A', 'B'):
            record = json.loads(files[f'workitems/{identifier}/item.json'])
            for name, value in store.write_item(newfiles, record).items():
                self.write(self.a, name, value)
            (self.a / f'workitems/{identifier}/item.json').unlink()
            self.write(self.a, f'workitems/{identifier}/requirement.md', '# Requirement\n\nAccepted.\n')
            self.write(self.a, f'workitems/{identifier}/context.md', '# Context\n')
        git(self.a, 'add', '.')
        git(self.a, 'commit', '--quiet', '-m', 'V2 fixture')
        git(self.a, 'push', '--quiet', 'origin', 'main')
        self.assertEqual(runtime.validate_project(self.a), [])
        self.backend = V2Adapter(self, config)
        return lambda config: self.backend

    def rename(self, identifier, title):
        files = runtime._working_files(self.a)
        record = store.item(files, identifier)
        record['title'] = title
        return store.write_item(files, record)

    def test_status_lock_permission_failure_is_explicit_and_never_uses_local_readiness(self):
        self.v2()
        original_open = Path.open
        lock = self.a / ".git/project-publish.lock"

        def denied(path, *args, **kwargs):
            if path == lock:
                raise PermissionError(errno.EPERM, "harness denied write", str(path))
            return original_open(path, *args, **kwargs)

        before = self.remote_head()
        for command in (("status",), ("autonomy", "status", "--all")):
            with self.subTest(command=command), mock.patch.object(Path, "open", denied), \
                    mock.patch.object(runtime, "_fetch_selected") as fetch:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = project.main(["--root", str(self.a), *command])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["code"], "host_permission_required")
                self.assertEqual(result["permission_path"], str(lock))
                self.assertEqual(result["required_access"], "write")
                self.assertEqual(result["action"], "request_host_permission")
                self.assertNotIn("round_finished", result)
                fetch.assert_not_called()
        self.assertEqual(self.remote_head(), before)
        self.assertFalse((self.a / ".project-local").exists())

    def test_git_only_publication_and_noop_stale_guard(self):
        self.v2()
        changes = self.rename('A', 'Changed')
        result = project.publish_changes(self.a, changes, self.identity, 'Rename')
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(self.remote_head(), result['commit'])
        with mock.patch.object(project, '_publish', side_effect=AssertionError('no publication')):
            result = project.publish_changes(self.a, changes, self.identity, 'Unchanged')
        self.assertEqual(result['status'], 'no_op')
        with self.assertRaisesRegex(runtime.ProjectError, 'byte check conflict'):
            project.publish_changes(self.a, changes, self.identity, 'Stale',
                                    {'workitems/A/metadata.yaml': '0' * 64})
        with self.assertRaisesRegex(runtime.ProjectError, 'begin/finish'):
            project.apply(self.a, {'session': 's', 'operations': []})

    def test_status_ignores_rejected_pre_push_attempts_and_retains_uncertain_outcomes(self):
        self.v2()
        saved = self.directory / 'publication.json'

        def publish(title, stale=False):
            files = runtime._working_files(self.a)
            writes = self.rename('A', title)
            writes['workitems/A/context.md'] = 'Private publication body\n'
            bundle = {'writes': writes, 'checks': {name: project._hash(files.get(name)) for name in writes},
                      'session': self.identity['session'], 'token': self.identity['token'], 'message': 'Publish'}
            if stale:
                bundle['checks']['workitems/A/metadata.yaml'] = '0' * 64
            saved.write_text(text(bundle))
            return runtime.publish(self.a, saved)

        for _ in range(3):
            with self.assertRaisesRegex(runtime.ProjectError, 'byte check conflict'):
                publish('Rejected private title', stale=True)
        status = project._status(self.a)
        self.assertEqual(status['status'], 'ready', status)
        self.assertEqual(status['pending_publications'], [])
        self.assertEqual(len(status['rejected_publications']), 3)
        for secret in (self.identity['token'], 'Private publication body', 'Rejected private title'):
            self.assertNotIn(secret, text(status))

        identity_file = project._save_identity(self.a, self.identity)
        original_git = runtime._git

        def lose_response(root, *args, **kwargs):
            if args and args[0] == 'push':
                raise runtime.ProjectError('simulated unknown push outcome')
            return original_git(root, *args, **kwargs)

        with mock.patch.object(runtime, '_git', side_effect=lose_response), self.assertRaisesRegex(runtime.ProjectError, 'unknown push outcome'):
            publish('Recover this candidate')
        with mock.patch.dict(project.os.environ, {'PROJECT_SESSION_ID': self.identity['session']}, clear=True):
            status = project._public_result(project._status(self.a), argparse.Namespace(root=str(self.a), command='status'))
        self.assertEqual(status['status'], 'partial', status)
        self.assertEqual(len(status['pending_publications']), 1)
        self.assertEqual(shlex.split(status['next_command'])[-3:], ['resume', '--identity-file', str(identity_file)])
        self.assertNotIn(self.identity['token'], text(status))
        self.assertNotIn('Private publication body', text(status))
        recovered = project.resume(self.a, self.identity['session'], self.identity['token'])
        self.assertEqual(recovered['status'], 'published', recovered)
        self.assertEqual(store.item(runtime._working_files(self.a), 'A')['title'], 'Recover this candidate')

        for title in ('First uncertain candidate', 'Second uncertain candidate'):
            with mock.patch.object(runtime, '_git', side_effect=lose_response), self.assertRaisesRegex(runtime.ProjectError, 'unknown push outcome'):
                publish(title)
        remote = self.remote_head()
        retained = {path: path.read_bytes() for path in (self.a / '.project-local/publish').glob('*/journal.json')}
        with mock.patch.dict(project.os.environ, {'PROJECT_SESSION_ID': self.identity['session']}, clear=True):
            status = project._public_result(project._status(self.a), argparse.Namespace(root=str(self.a), command='status'))
        self.assertEqual(status['status'], 'blocked', status)
        self.assertEqual(status['code'], 'publication_journal_ambiguous')
        self.assertEqual(len(status['pending_publications']), 2)
        self.assertNotIn('next_command', status)
        self.assertEqual(project.resume(self.a, self.identity['session'], self.identity['token'])['code'], 'publication_journal_ambiguous')
        self.assertEqual(self.remote_head(), remote)
        self.assertEqual({path: path.read_bytes() for path in retained}, retained)

    def test_backend_writeahead_projection_noop_and_release(self):
        factory = self.v2(aone=True)
        result = project.publish_changes(self.a, self.rename('A', 'Changed'), self.identity,
                                         'Rename', adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(self.backend.creates, ['A'])
        files = runtime._working_files(self.a)
        receipt = store.receipt(files, 'A')
        self.assertIsNone(store.item(files, 'A')['owner'])
        preflights = self.backend.preflights
        # Content changes in an already projected document do not alter Aone's
        # title/status/managed body. Their Git bytes still publish and validate.
        result = project.publish_changes(self.a, {'workitems/A/context.md': '# New context\n'},
                                         self.identity, 'Context', adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(self.backend.preflights, preflights)
        current = runtime._working_files(self.a)
        self.assertEqual(store.receipt(current, 'A')['baseline_fields'], receipt['baseline_fields'])
        self.assertEqual(store.receipt(current, 'A')['git_source_commit'], receipt['git_source_commit'])
        self.assertEqual(runtime.validate_project(self.a), [])

    def test_migration_preserves_external_identity_and_reverifies_new_projection(self):
        import project_migration
        config = copy.deepcopy(self.project)
        config['backends']['aone'] = {'space_id': 'space', 'type': 'type', 'category': 'Req',
                                     'status_map': {value: value for value in runtime.STATUSES}}
        self.write(self.a, '.project/project.json', text(config))
        for identifier in ('A', 'B'):
            self.write(self.a, f'workitems/{identifier}/requirement.md', '# Requirement\n\nAccepted.\n')
        git(self.a, 'add', '.')
        git(self.a, 'commit', '--quiet', '-m', 'Enable legacy backend')
        git(self.a, 'push', '--quiet', 'origin', 'main')
        self.backend = V2Adapter(self, config)
        factory = lambda config: self.backend
        result = project.publish_changes(self.a, self.rename('A', 'Changed'), self.identity,
                                         'Legacy rename', adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        files = runtime._working_files(self.a)
        old = store.receipt(files, 'A')
        migration = project_migration.prepare_migration(files, instructions='# Approved project instructions\n')
        # Rebuild adapter projection from the v2 configuration as the production
        # coordinator does, while keeping the fake external service state.
        def migrated_factory(config):
            self.backend.projection = AoneAdapter(config)
            return self.backend
        result = project.publish_changes(self.a, migration['writes'], self.identity, 'Migrate',
                                         checks=migration['checks'], adapter_factory=migrated_factory)
        self.assertEqual(result['status'], 'published', result)
        current = runtime._working_files(self.a)
        receipt = store.receipt(current, 'A')
        self.assertEqual(receipt['state'], 'verified')
        self.assertEqual(receipt['external_id'], old['external_id'])
        self.assertNotEqual(receipt['intent_id'], old['intent_id'])
        self.assertNotEqual(receipt['git_source_commit'], old['git_source_commit'])
        self.assertIn('metadata.yaml', receipt['baseline_fields']['managed_body'])
        self.assertEqual(self.backend.creates.count('A'), 1)
        self.assertEqual(runtime.validate_project(self.a), [])

    def test_partial_resume_preserves_intent_and_never_recreates(self):
        factory = self.v2(aone=True)
        self.backend.fail_after_create.add('A')
        changes = self.rename('A', 'Changed')
        result = project.publish_changes(self.a, changes, self.identity, 'Rename', adapter_factory=factory)
        self.assertEqual(result['status'], 'partial', result)
        before = runtime._working_files(self.a)
        receipt = store.receipt(before, 'A')
        self.assertEqual(receipt['state'], 'unknown')
        with mock.patch.dict(project.os.environ, {'PROJECT_SESSION_ID': 'another-session'}, clear=True):
            status = project._status(self.a)
        self.assertEqual(status['status'], 'blocked')
        self.assertEqual(status['code'], 'recovery_owned_by_another_session')
        with mock.patch.dict(project.os.environ, {'PROJECT_SESSION_ID': self.identity['session']}, clear=True):
            status = project._public_result(project._status(self.a), argparse.Namespace(root=str(self.a), command='status'))
        self.assertEqual(status['status'], 'partial')
        self.assertIn('--identity-file', status['next_command'])
        self.assertNotIn(self.identity['token'], status['next_command'])
        external = self.backend.items.pop('A')
        blocked = project.resume(self.a, self.identity['session'], self.identity['token'], ['A'], adapter_factory=factory)
        self.assertEqual(blocked['status'], 'blocked')
        self.assertEqual(blocked['code'], 'sync_conflict')
        self.assertEqual(store.receipt(runtime._working_files(self.a), 'A'), receipt)
        self.backend.items['A'] = external
        result = project.publish_changes(self.a, self.rename('A', 'Another'), self.identity,
                                         'Blocked', adapter_factory=factory)
        self.assertEqual(result['code'], 'sync_unresolved')
        self.assertEqual(store.receipt(runtime._working_files(self.a), 'A'), receipt)
        result = project.publish_changes(self.a, changes, self.identity, 'Resume exact intent', adapter_factory=factory)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(self.backend.creates, ['A'])
        self.assertIsNone(store.item(runtime._working_files(self.a), 'A')['owner'])
        self.assertEqual(runtime.validate_project(self.a), [])


class ProjectOutputTest(unittest.TestCase):
    def test_migration_partial_is_compact_and_resumes_original_identity(self):
        prepared = {'status': 'partial', 'writes': {'workitems/1-demo/requirement.md': 'long prose' * 1000},
                    'checks': {'AGENTS.md': '0' * 64},
                    'publication': {'status': 'partial', 'recovery': {'identity_file': '/tmp/migration identity.json'}}}
        result = project._public_result(project._migration_output(Path('/tmp/project'), prepared, None),
                                        argparse.Namespace(root='/tmp/project', command='migrate'))
        self.assertNotIn('writes', result)
        self.assertNotIn('checks', result)
        self.assertEqual(result['changed_files'], 1)
        command = shlex.split(result['next_command'])
        self.assertEqual(command[-2:], ['--identity-file', '/tmp/migration identity.json'])
        self.assertEqual(result['action'], 'resume')
        self.assertLess(len(json.dumps(result)), 1000)

    def test_pending_stage_result_selects_its_attempt_continuation(self):
        continuation = "python project.py --root /project autonomy resume A --attempt actual-attempt"
        result = project._public_result(
            {"status": "partial", "stage_result_pending": True,
             "continuation_command": continuation,
             "recovery": {"identity_file": "/project/identity.json", "journal": "/project/journal.json"}},
            argparse.Namespace(root="/project", command="autonomy"))
        self.assertEqual(result["next_command"], continuation)
        self.assertEqual(shlex.split(result["publication_next_command"])[-4:],
                         ["--identity-file", "/project/identity.json", "--journal", "/project/journal.json"])

    def test_partial_removal_is_blocked_without_unrelated_resume(self):
        result = project._public_result({'status': 'partial', 'removed': ['worktree'],
                                         'error': 'branch changed', 'action': 'retain_remaining'},
                                        argparse.Namespace(root='/tmp/project', command='remove'))
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['code'], 'partial_removal')
        self.assertEqual(result['removed'], ['worktree'])
        self.assertIsNone(result['next_command'])


if __name__ == '__main__':
    unittest.main()
