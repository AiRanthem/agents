"""Local-only tests for deterministic project initialization."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import project_init
import project_store as store


def git(path: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def commit_file(path: Path, name: str, content: str) -> str:
    (path / name).write_text(content, encoding="utf-8")
    git(path, "add", name)
    git(path, "-c", "user.name=Test User", "-c", "user.email=test@example.invalid",
        "commit", "--no-gpg-sign", "-m", "seed")
    return git(path, "rev-parse", "HEAD")


class ProjectInitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="project-init-test-")
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(self.remote)], check=True)
        # Leave HEAD pointing at its unborn default branch. Initialization must
        # query and publish the selected ref directly without consulting it.
        self.destination = self.root / "projects" / "demo"
        self.config = {
            "schema_version": 1,
            "id": "demo-project",
            "name": "Demo Project",
            "storage": {"remote": "origin", "branch": "projects/demo", "url": str(self.remote)},
            "backends": {"aone": None},
            "repositories": [],
        }
        self.identity = mock.patch.dict(os.environ, {
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        })
        self.identity.start()
        self.addCleanup(self.identity.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prepare_is_validated_uncommitted_and_tracks_placeholder(self):
        result = project_init.init_project(self.destination, self.config,
                                           "Shared project background.\n")
        self.assertEqual(result["status"], "prepared")
        self.assertFalse(result["published"])
        status_paths = {line[3:] for line in git(self.destination, "status", "--porcelain").splitlines()}
        self.assertEqual(status_paths, {".gitignore", "AGENTS.md", ".project/", "worktrees/"})
        self.assertEqual((self.destination / "worktrees/.gitkeep").read_bytes(), b"")
        self.assertIn("Shared project background.", (self.destination / ".project/context.md").read_text())
        self.assertIn("demo-project", (self.destination / "AGENTS.md").read_text())
        self.assertEqual(store.load_yaml((self.destination / ".project/project.yaml").read_bytes())["schema_version"], 2)
        self.assertFalse((self.destination / ".project/project.json").exists())
        self.assertEqual(git(self.destination, "config", "--get", "remote.origin.fetch"),
                         "+refs/heads/projects/demo:refs/remotes/origin/projects/demo")

    def test_publish_uses_only_exact_selected_ref_and_clone_recovers(self):
        unrelated = self.root / "seed"
        unrelated.mkdir()
        git(unrelated, "init", "--quiet")
        commit_file(unrelated, "README.md", "unrelated branch\n")
        git(unrelated, "push", str(self.remote), "HEAD:refs/heads/other")
        # The remote's symbolic HEAD is deliberately left at an unborn branch.
        self.assertEqual(git(self.remote, "symbolic-ref", "HEAD"), "refs/heads/master")

        result = project_init.init_project(self.destination, self.config,
                                           "Recoverable project.\n", publish=True)
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["ref"], "refs/heads/projects/demo")
        self.assertEqual(result["commit"], result["verified_remote_commit"])
        refs = git(self.remote, "for-each-ref", "--format=%(refname)", "refs/heads")
        self.assertEqual(set(refs.splitlines()), {"refs/heads/other", "refs/heads/projects/demo"})
        self.assertEqual(git(self.destination, "rev-parse", "--abbrev-ref", "@{upstream}"),
                         "origin/projects/demo")

        clone = self.root / "clone"
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "--quiet", "--branch", "projects/demo",
                        str(self.remote), str(clone)], check=True)
        self.assertEqual((clone / "worktrees/.gitkeep").read_bytes(), b"")
        self.assertEqual((clone / ".project/project.yaml").read_text(),
                         (self.destination / ".project/project.yaml").read_text())
        self.assertEqual(git(clone, "status", "--porcelain"), "")

    def test_existing_nonempty_destination_is_left_untouched(self):
        self.destination.mkdir(parents=True)
        marker = self.destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(project_init.ProjectInitError) as caught:
            project_init.init_project(self.destination, self.config, "Context")
        self.assertIn("nonempty", str(caught.exception))
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.destination / ".git").exists())

    def test_existing_selected_remote_branch_stops_without_reusing_it(self):
        seed = self.root / "seed"
        seed.mkdir()
        git(seed, "init", "--quiet")
        commit_file(seed, "README.md", "existing unrelated data\n")
        git(seed, "push", str(self.remote), "HEAD:refs/heads/projects/demo")
        with self.assertRaises(project_init.ProjectInitError) as caught:
            project_init.init_project(self.destination, self.config, "Context", publish=True)
        self.assertIn("already exists", str(caught.exception))
        self.assertEqual(caught.exception.result["status"], "failed")
        self.assertTrue(self.destination.exists())
        self.assertFalse(git(self.destination, "rev-parse", "--verify", "HEAD", check=False))
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/projects/demo"),
                         git(seed, "rev-parse", "HEAD"))

    def test_associated_project_requires_explicit_routing_context(self):
        config = dict(self.config)
        config["main_workspace"] = {
            "id": "main", "name": "Main Workspace", "repository": None,
        }
        with self.assertRaises(project_init.ProjectInitError) as caught:
            project_init.init_project(self.destination, config, "Context")
        self.assertIn("main_workspace_context", str(caught.exception))
        self.assertFalse(self.destination.exists())

    def test_associated_project_records_routes_and_optional_local_binding(self):
        main_root = self.root / "main-workspace"
        main_root.mkdir()
        git(main_root, "init", "--quiet")
        (main_root / "AGENTS.md").write_text("# Main instructions\n", encoding="utf-8")
        git(main_root, "remote", "add", "origin", "https://example.invalid/main.git")
        config = dict(self.config)
        config["main_workspace"] = {
            "id": "main", "name": "Main Workspace",
            "repository": {"url": "https://example.invalid/main.git", "ref": "refs/heads/main"},
        }
        before = git(main_root, "status", "--porcelain")
        result = project_init.init_project(
            self.destination, config, "Project background.", publish=False,
            main_workspace_context="Read `AGENTS.md` and use `skills/domain/SKILL.md` for domain work.",
            local_binding={"id": "main", "root": str(main_root)},
        )
        self.assertEqual(result["status"], "prepared")
        route = (self.destination / ".project/main-workspace.md").read_text(encoding="utf-8")
        self.assertIn("Main Workspace", route)
        self.assertIn("skills/domain/SKILL.md", route)
        self.assertTrue((self.destination / ".project-local/main-workspace.json").is_file())
        self.assertEqual(git(main_root, "status", "--porcelain"), before)


if __name__ == "__main__":
    unittest.main()
