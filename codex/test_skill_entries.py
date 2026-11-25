import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import skill_entries


class SkillEntriesTest(unittest.TestCase):
    def test_skill_installation_checks_links_and_duplicate_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.assertFalse(skill_entries.check(home)['disk_ready'])
            lines = []
            for item in skill_entries.entries(home, bootstrap=True):
                target = Path(item['target'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(item['source'])
                for config in item['config']:
                    lines += ['[[skills.config]]', 'path = ' + json.dumps(config['path']), 'enabled = false']
            path = home / '.codex/config.toml'
            path.write_text('\n'.join(lines))
            self.assertTrue(skill_entries.check(home)['disk_ready'])
            for active in (home / '.codex/skills/adapt-agent-routing/SKILL.md',
                           home / '.agents/skills/review-design/SKILL.md'):
                extra = ['[[skills.config]]', 'path = ' + json.dumps(str(active)), 'enabled = false']
                path.write_text('\n'.join(lines + extra))
                self.assertIn(f'skill must be enabled: {active}', skill_entries.check(home)['missing'])

            path.write_text('\n'.join(lines).replace('enabled = false', 'enabled = true', 1))
            self.assertFalse(skill_entries.check(home)['disk_ready'])

            retired = skill_entries.ROOT / 'skills/retired-example/SKILL.md'
            retired_lines = lines + ['[[skills.config]]', 'path = ' + json.dumps(str(retired))]
            path.write_text('\n'.join(retired_lines + ['enabled = true']))
            self.assertTrue(skill_entries.check(home)['disk_ready'])
            path.write_text('\n'.join(retired_lines + ['enabled = false']))
            self.assertIn(f'retired shared discovery setting: {retired}', skill_entries.check(home)['missing'])

            path.write_text('\n'.join(lines))
            old_link = home / '.codex/skills/review-design'
            retired_root = skill_entries.DIRECTORY / 'skills'
            old_link.symlink_to(retired_root / 'review-design')
            self.assertIn(f'retired skill link: {old_link}', skill_entries.check(home)['missing'])
            old_link.unlink()
            old_link.symlink_to(retired_root / 'absent' / '..' / 'review-design')
            self.assertTrue(skill_entries.check(home)['disk_ready'])
            self.assertTrue(old_link.is_symlink())

            foreign = home / '.agents/skills/adapt-agent-routing'
            foreign.unlink()
            source = skill_entries.ROOT / 'skills/adapt-agent-routing'
            for bad_target in (source / 'absent' / '..', Path(os.path.relpath(source, foreign.parent))):
                foreign.symlink_to(bad_target)
                self.assertFalse(skill_entries.check(home)['disk_ready'])
                foreign.unlink()
            foreign.mkdir()
            (foreign / 'SKILL.md').write_text('third-party skill')
            alias = str(foreign / 'SKILL.md')
            safe_entries = skill_entries.entries(home)
            self.assertFalse(any(item['path'] == alias for entry in safe_entries for item in entry['config']))
            before = path.read_bytes()
            self.assertIn(f'skill must link to repository entry by absolute path: {foreign}',
                          skill_entries.check(home)['missing'])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual((foreign / 'SKILL.md').read_text(), 'third-party skill')

    def test_native_routing_metadata_uses_default_implicit_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            name = 'adapt-agent-routing'
            shared = repo / 'skills' / name / 'SKILL.md'
            shared.parent.mkdir(parents=True)
            skill = f'---\nname: {name}\ndescription: test skill\n---\n'
            shared.write_text(skill)
            source = repo / 'codex/skills' / name
            with mock.patch.multiple(skill_entries, ROOT=repo, DIRECTORY=repo / 'codex'):
                (source / 'agents').mkdir(parents=True)
                (source / 'SKILL.md').write_text(skill)
                metadata = source / 'agents/openai.yaml'
                metadata.write_text('interface:\n  display_name: ""\n')
                self.assertIn('expected a nonempty interface.display_name', skill_entries.source_gaps()[0])
                metadata.write_text('interface:\n  display_name: "Adapt Agent Routing"\n')
                self.assertEqual(skill_entries.source_gaps(), [])


if __name__ == '__main__':
    unittest.main()
