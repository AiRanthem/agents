"""User finals stay in human acceptance and reuse only an actual passing source."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock

import project
import project_autonomy as autonomy
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_validation as helpers
from test_project_runtime import git


class FinalizationTest(unittest.TestCase):
    def setUp(self):
        self.v = helpers.UserValidationTest('runTest')
        self.addCleanup(self.v.doCleanups)
        self.v.setUp()
        self.f, self.root, self.a = self.v.f, self.v.root, self.v.a

    def phase(self, *, accepted):
        self.v.implement()
        self.a.finish_execution(self.a.dispatch('code-review', 'independent-reviewer'))
        if accepted:
            result = autonomy.accept(self.root, 'A', approval_source='User explicitly confirms manual acceptance passed', publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
        self.f.fake_development.prepare = mock.Mock(side_effect=AssertionError('user finals must not prepare or rebase code'))

    def finish(self, stage):
        result = self.f.finish(stage)
        self.assertEqual(result['status'], 'published', result)
        if 'workflow_gates' in result and self.f.record()['status'] == 'awaiting_delivery':
            self.assertEqual(result['workflow_gates']['handoff'], 'human_acceptance')
            self.assertEqual(result['workflow_gates']['skill_instruction_paths'],
                [str(Path(workflow.__file__).resolve().parents[2] / 'complete-workitem/SKILL.md')])
        return self.f.record()

    def test_phase_waits_for_real_conclusion_and_preserves_user_design(self):
        self.phase(accepted=False)
        original = copy.deepcopy(self.f.record()['design']['review'])
        self.a.snapshot['tree'] = 'f' * 40
        state = self.a.state()
        self.assertEqual(state['state'], 'awaiting_acceptance')
        self.assertIsNone(state['next_role'])
        self.assertFalse(state['acceptance_refresh_required'])
        with mock.patch.object(self.f.fake_development, 'snapshot', side_effect=runtime.ProjectError('recorded worktree is unavailable')):
            unavailable = self.a.state()
        self.assertEqual(unavailable['state'], 'blocked')
        self.assertEqual(unavailable['reasons'], ['input_unavailable'])
        self.assertIsNone(unavailable['next_role'])
        missing = workflow.begin(self.root, 'design-update', 'A', publish=self.f.publisher)
        self.assertIn('--finalization-source', missing['message'])
        for options in ({'contract_unchanged': True}, {'next_action': 'split'}):
            result = workflow.begin(self.root, 'design-update', 'A', options={'finalization_source': 'User supplies final spec', **options}, publish=self.f.publisher)
            self.assertEqual(result['status'], 'blocked', result)
        final = '# User final design\n\nKeep the user-selected contract even when code differs.\n'
        stage = self.f.begin('design-update', finalization_source='User supplies final design', author_session='actual-design-editor')
        self.f.edit(stage, final)
        item = self.finish(stage)
        self.assertEqual(item['status'], 'awaiting_delivery')
        self.assertNotIn('acceptance', item['workflow']['autonomy'])
        self.assertEqual(item['design']['author_session'], 'actual-design-editor')
        self.assertEqual(item['design']['review'], original)
        self.assertEqual(item['design']['approval']['kind'], 'user')
        blocked = workflow.begin(self.root, 'human-acceptance', 'A', options={'finalization_source': 'User final code and design'}, publish=self.f.publisher)
        self.assertIn('--approval-source', blocked['message'])
        stage = self.f.begin('human-acceptance', approval_source='User now confirms acceptance passed', finalization_source='User final code and design')
        self.assertEqual(stage['spec_authority'], 'user_final')
        self.f.edit(stage, '# Agent attempts to replace user design\n', 'spec.md')
        self.f.edit(stage, 'Final design/code facts.\n', 'report.md')
        self.assertEqual(self.f.finish(stage)['status'], 'blocked')
        self.f.edit(stage, final, 'spec.md')
        self.finish(stage)
        self.assertEqual((self.root / 'workitems/A/spec.md').read_text(), final)
        self.assertEqual(self.a.state()['state'], 'accepted_awaiting_delivery')
        self.f.fake_development.prepare.assert_not_called()

    def test_final_design_reuses_conclusion_and_can_finalize_unchanged_text(self):
        self.phase(accepted=True)
        before = copy.deepcopy(self.f.record())
        source = before['workflow']['autonomy']['acceptance']['source']
        stage = self.f.begin('design-update', finalization_source='User declares existing spec final')
        item = self.finish(stage)
        self.assertEqual(item['design']['version'], before['design']['version'])
        self.assertEqual(item['design']['finalization']['spec_sha256'], item['design']['registered_sha256'])
        self.a.snapshot['tree'] = 'f' * 40
        self.assertEqual(self.a.state()['state'], 'awaiting_acceptance')
        self.assertTrue(self.a.state()['acceptance_refresh_required'])
        stage = self.f.begin('design-update', finalization_source='User changes final design and code', author_session='actual-final-editor')
        final = '# User final contract\n\nUser-selected final behavior.\n'
        self.f.edit(stage, final)
        item = self.finish(stage)
        self.assertEqual(item['design']['version'], before['design']['version'] + 1)
        self.assertEqual(item['workflow']['autonomy']['acceptance']['source'], source)
        self.assertEqual(item['workflow']['autonomy']['acceptance']['finalization_source'], 'User changes final design and code')
        self.assertEqual(item['design']['review'], before['design']['review'])
        stage = self.f.begin('human-acceptance', finalization_source='User final code adjustment')
        self.assertEqual(stage['spec_authority'], 'user_final')
        self.f.edit(stage, 'Register current finals using the original passing conclusion.\n', 'report.md')
        item = self.finish(stage)
        self.assertEqual(item['design']['version'], before['design']['version'] + 1)
        self.assertEqual(item['workflow']['autonomy']['acceptance']['source'], source)
        self.assertEqual(item['workflow']['autonomy']['approved_contract']['spec'], final)
        self.assertEqual(self.a.state()['state'], 'accepted_awaiting_delivery')
        delivery = self.f.begin('delivery-record', kind=['merged'], reference=['Actual merge'], provenance='Actual delivery evidence')
        self.f.edit(delivery, 'Actual merge ancestry and required delivery evidence.\n')
        self.finish(delivery)
        self.assertEqual(self.f.record()['status'], 'done')
        self.assertEqual(workflow.begin(self.root, 'design-update', 'A', options={'finalization_source': 'Change delivered history'}, publish=self.f.publisher)['status'], 'blocked')
        self.f.fake_development.prepare.assert_not_called()

    def test_code_only_finalization_can_align_unfinalized_old_description(self):
        self.phase(accepted=True)
        before = copy.deepcopy(self.f.record())
        self.a.snapshot['tree'] = 'e' * 40
        stage = self.f.begin('human-acceptance', finalization_source='User finalized code only')
        self.assertEqual(stage['spec_authority'], 'implementation_alignment')
        self.f.edit(stage, '# Accurate current implementation description\n', 'spec.md')
        self.f.edit(stage, 'Only old description aligned; no user-final design replaced.\n', 'report.md')
        item = self.finish(stage)
        self.assertNotIn('finalization', item['design'])
        self.assertEqual(item['design']['version'], before['design']['version'] + 1)
        self.assertEqual(item['workflow']['autonomy']['acceptance']['source'], before['workflow']['autonomy']['acceptance']['source'])
        self.assertEqual(self.a.state()['state'], 'accepted_awaiting_delivery')

    def test_explicit_restart_retains_ordinary_design_invalidation(self):
        self.phase(accepted=True)
        self.finish(self.f.begin('design-update', finalization_source='User declares unchanged design final'))
        self.assertIn('finalization', self.f.record()['design'])
        self.f.fake_development.prepare = lambda root, item, *args, **kwargs: item['development']
        self.finish(self.f.begin('development-start', author_session='actual-new-implementer'))
        self.assertEqual(self.f.record()['status'], 'developing')
        self.assertNotIn('acceptance', self.f.record()['workflow']['autonomy'])
        self.assertIsNone(self.f.record()['development'].get('review'))
        self.assertEqual(self.a.state()['next_role'], 'implementation')
        stage = self.f.begin('design-update')
        self.f.edit(stage, '# New ordinary approved design\n')
        item = self.finish(stage)
        self.assertNotIn('finalization', item['design'])
        self.assertEqual(item['design']['state'], 'review-pending')
        self.assertNotIn('review', item['design'])
        self.assertNotIn('acceptance', item['workflow']['autonomy'])
        self.assertEqual(self.a.state()['next_action'], 'design_reuse_assessment')
        with self.assertRaises(runtime.ProjectError):
            workflow._approved(runtime._working_files(self.root), item)

    def test_final_ticket_stales_and_partial_recovers_original_intent(self):
        self.phase(accepted=True)
        stale = self.f.begin('design-update', finalization_source='User supplies final design')
        self.f.edit(stale, '# User final\n')
        old = copy.deepcopy(self.a.snapshot)
        self.a.snapshot['tree'] = 'f' * 40
        self.assertEqual(self.f.finish(stale)['code'], 'stale_evidence')
        self.a.snapshot.update(old)
        attempts = []
        def partial(root, writes, identity, message, checks=None):
            attempts.append(copy.deepcopy(writes))
            result = self.f.publisher(root, writes, identity, message, checks)
            return {'status': 'partial'} if len(attempts) == 1 else result
        stage = self.f.begin('design-update', finalization_source='User final after stale ticket')
        self.f.edit(stage, '# Final user-selected design\n')
        self.assertEqual(workflow.finish(self.root, stage['ticket'], publish=partial)['status'], 'partial')
        saved = copy.deepcopy(self.f.record())
        with mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': 'later-registrar'}):
            result = workflow.resume(self.root, stage['ticket'], publish=partial)
        self.assertEqual(result['status'], 'published', result)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(saved, self.f.record())
        self.assertEqual(saved['design']['finalization']['recorded_by'], 'author')
        self.assertEqual(self.a.state()['state'], 'accepted_awaiting_delivery')

    def test_real_cli_reads_committed_external_spec_and_keeps_dirty_guard(self):
        self.phase(accepted=True)
        prior = copy.deepcopy(self.f.record())
        self.f.commit('Accepted implementation ready for finals')
        self.f.refresh_patch.stop()
        final = '# User directly edited final design\r\n\r\nPreserve exact user text despite differing code.\r\n'
        path = self.root / 'workitems/A/spec.md'
        git(self.root, 'config', 'core.autocrlf', 'false')
        path.write_bytes(final.encode())
        remote = git(self.f.remote, 'rev-parse', 'refs/heads/main')
        result = workflow.begin(self.root, 'human-acceptance', 'A', options={'finalization_source': 'User directly edits design'}, publish=self.f.publisher)
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('dirty', result['message'])
        self.assertEqual(path.read_bytes(), final.encode())
        self.assertEqual(git(self.f.remote, 'rev-parse', 'refs/heads/main'), remote)
        self.f.commit('User commits management spec through normal project Git contract')
        with self.assertRaisesRegex(runtime.ProjectError, 'human-acceptance --finalization-source'):
            autonomy.accept(self.root, 'A', approval_source='Direct acceptance requires already registered spec', publish=self.f.publisher)
        def cli(*args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = project.main(['--root', str(self.root), *args], session='actual-registrar')
            self.assertEqual(code, 0, output.getvalue())
            return json.loads(output.getvalue())
        stage = cli('begin', 'human-acceptance', 'A', '--finalization-source', 'User directly edits final design')
        self.assertEqual(stage['spec_authority'], 'user_final')
        self.assertEqual(next(row for row in stage['editable'] if row['path'].endswith('/spec.md'))['template'], final)
        report = next(row for row in stage['editable'] if row['path'].endswith('/report.md'))
        Path(report['path']).write_text('Exact user final spec and current code; original acceptance remains authoritative.\n')
        self.assertEqual(cli('finish', stage['ticket'])['status'], 'published')
        item = self.f.record()
        self.assertEqual(item['design']['version'], prior['design']['version'] + 1)
        self.assertEqual(item['design']['registered_sha256'], workflow._hash(final))
        self.assertEqual(item['workflow']['autonomy']['acceptance']['source'], prior['workflow']['autonomy']['acceptance']['source'])
        self.assertEqual(item['workflow']['autonomy']['acceptance']['recorded_by'], 'actual-registrar')
        self.assertEqual(runtime._tree_files(self.root, git(self.root, 'rev-parse', 'HEAD'))['workitems/A/spec.md'], final.encode())
        self.assertEqual(path.read_bytes(), final.encode())
        self.assertEqual(git(self.root, 'status', '--porcelain'), '')
        self.assertEqual(self.a.state()['state'], 'accepted_awaiting_delivery')
        stage = cli('begin', 'human-acceptance', 'A', '--finalization-source', 'Same final remains current')
        report = next(row for row in stage['editable'] if row['path'].endswith('/report.md'))
        Path(report['path']).write_text('Same finals; no additional design revision.\n')
        self.assertEqual(cli('finish', stage['ticket'])['status'], 'published')
        self.assertEqual(self.f.record()['design']['version'], item['design']['version'])
