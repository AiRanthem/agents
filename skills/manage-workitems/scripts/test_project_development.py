"""Real local Git remotes exercise worktree and reviewed-delivery boundaries."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import project_development as development
import project_store as store
import project_migration as migration
import project_workflow as workflow


def git(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    return result.stdout.decode().strip()


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.area = Path(self.temp.name).resolve()
        self.root = self.area / "project"
        self.root.mkdir()
        git(self.root, "init", "-b", "master")
        self.remote = self.area / "remote.git"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "--initial-branch=main")
        self.code = self.area / "code"
        self.code.mkdir()
        git(self.code, "init", "-b", "main")
        git(self.code, "config", "user.email", "test@example.invalid")
        git(self.code, "config", "user.name", "Test")
        (self.code / "code.txt").write_text("baseline\n")
        git(self.code, "add", ".")
        git(self.code, "commit", "-m", "baseline")
        git(self.code, "remote", "add", "upstream", str(self.remote))
        git(self.code, "push", "upstream", "main")
        self.project = {"schema_version": 2, "id": "demo", "name": "Demo", "repositories": [
            {"id": "code", "url": str(self.remote), "base_remote": "upstream", "base_ref": "refs/heads/main"}]}
        (self.root / ".project").mkdir()
        # worktree_location uses runtime layout resolution; prepare doesn't inspect physical authority.
        (self.root / ".project/project.json").write_text(json.dumps(self.project))
        self.item = {"id": "1-feature", "repository": "code", "development": None}

    def prepare(self, **options):
        return development.prepare(self.root, self.item, self.project,
                                   options={"repository_path": str(self.code), **options})

    def worktree(self):
        return development.worktree_location(self.root, self.item, self.project)

    def commit(self, path, text="implemented\n"):
        (path / "code.txt").write_text(text)
        git(path, "add", ".")
        git(path, "commit", "-m", "implementation")
        return git(path, "rev-parse", "HEAD")

    def migrate_legacy_development(self):
        (self.code / "AGENTS.md").write_text("Original legacy code instructions.\n")
        git(self.code, "add", "AGENTS.md")
        git(self.code, "commit", "-m", "legacy instructions")
        git(self.code, "push", "upstream", "main")
        branch = "feature/multi-infra-shared-state-261014"
        location = self.root / "worktrees/multi-infra-shared-state"
        git(self.code, "worktree", "add", "-b", branch, str(location), "HEAD")
        git(location, "push", "--set-upstream", "upstream", branch)
        original = {"worktree": "worktrees/multi-infra-shared-state", "branch": branch,
                    "base_commit": git(location, "rev-parse", "HEAD"),
                    "base_ref": "upstream/refs/heads/main", "publish_remote": "upstream",
                    "publish_ref": "refs/heads/" + branch}
        source = {"id": self.item["id"], "title": "Legacy implementation", "kind": "development",
                  "status": "awaiting_delivery", "repository": "code", "owner": None,
                  "depends_on": [], "development": original,
                  "delivery": {"required": ["merged"], "status": "pending", "evidence": []}}
        config = dict(self.project, schema_version=1)
        files = {".project/project.json": json.dumps(config).encode(), "AGENTS.md": b"Legacy custom instructions",
                 f"workitems/{self.item['id']}/item.json": json.dumps(source).encode(),
                 f"workitems/{self.item['id']}/requirement.md": b"Keep the existing implementation"}
        result = migration.prepare_migration(files, instructions="Approved project instructions")
        self.assertEqual(result["status"], "prepared")
        converted = store.apply_writes(files, result["writes"])
        for name, value in result["writes"].items():
            path = self.root / name
            if value is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
        self.project = store.project(converted)
        self.item = store.item(converted, self.item["id"])
        return location, original

    def test_autonomous_preparation_keeps_source_branch_local_and_reuses_dirty_worktree(self):
        remote_before = git(self.remote, "show-ref")
        with mock.patch.object(development, "_git", wraps=development._git) as calls:
            prepared = development.prepare(self.root, self.item, self.project,
                options={"repository_path": str(self.code)}, publish_branch=False)
        self.assertFalse(prepared["branch_published"])
        self.assertFalse(any("push" in call.args[1:] for call in calls.call_args_list))
        self.assertEqual(git(self.remote, "show-ref"), remote_before)
        self.item["development"] = prepared
        location = self.worktree()
        (location / "code.txt").write_text("unsubmitted implementation\n")
        again = development.prepare(self.root, self.item, self.project, publish_branch=False)
        self.assertEqual(again, prepared)
        self.assertEqual((location / "code.txt").read_text(), "unsubmitted implementation\n")
        self.assertEqual(git(self.remote, "show-ref"), remote_before)
        self.assertEqual(git(location, "rev-parse", "HEAD"), prepared["base_commit"])

    def test_authenticated_legacy_context_and_prepare_preserve_code_and_remote(self):
        location, original = self.migrate_legacy_development()
        (location / "code.txt").write_text("staged legacy patch\n")
        git(location, "add", "code.txt")
        (location / "code.txt").write_text("unstaged legacy patch\n")
        config_before = (self.code / ".git/config").read_bytes()
        staged_before = git(location, "diff", "--cached", "--binary")
        status_before = git(location, "status", "--porcelain")
        remote_before = git(self.remote, "show-ref")
        payload = self.read_payload("context-update")
        self.assertIn({"path": str(location / "AGENTS.md"), "content": "Original legacy code instructions.\n"}, payload)
        self.assertEqual((self.code / ".git/config").read_bytes(), config_before)
        self.item["owner"] = {"session": "published-owner", "token": "published-token"}
        with mock.patch.object(development, "_git", wraps=development._git) as calls:
            upgraded = self.prepare()
        self.assertFalse(any("push" in call.args[1:] for call in calls.call_args_list))
        self.assertEqual(upgraded["worktree"], original["worktree"])
        self.assertEqual(upgraded["branch"], original["branch"])
        self.assertEqual(upgraded["base_ref"], "refs/heads/main")
        self.assertEqual(upgraded["base_remote"], "upstream")
        self.assertEqual(upgraded["legacy_source_hash"], self.item["development"]["legacy_source_hash"])
        self.assertEqual(git(location, "status", "--porcelain"), status_before)
        self.assertEqual(git(location, "diff", "--cached", "--binary"), staged_before)
        self.assertEqual(git(self.remote, "show-ref"), remote_before)
        self.item["development"] = upgraded
        self.assertEqual(self.prepare(), upgraded)
        self.assertIn(location / "AGENTS.md", development.instruction_files(self.root, self.item, self.project))
        with self.assertRaisesRegex(development.ProjectError, "independently reviewed"):
            development.verify_merged(self.root, self.item, self.project)

    def test_legacy_compatibility_requires_exact_migration_provenance(self):
        self.migrate_legacy_development()
        authenticated = copy.deepcopy(self.item["development"])
        del self.item["development"]["legacy_source_hash"]
        with self.assertRaisesRegex(development.ProjectError, "configuration"):
            development.instruction_files(self.root, self.item, self.project)
        self.item["development"] = copy.deepcopy(authenticated)
        self.item["development"]["legacy_source_hash"] = "0" * 64
        with self.assertRaisesRegex(development.ProjectError, "source hash"):
            development.instruction_files(self.root, self.item, self.project)
        self.item["development"] = copy.deepcopy(authenticated)
        self.item["development"]["branch"] = "feature/unrelated"
        with self.assertRaisesRegex(development.ProjectError, "original migration source"):
            development.instruction_files(self.root, self.item, self.project)
        self.item["development"] = copy.deepcopy(authenticated)
        git(self.code, "config", "branch." + authenticated["branch"] + ".project-identity", "another-project/item/code")
        with self.assertRaisesRegex(development.ProjectError, "identity"):
            development.instruction_files(self.root, self.item, self.project)

    def associate_main(self):
        main = self.area / "business"
        main.mkdir()
        (main / "AGENTS.md").write_text("Original business instructions: release needs explicit authorization.\n")
        self.project["main_workspace"] = {"id": "business", "name": "Business", "repository": None}
        (self.root / ".project/main-workspace.md").write_text("Navigation summary cannot replace original instructions.\n")
        local = self.root / ".project-local"
        local.mkdir(exist_ok=True)
        # Keep the platform's normal temp alias in the selected binding; returned
        # original paths must still be canonical and readable.
        binding = {"id": "business", "root": str(Path(self.temp.name) / "business")}
        (local / "main-workspace.json").write_text(json.dumps(binding))
        return main

    def read_payload(self, operation="log-record"):
        files = {".project/project.yaml": store.dump_yaml(self.project).encode(),
                 "AGENTS.md": b"Project entry instructions"}
        return workflow._read_payload(self.root, files, self.item, operation)

    def test_instruction_payload_includes_original_main_for_management_without_code(self):
        main = self.associate_main()
        (self.area / "AGENTS.md").write_text("Original ancestor business boundary.\n")
        self.item["repository"] = None
        payload = self.read_payload()
        bodies = {entry["path"]: entry["content"] for entry in payload}
        self.assertEqual(bodies[str(main / "AGENTS.md")], (main / "AGENTS.md").read_text())
        self.assertEqual(bodies[str(self.area / "AGENTS.md")], "Original ancestor business boundary.\n")
        self.assertFalse((self.root / ".project-local/repos").exists())

    def test_missing_or_unsafe_original_main_instructions_block(self):
        self.project["main_workspace"] = {"id": "business", "name": "Business", "repository": None}
        (self.root / ".project/main-workspace.md").write_text("Required original instructions must be read.")
        with self.assertRaisesRegex(development.ProjectError, "not bound"):
            development.instruction_files(self.root, self.item, self.project)
        with self.assertRaisesRegex(development.ProjectError, "not bound"):
            self.prepare()
        self.assertFalse((self.root / "worktrees").exists())
        self.assertFalse((self.root / ".project-local/repositories.yaml").exists())
        main = self.associate_main()
        agents = main / "AGENTS.md"
        agents.unlink()
        with self.assertRaisesRegex(development.ProjectError, "original AGENTS"):
            development.instruction_files(self.root, self.item, self.project)
        outside = self.area / "outside-instructions.md"
        outside.write_text("Uncontrolled symlink target")
        agents.symlink_to(outside)
        with self.assertRaisesRegex(development.ProjectError, "regular file"):
            development.instruction_files(self.root, self.item, self.project)
        agents.unlink()
        agents.write_text("Original main instructions")
        (self.root / ".project-local/main-workspace.json").write_text(json.dumps({"id": "other", "root": str(main)}))
        with self.assertRaisesRegex(development.ProjectError, "binding id"):
            development.instruction_files(self.root, self.item, self.project)

    def test_instruction_payload_reads_actual_worktree_original_and_rejects_symlink(self):
        (self.code / "AGENTS.md").write_text("Original code instructions: verify exact target before delivery.\n")
        git(self.code, "add", "AGENTS.md")
        git(self.code, "commit", "-m", "code instructions")
        git(self.code, "push", "upstream", "main")
        self.item["development"] = self.prepare()
        code_instruction = self.worktree() / "AGENTS.md"
        payload = self.read_payload("development-start")
        self.assertIn({"path": str(code_instruction), "content": code_instruction.read_text()}, payload)
        code_instruction.unlink()
        code_instruction.symlink_to(self.code / "AGENTS.md")
        with self.assertRaisesRegex(development.ProjectError, "regular file"):
            development.instruction_files(self.root, self.item, self.project)

    def test_missing_development_instructions_are_explicit_metadata_only(self):
        main = self.associate_main()
        self.item["development"] = {"worktree": "worktrees/removed", "branch": "feature/removed",
                                    "base_commit": git(self.code, "rev-parse", "HEAD")}
        with self.assertRaisesRegex(development.ProjectError, "checkout root"):
            development.instruction_files(self.root, self.item, self.project)
        paths = development.instruction_files(self.root, self.item, self.project, allow_missing_development=True)
        self.assertIn(main / "AGENTS.md", paths)
        self.assertFalse((self.root / "worktrees/removed").exists())
        with self.assertRaises(development.ProjectError):
            self.prepare()
        (self.code / "AGENTS.md").write_text("Original canonical checkout instructions.\n")
        development._save_binding(self.root, self.project["repositories"][0], self.code)
        paths = development.instruction_files(self.root, self.item, self.project, allow_missing_development=True)
        self.assertIn(self.code / "AGENTS.md", paths)
        (self.root / "worktrees").mkdir()
        (self.root / "worktrees/removed").symlink_to(self.area / "missing-target", target_is_directory=True)
        with self.assertRaisesRegex(development.ProjectError, "symlink"):
            development.instruction_files(self.root, self.item, self.project, allow_missing_development=True)
        (self.root / "worktrees/removed").unlink()
        self.item["development"]["worktree"] = "worktrees/../outside"
        with self.assertRaisesRegex(development.ProjectError, "normalized relative path"):
            development.instruction_files(self.root, self.item, self.project, allow_missing_development=True)

    def test_cleaned_metadata_payload_keeps_missing_checkout_fallback_scoped(self):
        self.item["development"] = {"worktree": "worktrees/removed", "branch": "feature/removed", "base_commit": git(self.code, "rev-parse", "HEAD")}
        for cleanup in ("pending", "done"):
            self.item["cleanup"] = cleanup
            for operation in workflow.METADATA_OPERATIONS:
                with self.subTest(cleanup=cleanup, operation=operation):
                    if cleanup == "done" or operation in {"cleanup-record", "kind-update"}:
                        self.read_payload(operation)
                    else:
                        with self.assertRaisesRegex(development.ProjectError, "checkout root"):
                            self.read_payload(operation)
        for operation in ("design-update", "design-review", "development-start", "development-finish", "delivery-record"):
            with self.subTest(operation=operation), self.assertRaisesRegex(development.ProjectError, "checkout root"):
                self.read_payload(operation)
        self.assertFalse((self.root / "worktrees/removed").exists())

    def test_discard_reservation_reprepares_default_and_explicit_location_at_current_base(self):
        for mode in ("default", "explicit"):
            with self.subTest(mode=mode):
                self.item = {"id": "1-" + mode, "repository": "code", "development": None}
                self.item["development"] = self.prepare()
                original = copy.deepcopy(self.item["development"])
                reservation = development.reservation_for_discard(self.root, self.item, self.project)
                git(self.code, "worktree", "remove", str(self.worktree()))
                self.item["development"] = None
                self.item["workflow"] = {"development_discard_record": "discarded"}
                record = {"id": "discarded", "item": self.item["id"], "kind": "cleanup", "status": "done", "mode": "verify",
                          "approval_source": "User explicitly discards old development", "development_snapshot": original,
                          "reservation_snapshot": reservation}
                path = self.root / ("workitems/" + self.item["id"] + "/records/discarded.yaml")
                path.parent.mkdir(parents=True)
                path.write_text(store.dump_yaml(record))
                self.assertFalse((self.root / original["worktree"]).exists())
                current = self.commit(self.code, "New target baseline " + mode + "\n")
                git(self.code, "push", "upstream", "main")
                options = {"branch": "feature/restarted", "worktree": "worktrees/restarted"} if mode == "explicit" else {}
                prepared = self.prepare(**options)
                self.assertEqual(prepared["base_commit"], current)
                self.assertNotEqual(prepared["branch"], original["branch"])
                if mode == "explicit":
                    self.assertEqual(prepared["branch"], options["branch"])
                    self.assertEqual(prepared["worktree"], options["worktree"])
                    self.assertFalse((self.root / original["worktree"]).exists())
                self.assertEqual(git(self.remote, "rev-parse", original["publish_ref"]), original["base_commit"])
                # Preparation can be retried before its development metadata is published.
                self.assertEqual(self.prepare(**options), prepared)

    def test_instruction_lookup_never_provisions_unknown_code_checkout(self):
        self.assertEqual(development.instruction_files(self.root, self.item, self.project), [])
        self.assertFalse((self.root / ".project-local").exists())

    def test_exact_base_published_upstream_and_reuse_dirty_worktree(self):
        # The current checkout may be on an unrelated commit; start from exact remote base.
        baseline = git(self.code, "rev-parse", "HEAD")
        git(self.code, "checkout", "-b", "unrelated")
        self.commit(self.code, "other\n")
        self.item["development"] = record = self.prepare()
        self.assertEqual(record["base_commit"], baseline)
        self.assertEqual(git(self.code, "branch", "--show-current"), "unrelated")
        self.assertEqual(git(self.worktree(), "rev-parse", "HEAD"), baseline)
        self.assertEqual(git(self.worktree(), "rev-parse", "@{upstream}"), baseline)
        self.assertEqual(git(self.worktree(), "config", "branch." + record["branch"] + ".merge"), record["publish_ref"])
        (self.worktree() / "dirty.txt").write_text("retain me")
        reused = self.prepare()
        self.assertEqual(reused, record)
        self.assertEqual((self.worktree() / "dirty.txt").read_text(), "retain me")

    def test_recover_interrupted_record_only_with_same_identity(self):
        record = self.prepare()
        self.item["owner"] = {"session": "different-session", "token": "new-owner"}
        recovered = self.prepare()
        self.assertEqual(recovered, record)
        git(self.code, "config", "--unset", "branch." + record["branch"] + ".project-identity")
        with self.assertRaisesRegex(development.ProjectError, "identity"):
            self.prepare()

    def test_existing_remote_branch_cannot_be_adopted(self):
        git(self.code, "push", "upstream", "HEAD:refs/heads/feature/demo/1-feature")
        with self.assertRaisesRegex(development.ProjectError, "identity"):
            self.prepare(branch="feature/demo/1-feature")
        self.assertFalse((self.root / "worktrees/1-feature").exists())

    def test_remote_and_target_configuration_changes_block(self):
        self.item["development"] = self.prepare()
        git(self.code, "remote", "set-url", "upstream", str(self.area / "other.git"))
        with self.assertRaisesRegex(development.ProjectError, "URL"):
            self.prepare()

    def test_remote_url_preserves_git_failure_and_rejects_ambiguous_values(self):
        with self.assertRaisesRegex(development.ProjectError, "git remote failed:.*No such remote 'missing'"):
            development._url(self.code, "missing", push=True)
        git(self.code, "config", "--add", "remote.upstream.pushurl", str(self.remote))
        git(self.code, "config", "--add", "remote.upstream.pushurl", str(self.area / "other.git"))
        with self.assertRaisesRegex(development.ProjectError, "unambiguous effective URL; found 2"):
            development._url(self.code, "upstream", push=True)
        empty = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
        with mock.patch.object(development, "_git", return_value=empty):
            with self.assertRaisesRegex(development.ProjectError, "unambiguous effective URL; found 0"):
                development._url(self.code, "upstream")

    def test_no_remote_guessing(self):
        del self.project["repositories"][0]["base_remote"]
        with self.assertRaisesRegex(development.ProjectError, "guessing"):
            self.prepare()

    def test_push_namespace_mapping(self):
        git(self.code, "config", "remote.upstream.push", "refs/heads/*:refs/heads/devkits/*")
        record = self.prepare()
        self.assertEqual(record["publish_ref"], "refs/heads/devkits/" + record["branch"])
        self.assertEqual(git(self.remote, "rev-parse", record["publish_ref"]), record["base_commit"])

    def test_separate_publish_repository_is_explicit(self):
        fork = self.area / "fork.git"
        fork.mkdir()
        git(fork, "init", "--bare")
        git(self.code, "remote", "add", "publish", str(fork))
        self.project["repositories"][0].update(publish_remote="publish", publish_url=str(fork))
        record = self.prepare()
        self.assertEqual(record["base_url"], str(self.remote))
        self.assertEqual(record["publish_url"], str(fork))
        self.assertEqual(git(fork, "rev-parse", record["publish_ref"]), record["base_commit"])

    def test_snapshot_refuses_uncommitted_submodule_content(self):
        git(self.code, "-c", "protocol.file.allow=always", "submodule", "add", str(self.remote), "dependency")
        (self.code / "dependency/code.txt").write_text("uncommitted submodule implementation\n")
        with self.assertRaisesRegex(development.ProjectError, "submodule content"):
            development.snapshot(self.code)
        self.assertIn("uncommitted", (self.code / "dependency/code.txt").read_text())

    def test_dirty_snapshot_preserves_index_and_requires_committed_tree(self):
        self.item["development"] = self.prepare()
        tree = self.worktree()
        (tree / "code.txt").write_text("staged\n")
        git(tree, "add", "code.txt")
        (tree / "code.txt").write_text("reviewed\n")
        (tree / "new.txt").write_text("new content")
        before = git(tree, "diff", "--cached")
        reviewed = development.snapshot(tree)
        self.assertFalse(reviewed["clean"])
        self.assertEqual(git(tree, "diff", "--cached"), before)
        self.item["development"]["reviewed_snapshot"] = reviewed
        with self.assertRaisesRegex(development.ProjectError, "reviewed implementation tree"):
            development.verify_merged(self.root, self.item, self.project)
        git(tree, "add", "-A")
        git(tree, "commit", "-m", "reviewed implementation")
        source = git(tree, "rev-parse", "HEAD")
        git(tree, "push", "upstream", "HEAD:refs/heads/main")
        evidence = development.verify_merged(self.root, self.item, self.project, evidence={"commit": source})
        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["source_commit"], source)

    def test_unmerged_and_stale_review_are_rejected(self):
        self.item["development"] = self.prepare()
        tree = self.worktree()
        source = self.commit(tree)
        self.item["development"]["reviewed_snapshot"] = development.snapshot(tree)
        with self.assertRaisesRegex(development.ProjectError, "not an ancestor"):
            development.verify_merged(self.root, self.item, self.project)
        changed = self.commit(tree, "not reviewed\n")
        git(tree, "push", "upstream", "HEAD:refs/heads/main")
        with self.assertRaisesRegex(development.ProjectError, "reviewed implementation tree"):
            development.verify_merged(self.root, self.item, self.project, evidence={"commit": changed})
        self.assertTrue(development.verify_merged(self.root, self.item, self.project,
                                               evidence={"commit": source})["verified"])

    def test_no_review_and_baseline_cannot_claim_delivery(self):
        self.item["development"] = self.prepare()
        with self.assertRaisesRegex(development.ProjectError, "independently reviewed"):
            development.verify_merged(self.root, self.item, self.project)
        self.item["development"]["reviewed_snapshot"] = development.snapshot(self.worktree())
        with self.assertRaisesRegex(development.ProjectError, "baseline"):
            development.verify_merged(self.root, self.item, self.project)

    def test_managed_clone_configures_explicit_separate_publish_remote(self):
        fork = self.area / "fork.git"
        fork.mkdir()
        git(fork, "init", "--bare")
        self.project["repositories"][0].update(publish_remote="inner", publish_url=str(fork))
        self.item["development"] = development.prepare(self.root, self.item, self.project)
        clone = self.root / ".project-local/repos/code"
        self.assertEqual(git(clone, "remote", "get-url", "--push", "inner"), str(fork))
        self.assertEqual(git(fork, "rev-parse", self.item["development"]["publish_ref"]),
                         self.item["development"]["base_commit"])
        self.assertEqual(development.prepare(self.root, self.item, self.project), self.item["development"])

    def test_interrupted_managed_clone_uses_declared_remote_map(self):
        fork = self.area / "fork.git"
        fork.mkdir()
        git(fork, "init", "--bare")
        clone = self.root / ".project-local/repos/code"
        clone.parent.mkdir(parents=True)
        git(self.root, "clone", "--no-checkout", "--origin", "upstream", str(self.remote), str(clone))
        self.project["repositories"][0].update(publish_remote="inner", remotes={"inner": str(fork)})
        record = development.prepare(self.root, self.item, self.project)
        self.assertEqual(record["publish_url"], str(fork))
        self.assertEqual(git(fork, "rev-parse", record["publish_ref"]), record["base_commit"])

    def test_managed_clone_does_not_guess_or_replace_publish_remote(self):
        repo = self.project["repositories"][0]
        repo["publish_remote"] = "inner"
        with self.assertRaisesRegex(development.ProjectError, "requires an explicit"):
            development.prepare(self.root, self.item, self.project)
        clone = self.root / ".project-local/repos/code"
        self.assertEqual(git(clone, "remote"), "upstream")
        git(clone, "remote", "add", "inner", str(self.area / "other.git"))
        before = (clone / ".git/config").read_bytes()
        repo["publish_url"] = str(self.remote)
        with self.assertRaisesRegex(development.ProjectError, "publish remote URL does not match"):
            development.prepare(self.root, self.item, self.project)
        self.assertEqual((clone / ".git/config").read_bytes(), before)
        self.assertFalse((self.root / ".project-local/repositories.yaml").exists())

    def test_user_checkout_missing_publish_remote_is_not_modified(self):
        self.project["repositories"][0].update(publish_remote="inner", publish_url=str(self.remote))
        before = (self.code / ".git/config").read_bytes()
        with self.assertRaisesRegex(development.ProjectError, "No such remote 'inner'"):
            self.prepare()
        self.assertEqual((self.code / ".git/config").read_bytes(), before)
        development._save_binding(self.root, self.project["repositories"][0], self.code)
        with self.assertRaisesRegex(development.ProjectError, "No such remote 'inner'"):
            development.prepare(self.root, self.item, self.project)
        self.assertEqual((self.code / ".git/config").read_bytes(), before)

    def test_clone_fallback_and_binding_reuse(self):
        self.project["repositories"][0]["base_remote"] = "origin"
        self.item["development"] = development.prepare(self.root, self.item, self.project)
        self.assertTrue((self.root / ".project-local/repos/code/.git").is_dir())
        self.assertTrue((self.root / ".project-local/repositories.yaml").is_file())
        self.assertEqual(development.prepare(self.root, self.item, self.project), self.item["development"])


if __name__ == "__main__":
    unittest.main()
