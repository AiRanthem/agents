"""Sequential local sessions share recovery while preserving real review evidence."""
import copy
import os
import unittest
from unittest import mock

import project
import project_autonomy as autonomy
import project_lifecycle as lifecycle
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_autonomy as helpers


class SingleMachineTest(unittest.TestCase):
    def setUp(self):
        self.a = helpers.AutonomyTest('runTest')
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.f, self.root = self.a.f, self.a.root

    def session(self, value):
        return mock.patch.dict(os.environ, {'PROJECT_SESSION_ID': value})

    def test_foreign_history_allows_sequential_advancement_and_mode_change(self):
        self.a.approved()
        item = self.f.record()
        item['owner'] = {'machine': 'old-host', 'session': 'old-session', 'token': 'old-token'}
        item.setdefault('workflow', {})['lifecycle'] = {'handoff': {
            'from': 'old-session', 'to': 'old-coordinator', 'claim_token': 'old-token',
            'source': 'Historical authorization'}}
        state_path = self.root / '.project/state/A.yaml'
        state = store.load_yaml(state_path.read_bytes())
        state.update(owner=item['owner'], workflow=item['workflow'])
        state_path.write_text(store.dump_yaml(state), encoding='utf-8')
        self.f.commit('historical control state')
        with self.session('new-coordinator'):
            self.a.authorize()
            item = self.f.record()
            state = store.load_yaml(state_path.read_bytes())
            state['workflow']['autonomy']['authorization']['claim_token'] = 'historical-token'
            state_path.write_text(store.dump_yaml(state), encoding='utf-8')
            self.f.commit('historical authorization claim')
            self.assertEqual(self.a.state()['next_role'], 'design-review')
            review = self.a.dispatch('design-review', 'independent-reviewer')
            self.f.edit(review, 'Actual independent review of the approved inputs.\n', 'report.md')
        with self.session('later-coordinator'):
            result = workflow.finish(self.root, review['ticket'], options={
                'result': 'pass', 'provenance': 'Actual independent reviewer report'}, publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
            saved = self.f.record()['design']['review']
            self.assertEqual(saved['session'], 'independent-reviewer')
            self.assertEqual(saved['recorded_by'], 'new-coordinator')
            switched = lifecycle.handoff(self.root, 'A', mode='manual',
                approval_source='User selects manual execution', publish=self.f.publisher)
            self.assertEqual(switched['status'], 'published', switched)
            self.assertEqual(self.f.record()['workflow']['lifecycle']['handoff']['recorded_by'], 'later-coordinator')
        self.assertFalse((self.root / '.project-local/identities').exists())

    def test_retained_ticket_resumes_original_publication_and_checks_current_inputs(self):
        draft = self.f.begin('context-update')
        self.f.edit(draft, 'Retained context from its actual author.\n')
        calls = []
        def partial(root, writes, identity, message, checks=None):
            calls.append(copy.deepcopy(identity))
            return {'status': 'partial'}
        first = workflow.finish(self.root, draft['ticket'], publish=partial)
        self.assertEqual(first['status'], 'partial')
        with self.session('later-session'):
            result = workflow.resume(self.root, publish=self.f.publisher)
            self.assertEqual(result['status'], 'published', result)
            self.assertEqual(calls[0]['session'], 'author')
            next_draft = self.f.begin('context-update')
            self.f.edit(next_draft, 'A new operation has its own real source.\n')
            _, manifest = workflow._load(self.root, next_draft['ticket'])
            self.assertEqual(manifest['identity']['session'], 'later-session')
        self.a.approved()
        self.a.authorize()
        review = self.a.dispatch('design-review', 'reviewer')
        self.f.edit(review, 'Review of the original design.\n', 'report.md')
        self.f.write(self.root, 'workitems/A/requirement.md', 'Changed requirement invalidates the old report.\n')
        with self.session('recovery-session'):
            stale = workflow.finish(self.root, review['ticket'], options={
                'result': 'pass', 'provenance': 'Original report'}, publish=self.f.publisher)
        self.assertEqual(stale['code'], 'stale_evidence', stale)
        self.assertNotEqual((self.f.record()['design'].get('review') or {}).get('result'), 'pass')

    def test_stored_claim_checkpoint_opens_without_publishing_a_new_owner(self):
        draft = self.f.begin('context-update')
        directory, manifest = workflow._load(self.root, draft['ticket'])
        for name in manifest.pop('drafts'):
            (directory / name).unlink()
        state = store.load_yaml((self.root / '.project/state/A.yaml').read_bytes())
        state['owner'] = {'machine': 'previous', 'session': 'previous', 'token': 'historical'}
        manifest.update(state='claim-pending', claim_writes={'.project/state/A.yaml': store.dump_yaml(state)})
        workflow._save(self.root, directory, manifest)
        writes = len(self.f.calls)
        with self.session('later-session'), mock.patch.object(runtime, 'resume_publication', return_value={'status': 'no_op'}):
            resumed = workflow.resume(self.root, draft['ticket'], publish=self.f.publisher)
        self.assertEqual(resumed['status'], 'ready', resumed)
        self.assertEqual(len(self.f.calls), writes)
        self.assertNotIn("owner", self.f.record())
        _, saved = workflow._load(self.root, draft['ticket'])
        self.assertEqual(saved['identity']['session'], 'author')
        self.assertNotIn('claim_writes', saved)

    def test_new_sessions_keep_author_independence_and_delivery_gates(self):
        self.a.reviewed()
        before = self.f.record()['development']['review']
        with self.session('new-session'):
            self.assertEqual(self.a.state()['state'], 'awaiting_acceptance')
            self.assertEqual(self.f.record()['development']['review'], before)
            result = workflow.begin(self.root, 'development-finish', 'A', options={
                'reviewer_session': 'implementer'}, publish=self.f.publisher)
            self.assertEqual(result['status'], 'blocked')
            self.assertIn('different session', result['message'])
            delivered = workflow.begin(self.root, 'delivery-record', 'A', options={
                'kind': ['merged'], 'reference': ['Actual upstream delivery'], 'provenance': 'Actual delivery evidence'}, publish=self.f.publisher)
            self.assertEqual(delivered['status'], 'ready', delivered)
            self.f.edit(delivered, 'Actual delivery evidence.\n')
            delivered = self.f.finish(delivered)
            self.assertEqual(delivered['status'], 'blocked', delivered)
            self.assertIn('acceptance', delivered['message'])
