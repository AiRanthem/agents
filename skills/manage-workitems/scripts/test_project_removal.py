"""Removal safety and happy paths use temporary projects and local bare remotes."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import project_removal as removal
import project_runtime as runtime
import project_store as store
import test_project_runtime as fixtures

git = fixtures.git


class RemovalTests(unittest.TestCase):
    setUp = fixtures.WorkspaceTest.setUp
    configure = fixtures.WorkspaceTest.configure
    write = fixtures.WorkspaceTest.write
    add_item = fixtures.WorkspaceTest.add_item

    def save(self):
        git(self.a, "add", ".")
        git(self.a, "commit", "--quiet", "-m", "save")
        git(self.a, "push", "--quiet", "origin", "main")

    def plan(self):
        return removal.removal_plan(self.a)

    def execute(self, plan):
        return removal.remove(self.a, plan["manifest"], plan["digest"])

    def code(self, external=False):
        self.code_remote = self.directory / "code.git"
        self.code_remote.mkdir()
        git(self.code_remote, "init", "--bare", "--quiet", "--initial-branch=main")
        self.source = self.directory / "source"
        self.source.mkdir()
        git(self.source, "init", "--quiet", "--initial-branch=main")
        self.configure(self.source)
        self.write(self.source, "README.md", "code\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "--quiet", "-m", "seed")
        git(self.source, "remote", "add", "origin", str(self.code_remote))
        git(self.source, "push", "--quiet", "-u", "origin", "main")
        self.target = self.a / "worktrees/A"
        if external:
            main = self.directory / "business"
            main.mkdir()
            self.write(main, "AGENTS.md", "business instructions\n")
            self.project["main_workspace"] = {"id": "business", "name": "business", "repository": None}
            self.project["worktrees"] = {"base": "main_workspace", "path": "worktrees/demo"}
            self.write(self.a, ".project/main-workspace.md", "business routes\n")
            self.write(self.a, ".project-local/main-workspace.json", json.dumps({"id": "business", "root": str(main)}))
            self.target = main / "worktrees/demo/A"
        self.target.parent.mkdir(parents=True, exist_ok=True)
        git(self.source, "worktree", "add", "--quiet", "-b", "feature", str(self.target))
        git(self.source, "config", "branch.feature.project-identity", "project-demo/A/code")
        git(self.source, "push", "--quiet", "-u", "origin", "feature")
        self.project["repositories"][0].update(url=str(self.code_remote), base_ref="refs/heads/main")
        self.write(self.a, ".project/project.json", fixtures.text(self.project))
        relative = "worktrees/demo/A" if external else "worktrees/A"
        self.add_item(self.a, "A", development={"worktree": relative, "branch": "feature",
                      "base_commit": git(self.source, "rev-parse", "HEAD"), "publish_remote": "origin",
                      "publish_url": str(self.code_remote), "publish_ref": "refs/heads/feature"})
        self.save()

    def test_clean_v1_removes_only_exact_project_and_retains_remote(self):
        plan = self.plan()
        self.assertEqual(plan["status"], "awaiting_confirmation", plan.get("blocked"))
        remote = git(self.remote, "show-ref")
        result = self.execute(plan)
        self.assertEqual(result["status"], "removed", result)
        self.assertFalse(self.a.exists())
        self.assertTrue(self.b.is_dir())
        self.assertEqual(git(self.remote, "show-ref"), remote)

    def test_v2_reads_store_and_is_removable(self):
        files = runtime._working_files(self.a)
        self.project["schema_version"] = 2
        (self.a / ".project/project.json").unlink()
        self.write(self.a, ".project/project.yaml", store.dump_yaml(self.project))
        for identifier, item in store.items(files).items():
            (self.a / f"workitems/{identifier}/item.json").unlink()
            for name, value in store.write_item({".project/project.yaml": b""}, item).items():
                self.write(self.a, name, value)
        self.save()
        plan = self.plan()
        self.assertEqual(plan["status"], "awaiting_confirmation", plan.get("blocked"))
        self.assertEqual(self.execute(plan)["status"], "removed")

    def test_exact_root_and_explicit_digest(self):
        with self.assertRaisesRegex(runtime.ProjectError, "exact real"):
            removal.removal_plan(self.a / "workitems")
        plan = self.plan()
        with self.assertRaisesRegex(runtime.ProjectError, "--confirm"):
            removal.remove(self.a, plan["manifest"], "wrong")
        self.assertTrue(self.a.is_dir())

    def test_cli_prepares_program_manifest_and_requires_matching_confirmation(self):
        command = [sys.executable, str(Path(removal.__file__).with_name("project.py")), "--root", str(self.a)]
        result = subprocess.run(command + ["removal-plan"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "ready", plan.get("blocked"))
        self.assertEqual(plan["action"], "obtain_user_confirmation_of_exact_manifest")
        result = subprocess.run(command + ["remove", "--manifest", plan["manifest"], "--confirm", "wrong"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.a.exists())
        result = subprocess.run(command + ["remove", "--manifest", plan["manifest"], "--confirm", plan["digest"]],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["outcome"], "removed")

    def test_changed_manifest_or_state_stops_before_deletion(self):
        plan = self.plan()
        self.write(self.a, "AGENTS.md", "new data\n")
        with self.assertRaisesRegex(runtime.ProjectError, "state changed"):
            self.execute(plan)
        record = store.load_yaml(Path(plan["manifest_path"]).read_bytes())
        record["payload"]["root"] = "/"
        Path(plan["manifest_path"]).write_text(store.dump_yaml(record))
        with self.assertRaisesRegex(runtime.ProjectError, "modified"):
            self.execute(plan)
        self.assertTrue(self.a.exists())

    def test_ignored_untracked_staged_and_unstaged_data_block(self):
        self.write(self.a, "worktrees/private.log", "important ignored data")
        self.write(self.a, "private.txt", "important untracked data")
        self.write(self.a, "AGENTS.md", "staged")
        git(self.a, "add", "AGENTS.md")
        self.write(self.a, "AGENTS.md", "unstaged")
        plan = self.plan()
        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(self.execute(plan)["status"], "blocked")
        self.assertTrue(self.a.exists())

    def test_stash_in_progress_owner_and_unknown_journal_block(self):
        self.write(self.a, "AGENTS.md", "stashed data")
        git(self.a, "stash", "push", "--quiet")
        self.write(self.a, ".git/MERGE_HEAD", self.base)
        self.write(self.a, ".project-local/publish/unknown/journal.json", '{"state":"push_returned_verification_pending"}')
        self.add_item(self.a, "A", owner={"machine": "machine", "session": "session", "token": "token"})
        blockers = " ".join(self.plan()["blocked"])
        for expected in ("stash", "in-progress", "active owner", "unaccounted local"):
            self.assertIn(expected, blockers)
        self.assertTrue(self.a.exists())

    def test_unpublished_commit_blocks(self):
        self.write(self.a, "AGENTS.md", "local only")
        git(self.a, "add", "AGENTS.md")
        git(self.a, "commit", "--quiet", "-m", "unpublished")
        self.assertIn("not recoverable", " ".join(self.plan()["blocked"]))

    def test_unknown_backend_outcome_and_unaccounted_local_file_block(self):
        self.write(self.a, ".project/sync/A.json", '{"state":"unknown"}')
        self.write(self.a, ".project-local/private-notes.md", "preserve me")
        plan = self.plan()
        self.assertEqual(plan["status"], "blocked")
        self.assertIn("unresolved sync: A", plan["blocked"])
        self.assertIn("private-notes.md", " ".join(plan["blocked"]))

    def test_remote_advance_requires_new_manifest(self):
        plan = self.plan()
        self.write(self.b, "AGENTS.md", "new published version")
        git(self.b, "add", "AGENTS.md")
        git(self.b, "commit", "--quiet", "-m", "advance")
        git(self.b, "push", "--quiet", "origin", "main")
        with self.assertRaisesRegex(runtime.ProjectError, "state changed"):
            self.execute(plan)
        self.assertTrue(self.a.exists())

    def test_clean_registered_local_clone_can_be_removed(self):
        self.code()
        # First remove the item worktree normally, then record its absence.
        git(self.source, "worktree", "remove", str(self.target))
        self.add_item(self.a, "A")
        self.save()
        clone = self.a / ".project-local/repos/code"
        clone.parent.mkdir(parents=True)
        git(self.directory, "clone", "--quiet", str(self.code_remote), str(clone))
        self.write(self.a, ".project-local/repositories.yaml", store.dump_yaml({"code": str(clone)}))
        plan = self.plan()
        self.assertEqual(plan["status"], "awaiting_confirmation", plan.get("blocked"))
        self.assertTrue(any(resource["kind"] == "local_clone" for resource in plan["resources"]))
        self.assertEqual(self.execute(plan)["status"], "removed")
        self.assertTrue(self.source.exists())

    def test_clean_linked_worktree_uses_surviving_repository(self):
        self.code()
        plan = self.plan()
        self.assertEqual(plan["status"], "awaiting_confirmation", plan.get("blocked"))
        remote = git(self.code_remote, "show-ref")
        result = self.execute(plan)
        self.assertEqual(result["status"], "removed", result)
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.target.exists())
        self.assertNotIn(str(self.target), git(self.source, "worktree", "list"))
        self.assertEqual(git(self.code_remote, "show-ref"), remote)

    def test_external_worktree_preserves_main_and_shared_container(self):
        self.code(external=True)
        main = self.directory / "business"
        git(main, "init", "--quiet", "--initial-branch=main")
        self.configure(main)
        self.write(main, ".gitignore", "/worktrees/\n")
        git(main, "add", "AGENTS.md", ".gitignore")
        git(main, "commit", "--quiet", "-m", "business workspace")
        sibling = self.target.parent / "unrelated"
        sibling.mkdir()
        self.write(sibling, "keep", "unrelated project")
        plan = self.plan()
        self.assertEqual(plan["status"], "awaiting_confirmation", plan.get("blocked"))
        result = self.execute(plan)
        self.assertEqual(result["status"], "removed", result)
        self.assertTrue(sibling.is_dir())
        self.assertTrue((self.directory / "business/AGENTS.md").is_file())

    def test_new_code_after_confirmation_stops(self):
        self.code()
        plan = self.plan()
        self.write(self.target, "untracked", "keep")
        with self.assertRaisesRegex(runtime.ProjectError, "state changed"):
            self.execute(plan)
        self.assertTrue(self.a.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(self.plan()["status"], "blocked")

    def test_source_configuration_change_stops(self):
        self.code()
        plan = self.plan()
        git(self.source, "config", "unrelated.setting", "changed")
        with self.assertRaisesRegex(runtime.ProjectError, "state changed"):
            self.execute(plan)
        self.assertTrue(self.target.exists())

    def test_unregistered_ignored_nested_repository_blocks(self):
        extra = self.a / "worktrees/other"
        extra.mkdir(parents=True)
        git(extra, "init", "--quiet")
        plan = self.plan()
        self.assertEqual(plan["status"], "blocked")
        self.assertIn("unregistered", " ".join(plan["blocked"]))

    def test_git_remove_failure_is_partial_and_keeps_project(self):
        self.code()
        plan = self.plan()
        original = removal._git
        def reject(root, *args, **kwargs):
            if "remove" in args:
                raise runtime.ProjectError("simulated busy checkout")
            return original(root, *args, **kwargs)
        with mock.patch.object(removal, "_git", side_effect=reject):
            result = self.execute(plan)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["removed"], [])
        self.assertTrue(self.a.exists())
        self.assertTrue(self.target.exists())


if __name__ == "__main__":
    unittest.main()
