"""Contract handoffs and lifecycle recovery with real Git and local bare remotes."""
import copy
import os
from pathlib import Path
import unittest
from unittest import mock

import project
import project_autonomy as autonomy
import project_development as development
import project_lifecycle as lifecycle
import project_ownership as ownership
import project_predevelopment as predevelopment
import project_removal as removal
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_workflow as workflow_tests
import test_project_predevelopment as predev_tests

git = predev_tests.git


class ApprovalHandoffTest(unittest.TestCase):
    def setUp(self):
        self.f = workflow_tests.WorkflowTest('runTest')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()

    def test_published_design_routes_to_review_without_separate_approval_registration(self):
        draft = self.f.begin('design-update')
        self.f.edit(draft, '# Complete user-approved design\n')
        finished = self.f.finish(draft)
        self.assertEqual(finished['workflow_gates']['handoff'], 'independent_review')
        files = runtime._working_files(self.f.a)
        gates = workflow.gates(files, self.f.record())
        self.assertTrue(gates['operations']['design-review']['eligible'])
        blocked = workflow.begin(self.f.a, 'design-review', 'A', publish=self.f.publisher)
        self.assertEqual(blocked['code'], 'independent_review_required')
        self.assertNotIn('next_command', blocked)
        for path in blocked['skill_instruction_paths']:
            self.assertTrue(Path(path).is_file(), path)
        self.assertEqual(self.f.record()['design']['approval']['kind'], 'user')

    def test_approval_registrar_may_review_but_all_design_contributors_remain_excluded(self):
        for author, text in [('author', 'First complete design'), ('reviser', 'Revised complete design')]:
            with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': author}):
                draft = self.f.begin('design-update')
                self.f.edit(draft, text + '\n')
                self.f.finish(draft)
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'registrar'}):
            approval = self.f.begin('decision-record', approval_source='Actual user approves the final version')
            self.f.edit(approval, 'Recorded unchanged user decisions.\n')
            self.f.finish(approval)
            for author in ('author', 'reviser'):
                with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': author}):
                    blocked = workflow.begin(self.f.a, 'design-review', 'A', publish=self.f.publisher)
                    self.assertEqual(blocked['code'], 'independent_review_required')
            review = self.f.begin('design-review')
            self.f.edit(review, 'Independent review; registrar did not author or revise the design.\n')
            result = workflow.finish(self.f.a, review['ticket'], options={'result': 'pass', 'provenance': 'Actual independent assessment'}, publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
            self.assertEqual(self.f.record()['design']['state'], 'implementable')


class LifecycleCapacityTest(unittest.TestCase):
    def test_pending_current_source_and_disposed_resident_copies_share_one_capacity(self):
        item = {'id': 'A', 'development': {'worktree': 'current'}, 'workflow': {'lifecycle': {
            'policy': {'max_retained': 2}, 'generations': {
                'pending': {'development': {'worktree': 'current'}},
                'disposed-one': {'development': {'worktree': 'old-one'}, 'disposition': {'kind': 'migrated'}},
                'disposed-two': {'development': {'worktree': 'old-two'}, 'disposition': {'kind': 'migrated'}}}}}}
        with self.assertRaisesRegex(runtime.ProjectError, 'retained-generation capacity'):
            lifecycle.capacity(item)
        # A logical and physical reference to the same source consumes one slot.
        item['development'] = {'worktree': 'replacement'}
        del lifecycle.state(item)['generations']['disposed-two']
        lifecycle.capacity(item)
        with self.assertRaisesRegex(runtime.ProjectError, 'retained-generation capacity'):
            lifecycle.capacity(item, retiring=True)


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.p = predev_tests.PredevelopmentTest('runTest')
        self.addCleanup(self.p.doCleanups)
        self.p.setUp()
        self.root, self.f = self.p.root, self.p.f

    def policy(self, identifier):
        result = lifecycle.policy(self.root, identifier, approval_source='Explicit internal archive and GC policy', grace_days=0, publish=self.f.publisher)
        self.assertEqual(result['status'], 'published', result)

    def source(self):
        self.p.configure('A')
        self.p.authorize('A')
        return self.p.develop('A')

    def collect(self, identifier):
        plan = lifecycle.plan(self.root, identifier, publish=self.f.publisher)
        self.assertEqual(plan['status'], 'ready', plan)
        result = lifecycle.collect(self.root, identifier, intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertIn(result['status'], {'published', 'no_op'}, result)
        return plan

    def test_replan_preserves_index_and_working_tree_and_manual_baseline_is_fresh(self):
        source = self.source()
        self.policy('A')
        (source / 'base.txt').write_text('staged\n')
        git(source, 'add', 'base.txt')
        (source / 'base.txt').write_text('unstaged\n')
        (source / 'extra.txt').write_text('untracked\n')
        before = development.snapshot(source)
        index_tree = git(source, 'write-tree')
        original = development._git
        failed = False
        def uncertain(checkout, *args, **options):
            nonlocal failed
            result = original(checkout, *args, **options)
            if args and args[0] == 'push' and not failed:
                failed = True
                raise runtime.ProjectError('ack lost after archive push')
            return result
        with mock.patch.object(development, '_git', side_effect=uncertain), self.assertRaisesRegex(runtime.ProjectError, 'ack lost'):
            lifecycle.replan(self.root, 'A', approval_source='Replace old work and switch to manual', mode='manual', publish=self.f.publisher)
        pending = lifecycle.state(self.p.item('A'))
        checkpoint_id = next(iter(pending['checkpoints']))
        result = lifecycle.replan(self.root, 'A', approval_source='Replace old work and switch to manual', mode='manual', publish=self.f.publisher)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(before, development.snapshot(source))
        saved = lifecycle.state(self.p.item('A'))['checkpoints'][checkpoint_id]
        self.assertEqual(git(self.p.remote, 'rev-parse', saved['commit'] + '^' + '^{tree}'), index_tree)
        self.assertEqual(git(self.p.remote, 'show', saved['commit'] + ':base.txt'), 'unstaged')
        self.assertEqual(git(self.p.remote, 'show', saved['commit'] + ':extra.txt'), 'untracked')
        self.assertEqual(len(lifecycle.state(self.p.item('A'))['checkpoints']), 1)
        self.assertEqual(lifecycle.replan(self.root, 'A', approval_source='Replace old work and switch to manual', mode='manual', publish=self.f.publisher)['status'], 'no_op')
        with self.assertRaisesRegex(runtime.ProjectError, 'replacement generation'):
            workflow._blocked(store.items(runtime._working_files(self.root)), 'A')
        self.assertEqual(lifecycle.prepare(self.root, 'A', publish=self.f.publisher)['status'], 'published')
        target = development.worktree_location(self.root, self.p.item('A'), self.f.project)
        self.assertNotEqual(target, source)
        self.assertEqual(git(target, 'rev-parse', 'HEAD'), self.p.base)
        self.assertFalse((target / 'A.txt').exists())
        self.assertEqual(development.snapshot(source), before)
        self.assertIsNone(autonomy._state(self.p.item('A')).get('authorization'))
        self.assertEqual(lifecycle.state(self.p.item('A'))['mode'], 'manual')

    def test_old_consumer_pins_survive_dag_change_and_collection_releases_only_copies(self):
        self.p.configure('A')
        self.p.configure('B', ['A'])
        self.p.authorize('A', 'B')
        self.p.develop('A')
        self.p.prepare('B')
        frozen = predevelopment.pins(self.p.item('B'))['A']
        self.policy('A')
        lifecycle.release(self.root, 'A', snapshot=frozen['id'], reference='Stop offering old version', publish=self.f.publisher)
        record = self.p.item('B')
        record['depends_on'] = []
        self.f.install(record)
        roots = lifecycle.snapshot_roots(runtime._working_files(self.root))
        self.assertIn(('A', frozen['id']), roots)
        plan = self.collect('A')
        self.assertFalse(any(row['kind'] == 'remote-ref' for row in plan['resources']))
        self.assertEqual(git(self.p.remote, 'rev-parse', frozen['ref']), frozen['commit'])
        # A new downstream consumer inherits the old frozen closure even after
        # that version stops being advertised and its local cache was evicted.
        record = self.p.item('B')
        record['depends_on'] = ['A']
        self.f.install(record)
        self.p.develop('B')
        self.p.configure('C', ['B'])
        self.p.authorize('C')
        self.p.prepare('C')
        self.assertEqual(predevelopment.pins(self.p.item('C'))['A']['id'], frozen['id'])

    def test_remote_conditional_delete_rejects_movement_and_retries_uncertain_success(self):
        self.source()
        frozen = predevelopment.snapshot(self.root, 'A', publish=self.f.publisher)['snapshot']
        self.policy('A')
        lifecycle.release(self.root, 'A', snapshot=frozen['id'], reference='Obsolete frozen offer', publish=self.f.publisher)
        plan = lifecycle.plan(self.root, 'A', publish=self.f.publisher)
        self.assertTrue(any(row['kind'] == 'remote-ref' for row in plan['resources']))
        original = development._git
        moved = False
        def race(checkout, *args, **options):
            nonlocal moved
            if args and args[0] == 'push' and any(str(value).startswith('--force-with-lease=') for value in args) and not moved:
                moved = True
                git(self.p.remote, 'update-ref', frozen['ref'], self.p.base, frozen['commit'])
            return original(checkout, *args, **options)
        with mock.patch.object(development, '_git', side_effect=race):
            blocked = lifecycle.collect(self.root, 'A', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertEqual(blocked['code'], 'resource_collection_pending')
        self.assertEqual(git(self.p.remote, 'rev-parse', frozen['ref']), self.p.base)
        git(self.p.remote, 'update-ref', frozen['ref'], frozen['commit'], self.p.base)
        lost = False
        def uncertain(checkout, *args, **options):
            nonlocal lost
            result = original(checkout, *args, **options)
            if args and args[0] == 'push' and any(str(value).startswith('--force-with-lease=') for value in args) and not lost:
                lost = True
                raise runtime.ProjectError('delete acknowledgement lost')
            return result
        with mock.patch.object(development, '_git', side_effect=uncertain):
            blocked = lifecycle.collect(self.root, 'A', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertEqual(blocked['code'], 'resource_collection_pending')
        completed = lifecycle.collect(self.root, 'A', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertEqual(completed['status'], 'published', completed)
        self.assertIsNone(development._remote_head(self.p.code, frozen['url'], frozen['ref']))
        newer = predevelopment.snapshot(self.root, 'A', publish=self.f.publisher)['snapshot']
        self.assertNotEqual(frozen['id'], newer['id'])


    def test_project_does_not_require_executor_closure_but_foreign_claim_is_fenced(self):
        self.p.configure('A')
        self.p.authorize('A')
        self.policy('A')
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'other'}), self.assertRaisesRegex(runtime.ProjectError, 'control claim'):
            lifecycle.replan(self.root, 'A', approval_source='Unauthorized foreign claim', publish=self.f.publisher)
        item = self.p.item('A')
        item['workflow']['autonomy'].update(current='0' * 32, executions={})
        self.f.install(item)
        result = lifecycle.replan(self.root, 'A', approval_source='User replans source managed by this agent', publish=self.f.publisher)
        self.assertEqual(result['status'], 'published', result)
        self.assertNotIn('current', self.p.item('A')['workflow']['autonomy'])

    def test_legacy_cache_is_retained_without_worker_history(self):
        self.source()
        self.policy('A')
        item = self.p.item('A')
        relative = '.project-local/autonomy-results/' + '0' * 32
        key, row = lifecycle._resource(item, 'runtime-cache', relative, relative_path=relative, attempt='0' * 32, retained_by=[])
        row['state'] = 'released'
        lifecycle.state(item).setdefault('resources', {})[key] = row
        cache = self.root / relative
        cache.mkdir(parents=True)
        (cache / 'user-data.txt').write_text('Only copy of old unfinished work.\n')
        self.f.install(item)
        plan = lifecycle.plan(self.root, 'A', publish=self.f.publisher)
        self.assertNotIn(key, [entry['id'] for entry in plan['resources']])
        self.assertTrue((cache / 'user-data.txt').is_file())

    def test_mode_handoff_preserves_speculative_baseline_and_does_not_authorize_gc(self):
        self.p.configure('A')
        self.p.configure('B', ['A'])
        self.p.authorize('A', 'B')
        self.p.develop('A')
        self.p.prepare('B')
        before = copy.deepcopy(self.p.item('B'))
        result = lifecycle.handoff(self.root, 'B', approval_source='User switches to manual execution', mode='manual', publish=self.f.publisher)
        self.assertEqual(result['status'], 'published', result)
        after = self.p.item('B')
        self.assertEqual(before['development'], after['development'])
        self.assertEqual(predevelopment.state(before), predevelopment.state(after))
        self.assertIsNone(autonomy._state(after).get('authorization'))
        self.assertIsNone(lifecycle.state(after).get('policy'))
        with self.assertRaisesRegex(runtime.ProjectError, 'formal convergence'):
            workflow._blocked(store.items(runtime._working_files(self.root)), 'B')
        with self.assertRaisesRegex(runtime.ProjectError, 'policy required'):
            lifecycle.plan(self.root, 'B', publish=self.f.publisher)

    def test_collection_publication_guards_nonancestor_consumer_state(self):
        self.source()
        frozen = predevelopment.snapshot(self.root, 'A', publish=self.f.publisher)['snapshot']
        self.policy('A')
        lifecycle.release(self.root, 'A', snapshot=frozen['id'], reference='Retired offer', publish=self.f.publisher)
        def concurrent(root, writes, identity, message, checks=None):
            self.assertIn('.project/state/B.yaml', checks)
            self.f.write(root, '.project/state/B.yaml', 'workflow: {}\n')
            return self.f.publisher(root, writes, identity, message, checks)
        with self.assertRaisesRegex(runtime.ProjectError, 'byte check conflict'):
            lifecycle.plan(self.root, 'A', publish=concurrent)
        self.assertEqual(git(self.p.remote, 'rev-parse', frozen['ref']), frozen['commit'])

    def test_dirty_retained_source_is_reported_and_project_removal_lists_it(self):
        self.source()
        self.policy('A')
        lifecycle.replan(self.root, 'A', approval_source='Replace while preserving source', mode='manual', publish=self.f.publisher)
        old = self.p.item('A')['development']['worktree']
        lifecycle.prepare(self.root, 'A', publish=self.f.publisher)
        generation = next(iter(lifecycle.state(self.p.item('A'))['generations']))
        lifecycle.dispose(self.root, 'A', generation=generation, disposition='discarded',
                          reference='User elects to discard this source after backup', approval_source='Explicit discard of this exact generation', publish=self.f.publisher)
        plan = lifecycle.plan(self.root, 'A', publish=self.f.publisher)
        self.assertTrue(any('user data' in row['reason'] for row in plan['blocked_resources']))
        inspected = removal._inspect(self.root)
        self.assertTrue(any(row.get('path') == str(self.root / old) for row in inspected['resources']))
        self.assertTrue(inspected.get('retained_resource_registry'))

    def retired_clean_source(self):
        self.p.configure('A')
        self.p.configure('B', ['A'])
        self.p.authorize('A', 'B')
        self.p.develop('A')
        self.p.prepare('B')
        source = development.worktree_location(self.root, self.p.item('B'), self.f.project)
        self.policy('B')
        lifecycle.replan(self.root, 'B', approval_source='Replace the clean speculative generation', publish=self.f.publisher)
        self.p.authorize('B')
        self.assertEqual(lifecycle.prepare(self.root, 'B', publish=self.f.publisher)['status'], 'published')
        generation = next(iter(lifecycle.state(self.p.item('B'))['generations']))
        lifecycle.dispose(self.root, 'B', generation=generation, disposition='discarded', reference='Explicit source disposition',
                          approval_source='User discards this exact preserved generation', publish=self.f.publisher)
        return source, generation

    def test_same_tree_new_commit_and_duplicate_checkout_block_collection(self):
        source, generation = self.retired_clean_source()
        git(source, 'commit', '--allow-empty', '--quiet', '-m', 'unique same-tree history')
        head = git(source, 'rev-parse', 'HEAD')
        plan = lifecycle.plan(self.root, 'B', publish=self.f.publisher)
        self.assertTrue(any('recovery checkpoint' in row['reason'] for row in plan['blocked_resources']))
        self.assertEqual(git(source, 'rev-parse', 'HEAD'), head)
        # Finish unrelated local-cache collection before producing a fresh checkpoint.
        lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        refreshed = lifecycle.adopt(self.root, 'B', worktree=self.p.item('B')['workflow']['lifecycle']['generations'][generation]['development']['worktree'], publish=self.f.publisher)
        self.assertEqual(refreshed['status'], 'published', refreshed)
        lifecycle.dispose(self.root, 'B', generation=generation, disposition='discarded', reference='Disposition covers refreshed source',
                          approval_source='User discards the refreshed exact source', publish=self.f.publisher)
        branch = git(source, 'symbolic-ref', '--short', 'HEAD')
        other = self.f.directory / 'duplicate-checkout'
        git(self.p.code, 'worktree', 'add', '--force', str(other), branch)
        plan = lifecycle.plan(self.root, 'B', publish=self.f.publisher)
        self.assertTrue(any('another registered worktree' in row['reason'] for row in plan['blocked_resources']))
        self.assertEqual(git(other, 'symbolic-ref', '--short', 'HEAD'), branch)

    def test_physical_recovery_ref_survives_until_clean_worktree_removal(self):
        source, generation = self.retired_clean_source()
        record = lifecycle.state(self.p.item('B'))
        checkpoint = record['checkpoints'][record['generations'][generation]['checkpoint']]
        first = self.collect('B')
        self.assertTrue(any(row['kind'] == 'worktree' for row in first['resources']))
        self.assertFalse(source.exists())
        self.assertEqual(development._remote_head(self.p.code, checkpoint['url'], checkpoint['ref']), checkpoint['commit'])
        self.collect('B')
        self.assertIsNone(development._remote_head(self.p.code, checkpoint['url'], checkpoint['ref']))

    def test_absent_worktree_keeps_source_branch_when_remote_recovery_disappears(self):
        source, generation = self.retired_clean_source()
        record = lifecycle.state(self.p.item('B'))
        checkpoint = record['checkpoints'][record['generations'][generation]['checkpoint']]
        branch = git(source, 'symbolic-ref', 'HEAD')
        head = git(source, 'rev-parse', 'HEAD')
        git(self.p.code, 'update-ref', '-d', 'refs/heads/' + checkpoint['branch'])
        plan = lifecycle.plan(self.root, 'B', publish=self.f.publisher)
        git(self.p.code, 'worktree', 'remove', str(source))
        git(self.p.remote, 'update-ref', '-d', checkpoint['ref'])
        result = lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertEqual(result['code'], 'resource_collection_pending')
        self.assertIn('recovery checkpoint', result['message'])
        self.assertEqual(git(self.p.code, 'rev-parse', branch), head)


    def test_takeover_continues_exact_collection_without_original_conversation(self):
        self.retired_clean_source()
        plan = lifecycle.plan(self.root, 'B', publish=self.f.publisher)
        self.assertTrue(plan['resources'])
        original = copy.deepcopy(lifecycle.state(self.p.item('B'))['gc'])
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'receiving-controller'}):
            transferred = ownership.takeover(self.root, 'B', approval_source='User continues B in the receiving conversation',
                                             publish=self.f.publisher)
            self.assertEqual(transferred['status'], 'published', transferred)
            self.assertEqual(lifecycle.state(self.p.item('B'))['gc'], original)
            result = lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
        with self.assertRaisesRegex(runtime.ProjectError, 'control claim'):
            lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)


    def test_cross_host_handoff_opens_fresh_baseline_without_reinterpreting_old_path(self):
        source = self.source()
        self.policy('A')
        result = lifecycle.replan(self.root, 'A', approval_source='Replan and transfer to receiving coordinator',
                                  mode='manual', coordinator_session='receiving-coordinator', publish=self.f.publisher)
        self.assertEqual(result['status'], 'published', result)
        original = copy.deepcopy(lifecycle.state(self.p.item('A'))['generations'])
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'receiving-coordinator'}), mock.patch('socket.gethostname', return_value='receiving-host'):
            result = lifecycle.prepare(self.root, 'A', publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
            current = self.p.item('A')
            self.assertEqual(current['development']['host'], 'receiving-host')
            self.assertEqual(lifecycle.state(current)['generations'], original)
            self.assertTrue(source.is_dir())
            self.assertNotEqual(current['development']['worktree'], next(iter(original.values()))['development']['worktree'])


if __name__ == '__main__':
    unittest.main()
