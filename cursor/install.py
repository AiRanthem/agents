#!/usr/bin/env python3
"""Replace Cursor Cloud Agent copies of this dev kit. Not for a developer machine."""

from pathlib import Path
import shutil
import sys

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent


def wipe(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def skill_directories():
    return sorted(path for path in (ROOT / 'skills').iterdir() if (path / 'SKILL.md').is_file())


def install(home):
    home = Path(home)
    cursor = home / '.cursor'
    cursor.mkdir(parents=True, exist_ok=True)
    for source, dest in (
        (DIRECTORY / 'rules', cursor / 'rules'),
        (DIRECTORY / 'agents', cursor / 'agents'),
    ):
        wipe(dest)
        shutil.copytree(source, dest)
    skills = cursor / 'skills'
    wipe(skills)
    skills.mkdir()
    for skill in skill_directories():
        shutil.copytree(skill, skills / skill.name)


def main():
    install(Path.home())
    return 0


if __name__ == '__main__':
    sys.exit(main())
