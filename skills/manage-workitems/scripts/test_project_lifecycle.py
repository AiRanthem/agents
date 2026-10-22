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
import project_removal as removal
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_workflow as workflow_tests
import test_project_autonomy as helpers

git = workflow_tests.fixtures.git


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
    def test_empty_optional_metadata_does_not_hide_active_unsupported_source_state(self):
        key = '0' * 32
        item = {'id': 'A', 'workflow': {'lifecycle': {'generations': {
            key: {'id': key, 'development': {'worktree': 'retained-source'}, 'unused': None}}}}}
        before = copy.deepcopy(item)
        lifecycle.validate(item)
        self.assertEqual(item, before)
        item['workflow']['lifecycle']['generations'][key]['unused'] = {'source': 'still active'}
        with self.assertRaisesRegex(runtime.ProjectError, 'unsupported retained generation'):
            lifecycle.validate(item)

    def test_historical_resource_locator_survives_without_host_routing(self):
        path = 'worktrees/retained'
        key = lifecycle._id('A', 'worktree', ['historical-host', path])
        item = {'id': 'A', 'workflow': {'lifecycle': {'resources': {key: {
            'id': key, 'kind': 'worktree', 'host': 'historical-host'}}}}}
        current, row = lifecycle._resource(item, 'worktree', path)
        self.assertEqual(current, key)
        self.assertNotIn('host', row)

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


