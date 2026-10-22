"""Conversion, instruction preservation and guarded publication checks."""
import copy
import contextlib
import errno
import hashlib
import io
import json
from pathlib import Path
import subprocess
import shutil
import shlex
import tempfile
import unittest
from unittest import mock

import project_migration as migration
import project_runtime as runtime
import project_store as store
import test_project_runtime as fixtures


class ConversionTest(unittest.TestCase):
    def source(self):
        config = {'schema_version': 1, 'id': 'demo', 'name': 'Demo',
                  'storage': {'remote': 'origin', 'branch': 'main', 'url': '/tmp/demo.git'},
                  'repositories': [{'id': 'code', 'url': 'https://example.invalid/code.git', 'base_ref': 'main'}],
                  'backends': {'aone': None}, 'unknown_project': {'retained': True}}
        item = fixtures.item('1-demo')
        item['unknown_item'] = {'keep': [1, 'yes']}
        item['workflow'] = {'review': {'provenance': {'independent': 'external historical record'}}}
        return {'.project/project.json': fixtures.text(config).encode(),
                '.gitignore': b'/worktrees/*\n!/worktrees/.gitkeep\n/.project-local/\n',
                'AGENTS.md': b'Custom instructions: never recycle.\n',
                '.project/context.md': b'No recycle.\n',
                '.project/workflow.md': b'Keep project workflow constraints.\n',
                'worktrees/.gitkeep': b'',
                'workitems/1-demo/item.json': fixtures.text(item).encode(),
                'workitems/1-demo/spec.md': b'---\ndesign_status: review-pending\ncustom: retained\n---\n\r\n# Design\r\nBody [old](decisions.md).\r\n',
                'workitems/1-demo/requirement.md': b'# No recycle\n',
                'workitems/1-demo/decisions.md': b'# Original decisions\n',
                'workitems/1-demo/handoff.md': b'# Original handoff\n',
                'workitems/1-demo/reviews/old.md': b'Original independent provenance\n'}

    def test_exact_contract_and_prose_preservation_without_synthetic_approval(self):
        files = self.source()
        original = store.item(files, '1-demo')
        result = migration.prepare_migration(files, instructions='Never recycle.\n')
        converted = store.apply_writes(files, result['writes'])
        expanded = store.item(converted, '1-demo')
        for key, value in original.items():
            self.assertEqual(expanded[key], value, key)
        self.assertEqual(store.project(converted)['unknown_project'], {'retained': True})
        self.assertEqual(expanded['design']['state'], 'review-pending')
        self.assertEqual(expanded['design']['version'], 1)
        self.assertNotIn('legacy_frontmatter', expanded['design'])
        self.assertEqual(converted['workitems/1-demo/spec.md'], b'\r\n# Design\r\nBody [old](decisions.md).\r\n')
        self.assertEqual(converted['workitems/1-demo/decision.md'], files['workitems/1-demo/decisions.md'])
        self.assertEqual(converted['workitems/1-demo/context.md'], files['workitems/1-demo/handoff.md'])
        self.assertEqual(converted['workitems/1-demo/requirement.md'], files['workitems/1-demo/requirement.md'])
        self.assertFalse(any('/history/' in name or '/records/' in name or '/reviews/' in name
                             or name.endswith(('/decisions.md', '/handoff.md')) for name in converted))
        self.assertEqual(converted['.project/business-instructions.md'], b'Never recycle.\n')
        self.assertIn(b'.project/business-instructions.md', converted['.project/project-instructions.md'])
        self.assertFalse(any(name.endswith('/item.json') or name == '.project/project.json' for name in converted))
        self.assertEqual(runtime._validate_files(Path('/tmp'), converted), [])
        again = migration.prepare_migration(dict(reversed(list(converted.items()))))
        self.assertEqual(again['status'], 'no_op')
        self.assertEqual(again['writes'], {})
        self.assertEqual(result['checks']['workitems/1-demo/metadata.yaml'], None)
        self.assertEqual(result['checks']['workitems/1-demo/item.json'], hashlib.sha256(files['workitems/1-demo/item.json']).hexdigest())

    def test_unknown_custom_instructions_require_explicit_source(self):
        result = migration.prepare_migration(self.source())
        self.assertEqual(result['code'], 'unsupported-custom-instructions')
        self.assertEqual(result['writes'], {})

    def test_legacy_development_authentication_keeps_original_binding_fields(self):
        files = self.source()
        record = store.item(files, '1-demo')
        development = {'worktree': 'worktrees/existing', 'branch': 'feature/existing',
                       'base_commit': 'a' * 40, 'base_ref': 'upstream/refs/heads/master',
                       'publish_remote': 'inner', 'publish_ref': 'refs/heads/feature/existing'}
        record['development'] = copy.deepcopy(development)
        files['workitems/1-demo/item.json'] = fixtures.text(record).encode()
        result = migration.prepare_migration(files, instructions='No recycle')
        after = store.apply_writes(files, result['writes'])
        binding = store.item(after, '1-demo')['development']
        for field, value in development.items():
            self.assertEqual(binding[field], value)
        source_hash = hashlib.sha256(files['workitems/1-demo/item.json']).hexdigest()
        self.assertEqual(binding['legacy_source_hash'], source_hash)
        marker = store.load_yaml(after['.project/migration.yaml'])
        self.assertEqual(marker['source_sha256'], {'workitems/1-demo/item.json': source_hash})
        self.assertEqual(marker['legacy_developments']['1-demo'],
                         {'source_sha256': source_hash, 'development': development})

    def test_missing_legacy_documents_get_fixed_scaffolds_without_synthetic_design(self):
        files = self.source()
        for name in ('requirement.md', 'spec.md', 'handoff.md', 'decisions.md'):
            files.pop('workitems/1-demo/' + name)
        result = migration.prepare_migration(files, instructions='No recycle')
        after = store.apply_writes(files, result['writes'])
        record = store.item(after, '1-demo')
        for name in ('requirement', 'context', 'decision', 'logs'):
            self.assertEqual(record['documents'][name], name + '.md')
            self.assertIn('workitems/1-demo/' + name + '.md', after)
        self.assertNotIn('workitems/1-demo/spec.md', after)
        self.assertEqual(record['design']['version'], 0)
        self.assertEqual(after['workitems/1-demo/context.md'], b'# Context\n')

    def test_empty_frontmatter_is_removed_without_changing_body(self):
        files = self.source()
        files['workitems/1-demo/spec.md'] = b'---\n---\n# Body\n'
        result = migration.prepare_migration(files, instructions='No recycle')
        after = store.apply_writes(files, result['writes'])
        self.assertEqual(after['workitems/1-demo/spec.md'], b'# Body\n')
        self.assertEqual(store.item(after, '1-demo')['design']['state'], 'draft')

    def test_generated_upgrade_preserves_separate_business_source_and_custom_edits_block(self):
        first = migration.prepare_migration(self.source(), instructions='Never recycle.\n')
        files = store.apply_writes(self.source(), first['writes'])
        original_business = files['.project/business-instructions.md']
        original_renderer = migration.project_instructions
        with mock.patch.object(migration, 'project_instructions',
                               side_effect=lambda snapshot: original_renderer(snapshot) + '\nUpdated generated routing.\n'):
            upgraded = migration.prepare_migration(files)
            self.assertEqual(upgraded['status'], 'prepared')
            after = store.apply_writes(files, upgraded['writes'])
            self.assertEqual(after['.project/business-instructions.md'], original_business)
            self.assertEqual(migration.prepare_migration(after)['status'], 'no_op')
        files['.project/project-instructions.md'] += b'Custom constraint added directly.\n'
        blocked = migration.prepare_migration(files)
        self.assertEqual(blocked['code'], 'unsupported-custom-instructions')
        approved = migration.prepare_migration(files, instructions='Never recycle. Custom constraint.\n')
        after = store.apply_writes(files, approved['writes'])
        self.assertFalse(any(name.startswith('.project/history/') for name in after))
        self.assertEqual(after['.project/business-instructions.md'], b'Never recycle. Custom constraint.\n')

    def test_legacy_prose_requires_current_source_and_never_becomes_raw_current_business(self):
        files = self.source()
        files['.project/business-instructions.md'] = b'Current business mixed with old commands.\r\n'
        files['.project/workflow.md'] = b'Shared reference is read-only.\r\nOld lifecycle procedure.\r\n'
        files['.project/recovery.md'] = b'Old writer must stop. Uncommitted code is not recoverable.\r\n'
        normalized = files['AGENTS.md'].decode().replace('Demo', '{{PROJECT_NAME}}').replace('demo', '{{PROJECT_ID}}')
        with mock.patch.object(migration, 'LEGACY_ENTRY_HASHES', {hashlib.sha256(normalized.encode()).hexdigest()}):
            result = migration.prepare_migration(files)
        self.assertEqual(result['code'], 'current-instructions-required')
        self.assertIn('.project/workflow.md', result['read_sources'])
        self.assertIn('.project/recovery.md', result['read_sources'])
        self.assertIn('workitems/1-demo/spec.md', result['read_sources'])
        self.assertEqual(result['writes'], {})
        current = 'Shared reference is read-only. Old writer must stop. Unpublished code remains local.\n'
        approved = migration.prepare_migration(files, instructions=current)
        after = store.apply_writes(files, approved['writes'])
        self.assertEqual(after['.project/business-instructions.md'], current.encode())
        self.assertFalse(any('/history/' in name for name in after))
        self.assertNotIn(b'Old lifecycle procedure', b''.join(after.values()))
        self.assertNotIn('legacy_frontmatter', store.item(after, '1-demo')['design'])
        marker = store.load_yaml(after['.project/migration.yaml'])
        marker.pop('instruction_policy')
        after['.project/migration.yaml'] = store.dump_yaml(marker).encode()
        blocked = migration.prepare_migration(after)
        self.assertEqual(blocked['code'], 'current-instructions-required')
        self.assertEqual(blocked['read_sources'], ['.project/business-instructions.md'])
        replaced = store.apply_writes(after, migration.prepare_migration(after, instructions=current)['writes'])
        self.assertEqual(migration.prepare_migration(replaced)['status'], 'no_op')

    def test_init_and_migration_use_actual_assets_and_v2_refresh_is_repeatable(self):
        import project_init
        import project_templates
        source = self.source()
        config = copy.deepcopy(store.project(source))
        config['schema_version'] = 2
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp) / 'assets'
            shutil.copytree(project_templates.TEMPLATE_ROOT, assets)
            with mock.patch.object(project_templates, 'TEMPLATE_ROOT', assets):
                initial = project_init._render(config, 'Business {literal} {{PROJECT_NAME}}', None, None)
                initial_migration = migration.prepare_migration(source, instructions='Preserve exact business.\r\n')
                converted = store.apply_writes(source, initial_migration['writes'])
                for name in project_templates.GENERATED_PROJECT_PATHS:
                    self.assertEqual(initial[name], converted[name], name)
                self.assertIn(b'Business {literal} {{PROJECT_NAME}}', initial['.project/context.md'])
                before = store.load_yaml(converted['.project/migration.yaml'])
                for index, name in enumerate(project_templates.GENERATED_PROJECT_PATHS):
                    path = assets / name
                    path.write_text(path.read_text() + f'\nInstalled source revision {index}.\n')
                refreshed = migration.prepare_migration(converted)
                self.assertEqual(refreshed['status'], 'prepared')
                after = store.apply_writes(converted, refreshed['writes'])
                created = project_init._render(config, 'Other business', None, None)
                marker = store.load_yaml(after['.project/migration.yaml'])
                self.assertNotEqual(before['generator_sha256'], marker['generator_sha256'])
                for name in project_templates.GENERATED_PROJECT_PATHS:
                    self.assertEqual(after[name], created[name], name)
                    self.assertEqual(marker['generator_sources_sha256'][name],
                                     hashlib.sha256((assets / name).read_bytes()).hexdigest())
                    self.assertEqual(marker['generated_sha256'][name], hashlib.sha256(after[name]).hexdigest())
                self.assertEqual(after['.project/business-instructions.md'], b'Preserve exact business.\r\n')
                self.assertFalse(any('/history/' in name for name in after))
                self.assertEqual(migration.prepare_migration(after)['status'], 'no_op')
                self.assertEqual(migration.prepare_migration(created)['writes'], {})

    def test_v2_spec_is_opaque_even_with_yaml_like_or_invalid_opening_text(self):
        files = store.apply_writes(self.source(), migration.prepare_migration(
            self.source(), instructions='Current effective constraints.')['writes'])
        spec = 'workitems/1-demo/spec.md'
        for prose in (b'---\r\ndesign_status: prose\r\ncustom: current\r\n---\r\n# Design\r\n',
                      b'---\ninvalid: [YAML\n---\nCurrent prose.\n',
                      b'---\nNo closing delimiter; this is current Markdown.\n'):
            with self.subTest(prose=prose):
                snapshot = dict(files)
                snapshot[spec] = prose
                with mock.patch.object(migration, '_frontmatter', side_effect=AssertionError('v2 Markdown was parsed')):
                    result = migration.prepare_migration(snapshot)
                self.assertEqual(result['status'], 'no_op')
                self.assertEqual(store.apply_writes(snapshot, result['writes'])[spec], prose)
        item = store.item(snapshot, '1-demo')
        item['design']['legacy_frontmatter'] = {'custom': 'Current constraint needing consolidation'}
        snapshot.update({name: text.encode() for name, text in store.write_item(snapshot, item).items()})
        with mock.patch.object(migration, '_frontmatter', side_effect=AssertionError('v2 Markdown was parsed')):
            blocked = migration.prepare_migration(snapshot)
            self.assertEqual(blocked['code'], 'current-instructions-required')
            self.assertEqual(blocked['read_sources'], ['workitems/1-demo/metadata.yaml'])
            refreshed = migration.prepare_migration(snapshot, instructions='Current consolidated custom constraint.')
        after = store.apply_writes(snapshot, refreshed['writes'])
        self.assertEqual(after[spec], prose)
        self.assertNotIn('legacy_frontmatter', store.item(after, '1-demo')['design'])

    def test_v2_custom_workflow_or_recovery_is_not_silently_refreshed(self):
        converted = store.apply_writes(self.source(), migration.prepare_migration(
            self.source(), instructions='Original business.\n')['writes'])
        for name in ('.project/workflow.md', '.project/recovery.md'):
            with self.subTest(name=name):
                files = dict(converted)
                files[name] += b'Custom project constraint.\r\n'
                snapshot = copy.deepcopy(files)
                result = migration.prepare_migration(files)
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['blockers'], [name])
                self.assertEqual(result['writes'], {})
                self.assertEqual(files, snapshot)
                approved = migration.prepare_migration(files, instructions='Original business. Custom project constraint.\n')
                after = store.apply_writes(files, approved['writes'])
                self.assertFalse(any('/history/' in path for path in after))
                self.assertEqual(migration.prepare_migration(after)['writes'], {})

    def test_v2_routes_without_recorded_hashes_accept_only_observed_old_outputs(self):
        import project_init
        import project_templates
        config = copy.deepcopy(store.project(self.source()))
        config['schema_version'] = 2
        files = project_init._render(config, 'Business', None, None)
        # These bytes are the observed initializer output before routes were
        # tracked. Keep its old source fingerprint; recognition uses exact bytes.
        files['.project/recovery.md'] = (
            '# Recover this workspace\n\n'
            'Restore the dedicated branch `main` from `/tmp/demo.git` and start the agent at this project\'s management root. Read its generated `AGENTS.md`. If shared skills are missing, install the dev-kit from `git@github.com:AiRanthem/agents.git` using its installation contract. Credentials and unpublished code are not restored by cloning project records.\n\n'
            'Use installed `manage-workitems/scripts/project.py status`. Report its facts; for `partial`, run only the returned resume command. `published` or `no_op` ends the operation; `blocked` permits only the returned begin command for `code: stale_ticket`; otherwise report its listed blockers or missing facts. Keep local identity/recovery data; no timeout or new session authorizes takeover.\n\n'
            'Use `upgrade-project` for deterministic migration and generated instruction refresh. Historical prompts remain under `.project/history/` as evidence and are not active instructions. Required original main-workspace instructions and code-worktree paths come from the program; read the originals before dependent work. Missing bindings, originals or unpublished code must be restored through the stated inputs rather than guessed.\n').encode()
        marker = store.load_yaml(files['.project/migration.yaml'])
        marker['generator_version'] = 1
        marker['generator_sha256'] = '0c507bb6679a4eb86ecd0a0d4cead3b9c402af4d0d8a03469ad0e980626723bb'
        marker.pop('generator_sources_sha256')
        for name in ('.project/workflow.md', '.project/recovery.md'):
            marker['generated_sha256'].pop(name)
        files['.project/migration.yaml'] = store.dump_yaml(marker).encode()
        upgraded = migration.prepare_migration(files)
        self.assertEqual(upgraded['status'], 'prepared', upgraded)
        after = store.apply_writes(files, upgraded['writes'])
        for name in project_templates.GENERATED_PROJECT_PATHS:
            self.assertEqual(after[name].decode(), project_templates.project_entries(config)[name])
        self.assertEqual(migration.prepare_migration(after)['writes'], {})
        old_migration = dict(files)
        old_migration['.project/workflow.md'] = b'# Project workflow\n\nRead `project-instructions.md` for preserved business constraints. Use the current installed `manage-workitems/references/workflow.md` and project root `AGENTS.md` for lifecycle commands. Original project workflow text is retained at `history/workflow.md`.\n'
        old_migration['.project/recovery.md'] = b'# Project recovery\n\nUse installed `project.py status` and the root `AGENTS.md`. Continue only through the program-returned operation or resume command; report blocked facts when no continuation is returned. Historical recovery instructions are retained at `history/recovery.md`.\n'
        migrated = migration.prepare_migration(old_migration)
        self.assertEqual(migrated['status'], 'prepared', migrated)
        self.assertEqual(store.apply_writes(old_migration, migrated['writes']), after)
        files['.project/workflow.md'] += b'User edit.\n'
        blocked = migration.prepare_migration(files)
        self.assertEqual(blocked['code'], 'unsupported-custom-instructions')
        self.assertEqual(blocked['writes'], {})

    def test_unresolved_sync_blocks_all_writes_even_with_active_owner(self):
        for value in ('pending', 'unknown'):
            files = self.source()
            record = store.item(files, '1-demo')
            record['owner'] = {'session': 'other', 'machine': 'host', 'token': 'lease'}
            files['workitems/1-demo/item.json'] = fixtures.text(record).encode()
            files['.project/sync/1-demo.json'] = fixtures.text({'state': value}).encode()
            result = migration.prepare_migration(files, instructions='No recycle')
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['writes'], {})

    def test_legacy_cleanup_gets_one_current_pointer_and_ambiguous_disposition_blocks(self):
        files = store.apply_writes(self.source(), migration.prepare_migration(self.source(), instructions='Current constraints')['writes'])
        for identifier, stamp in (('old', '2026-10-15T00:00:00+00:00'), ('latest', '2026-10-16T00:00:00+00:00')):
            base = 'workitems/1-demo/records/' + identifier
            cleanup = {'id': identifier, 'kind': 'cleanup', 'status': 'not_applicable',
                       'mode': 'skipped', 'reference': 'Current user disposition',
                       'approval_source': 'Existing user instruction', 'created_at': stamp}
            files[base + '.yaml'] = store.dump_yaml(cleanup).encode()
            files[base + '.md'] = b'Current disposition\n'
        snapshot = dict(files)
        result = migration.prepare_migration(files)
        after = store.apply_writes(files, result['writes'])
        self.assertEqual(files, snapshot)
        item = store.item(after, '1-demo')
        self.assertEqual(item['workflow']['cleanup_record'], 'latest')
        record = store.load_yaml(after['workitems/1-demo/records/latest.yaml'])
        self.assertEqual(record['item'], '1-demo')
        self.assertNotIn('workitems/1-demo/records/old.yaml', after)
        self.assertNotIn('workitems/1-demo/records/old.md', after)
        self.assertEqual(migration.prepare_migration(after)['status'], 'no_op')
        ambiguous = store.load_yaml(files['workitems/1-demo/records/latest.yaml'])
        ambiguous['id'] = 'ambiguous'
        files['workitems/1-demo/records/ambiguous.yaml'] = store.dump_yaml(ambiguous).encode()
        files['workitems/1-demo/records/ambiguous.md'] = b'Other disposition\n'
        with self.assertRaisesRegex(store.StoreError, 'ambiguous'):
            migration.prepare_migration(files)

    def test_custom_frontmatter_requires_current_source_and_canonical_alias_wins(self):
        files = self.source()
        files.pop('.project/workflow.md')
        normalized = files['AGENTS.md'].decode().replace('Demo', '{{PROJECT_NAME}}').replace('demo', '{{PROJECT_ID}}')
        with mock.patch.object(migration, 'LEGACY_ENTRY_HASHES', {hashlib.sha256(normalized.encode()).hexdigest()}):
            result = migration.prepare_migration(files)
        self.assertEqual(result['code'], 'current-instructions-required')
        self.assertEqual(result['read_sources'], ['workitems/1-demo/spec.md'])
        files['workitems/1-demo/decision.md'] = b''
        current = 'Current custom constraint from the old frontmatter.\n'
        after = store.apply_writes(files, migration.prepare_migration(files, instructions=current)['writes'])
        self.assertEqual(after['workitems/1-demo/decision.md'], b'')
        self.assertNotIn('workitems/1-demo/decisions.md', after)
        self.assertEqual(after['.project/business-instructions.md'], current.encode())
        self.assertNotIn('legacy_frontmatter', store.item(after, '1-demo')['design'])

    def test_changed_verified_receipt_requires_backend_configuration_before_publication(self):
        files = store.apply_writes(self.source(), migration.prepare_migration(self.source(), instructions='Current constraints')['writes'])
        files['workitems/1-demo/records/obsolete.yaml'] = b'id: obsolete\n'
        files['workitems/1-demo/records/obsolete.md'] = b'Obsolete report\n'
        receipt = {'intent_id': 'current', 'content_sha256': runtime._business_digest(files, '1-demo'),
                   'state': 'verified', 'external_id': 'external', 'baseline_fields': {'title': 'Current'},
                   'git_source_commit': 'a' * 40, 'checked_at': '2026-10-16T00:00:00+00:00'}
        files.update({name: text.encode() for name, text in store.write_receipt(files, '1-demo', receipt).items()})
        self.assertEqual(runtime._validate_files(Path('/tmp'), files), [])
        publish = mock.Mock()
        snapshot = dict(files)
        with mock.patch.object(runtime, 'find_project', return_value=Path('/tmp')) as find, \
                mock.patch.object(runtime, '_check_tracked_paths'), \
                mock.patch.object(runtime, '_working_files', return_value=files):
            blocked = migration.migrate('/tmp', publish=publish)
            self.assertEqual(blocked['code'], 'aone-configuration-required')
            self.assertEqual(blocked['status'], 'blocked')
            self.assertEqual(blocked['writes'], {})
            self.assertEqual(files, snapshot)
            publish.assert_not_called()
            config = store.project(files)
            config['backends']['aone'] = {'space_id': 'space', 'type': 'type', 'category': 'Req',
                                         'status_map': {value: value for value in runtime.STATUSES}}
            files.update({name: text.encode() for name, text in store.write_project(files, config).items()})
            prepared = migration.migrate('/tmp', dry_run=True, publish=publish)
            self.assertEqual(prepared['status'], 'prepared')
            self.assertTrue(prepared['validated'])
            self.assertEqual(prepared['backend_sync_required'], ['1-demo'])
            publish.assert_not_called()

    def test_current_credentials_survive_while_superseded_records_and_aliases_are_removed(self):
        files = store.apply_writes(self.source(), migration.prepare_migration(self.source(), instructions='Current source')['writes'])
        item = store.item(files, '1-demo')
        for slot, kind, identifier in (('design', 'design-review', 'review'),
                                       ('development', 'development-finish', 'implementation')):
            base = 'workitems/1-demo/records/' + identifier
            record = {'id': identifier, 'item': '1-demo', 'kind': kind, 'report': base + '.md'}
            files[base + '.yaml'] = store.dump_yaml(record).encode()
            files[base + '.md'] = b'Current credential report\n'
            if slot == 'design':
                item['design']['review'] = record
            else:
                item['development'] = {'review': record}
        delivery = {'id': 'delivered', 'item': '1-demo', 'kind': 'delivery-record',
                    'report': 'workitems/1-demo/records/delivered.md'}
        files['workitems/1-demo/records/delivered.yaml'] = store.dump_yaml(delivery).encode()
        files['workitems/1-demo/records/delivered.md'] = b'Current delivery evidence\n'
        item['delivery']['record'] = 'delivered'
        files.update({name: text.encode() for name, text in store.write_item(files, item).items()})
        kept = {name: content for name, content in files.items() if '/records/' in name}
        files['workitems/1-demo/records/obsolete.yaml'] = b'id: obsolete\n'
        files['workitems/1-demo/records/obsolete.md'] = b'Old report\n'
        files['workitems/1-demo/records/legacy-spec.md'] = b'Old spec\n'
        files['workitems/1-demo/reviews/old.md'] = b'Historical review\n'
        files['.project/history/AGENTS.md'] = b'Old instructions\n'
        files['workitems/1-demo/decisions.md'] = b'Obsolete alias\n'
        files['workitems/1-demo/handoff.md'] = b'Obsolete alias\n'
        knowledge = {'id': 'current', 'body': 'evidence/current.md', 'topic': 'Current topic',
                     'inputs': {'revision': 'current'}, 'extra': {'preserved': True}}
        files['evidence/current.json'] = fixtures.text(knowledge).encode()
        files['evidence/current.md'] = b'Current effective knowledge. {{literal}}\r\n'
        result = migration.prepare_migration(files)
        self.assertEqual(result['status'], 'prepared')
        after = store.apply_writes(files, result['writes'])
        for name, content in kept.items():
            self.assertEqual(after[name], content)
        self.assertEqual(after['workitems/1-demo/decision.md'], files['workitems/1-demo/decision.md'])
        self.assertEqual(after['workitems/1-demo/context.md'], files['workitems/1-demo/context.md'])
        self.assertEqual(store.load_yaml(after['evidence/current.yaml']), knowledge)
        self.assertEqual(after['evidence/current.md'], files['evidence/current.md'])
        self.assertNotIn('evidence/current.json', after)
        self.assertFalse(any('/history/' in name or '/reviews/' in name or 'obsolete' in name or 'legacy-spec' in name
                             or name.endswith(('/decisions.md', '/handoff.md')) for name in after))
        self.assertEqual(migration.prepare_migration(after)['status'], 'no_op')


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.workspace = fixtures.WorkspaceTest(methodName='runTest')
        self.workspace.setUp()
        self.addCleanup(self.workspace.doCleanups)

    def test_dry_run_never_writes_and_guard_conflict_preserves_source(self):
        root = self.workspace.a
        original = runtime._working_files(root)
        with tempfile.TemporaryDirectory() as temp:
            instructions = Path(temp) / 'instructions.md'
            instructions.write_text('Explicit business constraints.\n')
            publish = mock.Mock()
            result = migration.migrate(root, dry_run=True, instructions_file=instructions, publish=publish)
            publish.assert_not_called()
            self.assertEqual(result['status'], 'prepared')
            self.assertEqual(runtime._working_files(root), original)

            def conflict(root, writes, identity, message, checks=None):
                # The existing transaction must reject changed original bytes.
                name = 'workitems/A/item.json'
                (root / name).write_text((root / name).read_text() + '\n')
                from project import publish_changes
                return publish_changes(root, writes, identity, message, checks=checks)
            failed = migration.migrate(root, instructions_file=instructions, publish=conflict)
            self.assertEqual(failed['status'], 'partial')
            self.assertIn('byte check conflict', failed['publication']['error'])
            self.assertFalse((root / '.project/project.yaml').exists())
            self.assertTrue((root / '.project/project.json').exists())

    def test_conversion_is_one_guarded_publish_and_repeat_is_noop(self):
        root = self.workspace.a
        owners = {}
        for identifier in ('A', 'B'):
            record = store.item(runtime._working_files(root), identifier)
            owners[identifier] = {'session': identifier + '-owner', 'machine': 'host', 'token': identifier + '-claim'}
            record['owner'] = owners[identifier]
            self.workspace.write(root, f'workitems/{identifier}/item.json', fixtures.text(record))
        fixtures.git(root, 'add', '.')
        fixtures.git(root, 'commit', '--quiet', '-m', 'Retain active owners')
        fixtures.git(root, 'push', '--quiet', 'origin', 'main')
        before = fixtures.git(root, 'rev-parse', 'HEAD')
        with tempfile.TemporaryDirectory() as temp:
            instructions = Path(temp) / 'instructions.md'
            instructions.write_text('Explicit business constraints.\n')
            from project import publish_changes
            result = migration.migrate(root, instructions_file=instructions, publish=publish_changes)
            self.assertEqual(result['publication']['status'], 'published')
            self.assertEqual(runtime.validate_project(root), [])
            self.assertEqual(fixtures.git(root, 'status', '--porcelain'), '')
            self.assertEqual(fixtures.git(root, 'rev-list', '--count', before + '..HEAD'), '1')
            for identifier, owner in owners.items():
                self.assertEqual(store.item(runtime._working_files(root), identifier)['owner'], owner)
            repeat = migration.migrate(root, publish=mock.Mock(side_effect=AssertionError('no-op must not publish')))
            self.assertEqual(repeat['status'], 'no_op')
            # Refresh changed installed instructions under the same v2 claims.
            original = migration.item_entry
            with mock.patch.object(migration, 'item_entry', side_effect=lambda identifier: original(identifier) + '\nUpdated routing.\n'):
                refreshed = migration.migrate(root, publish=publish_changes)
            self.assertEqual(refreshed['status'], 'published', refreshed)
            after = runtime._working_files(root)
            for identifier, owner in owners.items():
                self.assertEqual(store.item(after, identifier)['owner'], owner)

    def test_permission_failure_resume_keeps_and_publishes_original_migration(self):
        import project
        root = self.workspace.a
        before = runtime._working_files(root)
        revision = self.workspace.remote_head()
        lock = root / '.git/project-publish.lock'
        original_open = Path.open

        def denied(path, *args, **kwargs):
            if path == lock:
                raise PermissionError(errno.EPERM, 'harness denied write', str(path))
            return original_open(path, *args, **kwargs)

        def invoke(arguments):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = project.main(['--root', str(root), *arguments])
            return code, json.loads(output.getvalue())

        with tempfile.TemporaryDirectory() as temp:
            instructions = Path(temp) / 'instructions.md'
            instructions.write_text('Explicit business constraints.\n')
            with mock.patch.object(Path, 'open', denied):
                code, initial = invoke(['migrate', '--instructions-file', str(instructions)])
                self.assertEqual(code, 1)
                self.assertEqual(initial['status'], 'partial')
                self.assertTrue(initial['needs_update'])
                self.assertTrue(initial['validated'])
                self.assertGreater(initial['changed_files'], 0)
                self.assertEqual(initial['publication']['code'], 'host_permission_required')
                self.assertEqual(runtime._working_files(root), before)
                saved = runtime.read_json(migration._intent_path(root, initial['migration_operation']))
                arguments = shlex.split(initial['next_command'])[4:]
                code, still_denied = invoke(arguments)
                self.assertEqual(code, 1)
                self.assertEqual(still_denied['status'], 'partial')
                self.assertEqual(still_denied['migration_operation'], initial['migration_operation'])
                self.assertEqual(still_denied['paths'], initial['paths'])
            self.assertEqual(self.workspace.remote_head(), revision)
            # The returned command resumes the persisted intent after permission
            # becomes available; it cannot collapse into an empty sync no-op.
            code, completed = invoke(arguments)
            self.assertEqual(code, 0, completed)
            self.assertEqual(completed['status'], 'published', completed)
            self.assertEqual(completed['migration_operation'], initial['migration_operation'])
            self.assertEqual(completed['paths'], initial['paths'])
            after = runtime._working_files(root)
            for name, value in saved['result']['writes'].items():
                self.assertEqual(after.get(name), value.encode('utf-8') if value is not None else None)
            self.assertEqual(self.workspace.remote_head(), completed['publication']['verified_remote_commit'])
            self.assertNotEqual(self.workspace.remote_head(), revision)
            code, current = invoke(['migrate'])
            self.assertEqual(code, 0)
            self.assertEqual(current['status'], 'no_op')
            self.assertFalse(current['needs_update'])

    def test_migration_publication_rejects_owner_or_business_changes_and_missing_guards(self):
        import project
        source = ConversionTest().source()
        record = store.item(source, '1-demo')
        record['owner'] = {'session': 'other', 'machine': 'host', 'token': 'claim'}
        source['workitems/1-demo/item.json'] = fixtures.text(record).encode()
        prepared = migration.prepare_migration(source, instructions='Current constraints')
        identity = {'session': 'migration', 'token': 'migration-token', 'migration': True}
        bundle = project._bundle(source, prepared['writes'], identity, 'Upgrade', ['1-demo'], prepared['checks'])
        candidate = store.apply_writes(source, bundle['writes'])
        runtime._check_owners(bundle, source, candidate)
        for field, value in (('owner', None), ('title', 'Unauthorized change')):
            with self.subTest(field=field):
                item = store.item(candidate, '1-demo')
                item[field] = value
                changed = store.apply_writes(candidate, store.write_item(candidate, item))
                with self.assertRaisesRegex(runtime.ProjectError, 'deterministic candidate'):
                    runtime._check_owners(bundle, source, changed)
        missing = copy.deepcopy(bundle)
        missing['checks'].pop('workitems/1-demo/requirement.md')
        with self.assertRaisesRegex(runtime.ProjectError, 'guarded deterministic candidate'):
            runtime._check_owners(missing, source, candidate)
        ordinary = dict(bundle, migration=False)
        with self.assertRaisesRegex(runtime.ProjectError, 'owned by another'):
            runtime._check_owners(ordinary, source, candidate)

    def test_empty_resume_requires_authority_and_can_verify_equivalent_publication(self):
        import project
        root = self.workspace.a
        with tempfile.TemporaryDirectory() as temp:
            instructions = Path(temp) / 'instructions.md'
            instructions.write_text('Explicit business constraints.\n')
            initial = migration.migrate(root, instructions_file=instructions,
                                        publish=lambda *args, **kwargs: {'status': 'partial', 'error': 'permission denied'})
        operation = initial['migration_operation']
        record = runtime.read_json(migration._intent_path(root, operation))
        no_action = lambda *args: {'status': 'no_op', 'synchronized': []}
        never_publish = mock.Mock(side_effect=AssertionError('authority must be checked before any new publication'))
        unresolved = migration.resume(root, operation, publish=never_publish, recover=no_action,
                                      inspect=lambda root: {'pending_publications': [{'state': 'candidate'}]})
        self.assertEqual(unresolved['status'], 'blocked')
        self.assertEqual(unresolved['completion'], 'incomplete')
        never_publish.assert_not_called()
        published = project.publish_changes(root, record['result']['writes'], record['identity'], 'Equivalent upgrade',
                                            checks=record['result']['checks'])
        self.assertEqual(published['status'], 'published', published)
        completed = migration.resume(root, operation, publish=never_publish, recover=no_action, inspect=project._status)
        self.assertEqual(completed['status'], 'published', completed)
        self.assertEqual(completed['completion'], 'original_changes_verified')
        self.assertNotIn('authority', completed)
        self.assertNotIn('code', completed)
        self.assertEqual(completed['verified_remote_commit'], self.workspace.remote_head())
        never_publish.assert_not_called()

    def test_verified_backend_receipts_get_new_intent_and_readback(self):
        self.check_backend_migration()

    def test_migration_backend_resume_preserves_active_owners(self):
        self.check_backend_migration(interrupt=True)

    def check_backend_migration(self, interrupt=False):
        import project
        from test_project_cli import V2Adapter
        workspace = self.workspace
        root = workspace.a
        config = copy.deepcopy(workspace.project)
        config['backends']['aone'] = {'space_id': 'space', 'type': 'type', 'category': 'Req',
                                     'status_map': {value: value for value in runtime.STATUSES}}
        workspace.write(root, '.project/project.json', fixtures.text(config))
        for identifier in ('A', 'B'):
            workspace.write(root, f'workitems/{identifier}/requirement.md', '# Requirement\n')
        fixtures.git(root, 'add', '.')
        fixtures.git(root, 'commit', '--quiet', '-m', 'Enable backend')
        fixtures.git(root, 'push', '--quiet', 'origin', 'main')
        backend = V2Adapter(workspace, config)
        request = {'session': 'seed', 'token': 'seed-token', 'machine': 'test',
                   'message': 'Synchronize legacy records', 'operations': [
                       {'op': 'update', 'item': identifier, 'set': {'title': identifier + ' accepted'}}
                       for identifier in ('A', 'B')]}
        project.apply(root, request, adapter_factory=lambda config: backend)
        owners = {}
        for identifier in ('A', 'B'):
            record = store.item(runtime._working_files(root), identifier)
            owners[identifier] = {'session': identifier + '-owner', 'machine': 'host', 'token': identifier + '-claim'}
            record['owner'] = owners[identifier]
            workspace.write(root, f'workitems/{identifier}/item.json', fixtures.text(record))
        fixtures.git(root, 'add', '.')
        fixtures.git(root, 'commit', '--quiet', '-m', 'Retain active owners')
        fixtures.git(root, 'push', '--quiet', 'origin', 'main')
        original = runtime._working_files(root)
        previous = {identifier: store.receipt(original, identifier) for identifier in ('A', 'B')}
        if interrupt:
            backend.fail_after_create.add('A')
        with tempfile.TemporaryDirectory() as temp:
            instructions = Path(temp) / 'instructions.md'
            instructions.write_text('Explicit business constraints.\n')
            def publish(*args, **kwargs):
                return project.publish_changes(*args, **kwargs, adapter_factory=lambda config: backend)
            result = migration.migrate(root, instructions_file=instructions, publish=publish)
        if interrupt:
            self.assertEqual(result['status'], 'partial', result)
            pending = runtime._working_files(root)
            for identifier, owner in owners.items():
                self.assertEqual(store.item(pending, identifier)['owner'], owner)
            receipt = store.receipt(pending, 'A')
            self.assertEqual(receipt['state'], 'unknown')
            actor = receipt['migration_sync']
            # Even the migration's sync identity cannot alter business content.
            altered = dict(pending, **{'workitems/A/requirement.md': b'Unauthorized change\n'})
            self.assertFalse(migration.sync_publication(actor, pending, altered, 'A'))
            resumed = migration.resume(root, result['migration_operation'], publish=publish,
                                       recover=lambda root, session, token: project.resume(
                                           root, session, token, adapter_factory=lambda config: backend), inspect=project._status)
            self.assertEqual(resumed['status'], 'published', resumed)
        else:
            self.assertEqual(result['publication']['status'], 'published', result)
        self.assertEqual(runtime.validate_project(root), [])
        after = runtime._working_files(root)
        for identifier in ('A', 'B'):
            receipt = store.receipt(after, identifier)
            self.assertEqual(store.item(after, identifier)['owner'], owners[identifier])
            self.assertEqual(receipt['state'], 'verified')
            self.assertEqual(receipt['external_id'], previous[identifier]['external_id'])
            self.assertNotEqual(receipt['intent_id'], previous[identifier]['intent_id'])
            self.assertEqual(receipt['content_sha256'], runtime._business_digest(after, identifier))
            self.assertNotIn(f'.project/history/sync-{identifier}.md', after)
        self.assertEqual(backend.creates, ['A', 'B'])
        # Generated routing changes the physical digest without changing the
        # backend's managed projection. Refresh only the verified receipt.
        backend_before = copy.deepcopy(backend.items)
        entry = migration.item_entry
        with mock.patch.object(migration, 'item_entry', side_effect=lambda identifier: entry(identifier) + '\nCurrent routing.\n'):
            refreshed = migration.migrate(root, publish=publish)
        self.assertEqual(refreshed['status'], 'published', refreshed)
        self.assertEqual(backend.items, backend_before)
        self.assertEqual(runtime.validate_project(root), [])
        for identifier, owner in owners.items():
            self.assertEqual(store.item(runtime._working_files(root), identifier)['owner'], owner)


if __name__ == '__main__':
    unittest.main()
