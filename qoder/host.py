#!/usr/bin/env python3
"""Check the shared and Qoder-specific skill links on disk."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(home):
    missing = []
    for source_root, target_root in (
        (ROOT / 'skills', home / '.agents/skills'),
        (ROOT / 'qoder/skills', home / '.qoder/skills'),
    ):
        for source in sorted(source_root.glob('*/SKILL.md')):
            link = target_root / source.parent.name
            try:
                if link.readlink() == source.parent:
                    with (link / 'SKILL.md').open('rb') as entry:
                        if entry.read(1):
                            continue
            except OSError:
                pass
            missing.append(f'skill must link to a readable repository entry: {link} -> {source.parent}')
    return {'host': 'qoder', 'disk_ready': not missing, 'missing': missing,
            'runtime_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check'])
    parser.add_argument('--home', type=Path, default=Path.home())
    result = check(parser.parse_args().home.expanduser().resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['disk_ready'] else 1)