class SourceWorkspace(unittest.TestCase):
    approved = helpers.AutonomyTest.approved
    receipt = helpers.AutonomyTest.receipt
    dispatch = helpers.AutonomyTest.dispatch

    def setUp(self):
        helper = helpers.AutonomyTest("runTest")
        self.addCleanup(helper.doCleanups)
        helper.setUp()
        self.f, self.root = helper.f, helper.root
        self.f.development_patch.stop()
        self.remote = self.f.directory / "code.git"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "--quiet", "--initial-branch=main")
        git(self.remote, "config", "core.hooksPath", str(self.remote / "hooks"))
        self.code = self.f.directory / "code"
        self.code.mkdir()
        git(self.code, "init", "--quiet", "--initial-branch=main")
        self.f.configure(self.code)
        (self.code / "base.txt").write_text("base\n")
        (self.code / "AGENTS.md").write_text("Preserve the contract; verify the resulting tree.\n")
        git(self.code, "add", ".")
        git(self.code, "commit", "--quiet", "-m", "formal base")
        git(self.code, "remote", "add", "upstream", str(self.remote))
        git(self.code, "config", "remote.upstream.push", "refs/heads/*:refs/heads/devkits/*")
        git(self.code, "push", "--quiet", "upstream", "main:refs/heads/devkits/main")
        self.base = git(self.code, "rev-parse", "HEAD")
        self.f.project["repositories"] = [{"id": "code", "url": str(self.remote),
            "base_ref": "refs/heads/devkits/main", "base_remote": "upstream"}]
        self.f.write(self.root, ".project/project.yaml", store.dump_yaml(self.f.project))
        self.f.write(self.root, ".project-local/repositories.yaml", store.dump_yaml({"code": str(self.code)}))
        self.f.commit("bind source repository")

    def item(self, identifier):
        return self.f.record(identifier)

    def state(self, identifier):
        return autonomy.status(self.root, items=[identifier])["items"][0]

    def configure(self, identifier, dependencies=(), repository="code"):
        if identifier not in store.items(runtime._working_files(self.root)):
            record = copy.deepcopy(self.item("A"))
            record.update(id=identifier, title=identifier)
            record.pop("workflow", None)
            record["design"] = {"file": "spec.md", "version": 0, "state": "draft"}
            self.f.write(self.root, "workitems/" + identifier + "/requirement.md", "Requirement " + identifier + "\n")
            self.f.write(self.root, "workitems/" + identifier + "/context.md", "Context\n")
        else:
            record = self.item(identifier)
        record.update(depends_on=list(dependencies), development=None, repository=repository)
        for name, body in store.write_item(runtime._working_files(self.root), record).items():
            self.f.write(self.root, name, body)
        self.approved(identifier)

    def authorize(self, *identifiers):
        result = autonomy.authorize(self.root, items=list(identifiers),
            approval_source="Explicit ordinary advancement scope", publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)


    def finish(self, identifier, execution, **options):
        result = helpers.AutonomyTest.finish_execution(self, execution, **options)
        self.assertEqual(result["status"], "published", result)

    def develop(self, identifier):
        for role in ("design-review", "implementation", "code-review"):
            execution = self.dispatch(role, identifier + "-" + role + "-" + str(len(self.f.calls)), identifier)
            if role == "implementation":
                worktree = Path(execution["code_context"]["worktree"])
                (worktree / (identifier + ".txt")).write_text(identifier + " implementation\n")
            self.finish(identifier, execution)
        return worktree


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.p = SourceWorkspace('runTest')
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


    def test_remote_conditional_delete_rejects_movement_and_retries_uncertain_success(self):
        _, generation = self.retired_clean_source()
        record = lifecycle.state(self.p.item('B'))
        captured = record['checkpoints'][record['generations'][generation]['checkpoint']]
        self.collect('B')
        plan = lifecycle.plan(self.root, 'B', publish=self.f.publisher)
        self.assertTrue(any(row['kind'] == 'remote-ref' for row in plan['resources']))
        original = development._git
        moved = False
        def race(checkout, *args, **options):
            nonlocal moved
            if args and args[0] == 'push' and any(str(value).startswith('--force-with-lease=') for value in args) and not moved:
                moved = True
                git(self.p.remote, 'update-ref', captured['ref'], self.p.base, captured['commit'])
            return original(checkout, *args, **options)
        with mock.patch.object(development, '_git', side_effect=race):
            blocked = lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertEqual(blocked['code'], 'resource_collection_pending')
        self.assertEqual(git(self.p.remote, 'rev-parse', captured['ref']), self.p.base)
        git(self.p.remote, 'update-ref', captured['ref'], captured['commit'], self.p.base)
        lost = False
        def uncertain(checkout, *args, **options):
            nonlocal lost
            result = original(checkout, *args, **options)
            if args and args[0] == 'push' and any(str(value).startswith('--force-with-lease=') for value in args) and not lost:
                lost = True
                raise runtime.ProjectError('delete acknowledgement lost')
            return result
        with mock.patch.object(development, '_git', side_effect=uncertain):
            blocked = lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertEqual(blocked['code'], 'resource_collection_pending')
        completed = lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
        self.assertEqual(completed['status'], 'published', completed)
        self.assertIsNone(development._remote_head(self.p.code, captured['url'], captured['ref']))


    def test_later_session_replans_and_preserves_legacy_execution_evidence(self):
        self.p.configure('A')
        self.p.authorize('A')
        self.policy('A')
        item = self.p.item('A')
        item['workflow']['autonomy'].update(current='0' * 32, executions={})
        self.f.install(item)
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'later-session'}):
            result = lifecycle.replan(self.root, 'A', approval_source='User replans preserved source', publish=self.f.publisher)
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

    def test_mode_handoff_preserves_source_and_reviews_without_authorizing_gc(self):
        self.source()
        before = copy.deepcopy(self.p.item('A'))
        result = lifecycle.handoff(self.root, 'A', approval_source='User switches to manual execution', mode='manual', publish=self.f.publisher)
        self.assertEqual(result['status'], 'published', result)
        after = self.p.item('A')
        self.assertEqual(before['development'], after['development'])
        self.assertEqual(before['design'], after['design'])
        self.assertIsNone(autonomy._state(after).get('authorization'))
        self.assertIsNone(lifecycle.state(after).get('policy'))
        with self.assertRaisesRegex(runtime.ProjectError, 'policy required'):
            lifecycle.plan(self.root, 'A', publish=self.f.publisher)


    def test_collection_publication_guards_other_item_state(self):
        _, generation = self.retired_clean_source()
        record = lifecycle.state(self.p.item('B'))
        captured = record['checkpoints'][record['generations'][generation]['checkpoint']]
        def concurrent(root, writes, identity, message, checks=None):
            self.assertIn('.project/state/A.yaml', checks)
            self.f.write(root, '.project/state/A.yaml', 'workflow: {}\n')
            return self.f.publisher(root, writes, identity, message, checks)
        with self.assertRaisesRegex(runtime.ProjectError, 'byte check conflict'):
            lifecycle.plan(self.root, 'B', publish=concurrent)
        self.assertEqual(git(self.p.remote, 'rev-parse', captured['ref']), captured['commit'])


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
        self.p.configure('B')
        self.p.authorize('B')
        self.policy('B')
        lifecycle.replan(self.root, 'B', approval_source='Prepare an ordinary replacement source', publish=self.f.publisher)
        lifecycle.prepare(self.root, 'B', publish=self.f.publisher)
        source_record = self.p.item('B')
        source = development.worktree_location(self.root, source_record, self.f.project)
        # Internal replacement branches are unpublished; ordinary published source
        # still requires separately authorized cleanup rather than lifecycle GC.
        self.assertFalse(source_record['development']['branch_published'])
        (source / 'retained.txt').write_text('Unique source requiring exact preservation.\n')
        git(source, 'add', 'retained.txt')
        git(source, 'commit', '--quiet', '-m', 'retained ordinary source')
        lifecycle.replan(self.root, 'B', approval_source='Replace the clean source generation', publish=self.f.publisher)
        self.p.authorize('B')
        self.assertEqual(lifecycle.prepare(self.root, 'B', publish=self.f.publisher)['status'], 'published')
        generation = next(key for key, value in lifecycle.state(self.p.item('B'))['generations'].items()
                          if value['development']['worktree'] == source_record['development']['worktree'])
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
        # Finish unrelated resource collection before producing a fresh checkpoint.
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


    def test_new_session_continues_exact_collection_without_original_conversation(self):
        self.retired_clean_source()
        plan = lifecycle.plan(self.root, 'B', publish=self.f.publisher)
        self.assertTrue(plan['resources'])
        original = copy.deepcopy(lifecycle.state(self.p.item('B'))['gc'])
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'receiving-controller'}):
            self.assertEqual(lifecycle.state(self.p.item('B'))['gc'], original)
            result = lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
        self.assertEqual(lifecycle.collect(self.root, 'B', intent=plan['intent'], confirm=plan['digest'], publish=self.f.publisher)['status'], 'no_op')


    def test_source_replacement_waits_for_actual_dependency_delivery_in_both_modes(self):
        source = self.source()
        self.policy('A')
        item = self.p.item('A')
        item['depends_on'] = ['B']
        self.f.install(item)
        lifecycle.replan(self.root, 'A', approval_source='Replace preserved source', mode='manual', publish=self.f.publisher)
        for mode in ('manual', 'autonomous'):
            item = self.p.item('A')
            lifecycle.state(item)['mode'] = mode
            self.f.install(item)
            with self.subTest(mode=mode), self.assertRaisesRegex(runtime.ProjectError, 'actual accepted prerequisite delivery'):
                lifecycle.prepare(self.root, 'A', publish=self.f.publisher)
            self.assertTrue(source.is_dir())
            self.assertTrue(lifecycle.state(self.p.item('A'))['replacement_pending'])

    def test_replacement_keeps_recorded_resource_host_without_reinterpreting_old_path(self):
        source = self.source()
        self.policy('A')
        result = lifecycle.replan(self.root, 'A', approval_source='Replan and transfer to receiving coordinator',
                                  mode='manual', publish=self.f.publisher)
        self.assertEqual(result['status'], 'published', result)
        original = copy.deepcopy(lifecycle.state(self.p.item('A'))['generations'])
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'receiving-coordinator'}), mock.patch('socket.gethostname', return_value='receiving-host'):
            result = lifecycle.prepare(self.root, 'A', publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
            current = self.p.item('A')
            self.assertNotIn('host', current['development'])
            self.assertEqual(lifecycle.state(current)['generations'], original)
            self.assertTrue(source.is_dir())
            self.assertNotEqual(current['development']['worktree'], next(iter(original.values()))['development']['worktree'])


if __name__ == '__main__':
    unittest.main()
