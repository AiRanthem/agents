from pathlib import Path
import tempfile
import unittest

import host


class SkillLinkTest(unittest.TestCase):
    def test_missing_installation_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = host.check(home)
            self.assertFalse(result['disk_ready'])
            self.assertFalse(result['runtime_verified'])
            self.assertEqual(list(home.iterdir()), [])

    def test_shared_and_native_links_require_the_expected_source(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for source_root, target_root in (
                (host.ROOT / 'skills', home / '.agents/skills'),
                (host.ROOT / 'qoder/skills', home / '.qoder/skills'),
            ):
                target_root.mkdir(parents=True)
                for source in source_root.glob('*/SKILL.md'):
                    (target_root / source.parent.name).symlink_to(source.parent)
            self.assertTrue(host.check(home)['disk_ready'])
            for target in [home / '.agents/skills/install', home / '.qoder/skills/tune-ui']:
                target.unlink()
                target.mkdir()
                (target / 'SKILL.md').write_text('foreign skill')
            gaps = host.check(home)['missing']
            self.assertEqual(len(gaps), 2)
            self.assertTrue(any('.agents/skills/install' in gap for gap in gaps))
            self.assertTrue(any('.qoder/skills/tune-ui' in gap for gap in gaps))


if __name__ == '__main__':
    unittest.main()
