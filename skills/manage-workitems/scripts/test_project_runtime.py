"""Run with PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_project_runtime."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import project_runtime as runtime
from workitem_ids import ALPHABET


def git(directory, *args):
    result = subprocess.run(["git", "-C", str(directory), *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode().strip()


def text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def item(identifier):
    return {"id": identifier, "title": identifier, "kind": "development", "status": "new",
            "archived": False, "depends_on": [], "split_from": None, "repository": "code",
            "development": None,
            "delivery": {"required": ["merged"], "status": "pending", "evidence": []},
            "cleanup": "not_applicable"}


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="project-runtime-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.remote = self.directory / "remote.git"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "--initial-branch=main", "--quiet")
        git(self.remote, "config", "core.hooksPath", str(self.remote / "hooks"))
        self.a = self.directory / "a"
        self.a.mkdir()
        git(self.a, "init", "--initial-branch=main", "--quiet")
        self.configure(self.a)
        git(self.a, "remote", "add", "origin", str(self.remote))
        self.project = {"schema_version": 1, "id": "project-demo", "name": "测试项目",
                        "storage": {"remote": "origin", "branch": "main", "url": str(self.remote)},
                        "backends": {"aone": None},
                        "repositories": [{"id": "code", "url": "https://example.invalid/code.git",
                                          "base_ref": "main"}]}
        self.write(self.a, ".project/project.json", text(self.project))
        self.write(self.a, ".gitignore", "/worktrees/\n/.project-local/\n")
        self.write(self.a, "AGENTS.md", "Manage this project.\n")
        for identifier in ("A", "B"):
            self.write(self.a, f"workitems/{identifier}/item.json", text(item(identifier)))
        git(self.a, "add", ".")
        git(self.a, "commit", "--quiet", "-m", "initial")
        git(self.a, "push", "--quiet", "-u", "origin", "main")
        self.b = self.directory / "b"
        git(self.directory, "clone", "--quiet", str(self.remote), str(self.b))
        self.configure(self.b)
        self.base = git(self.a, "rev-parse", "HEAD")

    def configure(self, root):
        git(root, "config", "user.name", "Runtime Test")
        git(root, "config", "user.email", "runtime@example.invalid")
        git(root, "config", "core.hooksPath", str(root / ".git/hooks"))

    def write(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def bundle(self, root, identifier, change, session="test", token=None, extra=None):
        name = f"workitems/{identifier}/item.json"
        old_bytes = (root / name).read_bytes()
        updated = json.loads(old_bytes)
        updated.update(change)
        bundle = {"checks": {name: hashlib.sha256(old_bytes).hexdigest()},
                  "writes": {name: text(updated)}, "message": f"update {identifier}",
                  "session": session, "token": token}
        if extra:
            for path, content in extra.items():
                bundle["checks"][path] = hashlib.sha256((root / path).read_bytes()).hexdigest() if (root / path).exists() else None
                bundle["writes"][path] = content
        return bundle

    def publish(self, root, bundle):
        # The caller's bundle can live outside the workspace; retained journals are ignored.
        path = self.directory / "bundle.json"
        path.write_text(text(bundle), encoding="utf-8")
        return runtime.publish(root, path)

    def remote_head(self):
        return git(self.remote, "rev-parse", "refs/heads/main")

    def add_item(self, root, identifier, **changes):
        record = item(identifier)
        record.update(changes)
        self.write(root, f"workitems/{identifier}/item.json", text(record))
        return record

    def new_item_bundle(self, identifier):
        name = f"workitems/{identifier}/item.json"
        return {"checks": {name: None}, "writes": {name: text(item(identifier))},
                "message": "new item", "session": "test", "token": None}

    def test_hierarchical_allocation_uses_all_metadata_and_never_reserves(self):
        self.assertEqual(runtime.new_ids(self.a, ["quota-lock", "pool-binding"]),
                         ["1-quota-lock", "2-pool-binding"])
        self.add_item(self.a, "1-quota-lock", title="配额锁")
        for character in ALPHABET[:9]:
            self.add_item(self.a, f"1{character}-child", split_from="1-quota-lock",
                          archived=True, status="cancelled")
        self.assertEqual(runtime.new_ids(self.a, ["shared-quota", "other"], "1-quota-lock"),
                         ["1A-shared-quota", "1B-other"])
        self.add_item(self.a, "1A-shared-quota", split_from="1-quota-lock")
        self.assertEqual(runtime.new_ids(self.a, ["worker"], "1A-shared-quota"), ["1A1-worker"])
        self.assertEqual(runtime.new_ids(self.a, ["next"]), ["2-next"])
        self.assertEqual(runtime.new_ids(self.a, ["next"]), ["2-next"])
        self.assertFalse((self.a / ".project-local").exists())

    def test_new_ids_reject_invalid_parent_slug_and_exhaustion_atomically(self):
        for parent in ("missing", "1", "A"):
            with self.subTest(parent=parent), self.assertRaises(runtime.ProjectError):
                runtime.new_ids(self.a, ["child"], parent)
        with self.assertRaisesRegex(runtime.ProjectError, "explicitly migrate"):
            runtime.new_ids(self.a, ["child"], "A")
        for slug in ("Upper", "-bad", "a--b", "é", "a_thing", "1-first", "a" * 128):
            with self.subTest(slug=slug), self.assertRaises(runtime.ProjectError):
                runtime.new_ids(self.a, ["good", slug])
        for character in ALPHABET[:-1]:
            self.add_item(self.a, f"{character}-root")
        self.assertEqual(runtime.new_ids(self.a, ["last"]), ["Z-last"])
        with self.assertRaisesRegex(runtime.ProjectError, "35-item limit"):
            runtime.new_ids(self.a, ["last", "overflow"])
        self.add_item(self.a, "Z-root", archived=True, status="cancelled")
        with self.assertRaisesRegex(runtime.ProjectError, "35-item limit"):
            runtime.new_ids(self.a, ["overflow"])

    def test_new_id_cli_reads_metadata_only_and_emits_no_partial_batch(self):
        script = Path(runtime.__file__).resolve()
        self.add_item(self.a, "1-root")
        (self.a / "workitems/1-root/requirement.md").write_bytes(b"\xffnot UTF-8")
        result = subprocess.run([sys.executable, str(script), "--root", str(self.a),
                                 "new-id", "child", "sibling", "--parent", "1-root"],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "11-child\n12-sibling\n")
        self.assertFalse((self.a / ".project-local").exists())
        result = subprocess.run([sys.executable, str(script), "--root", str(self.a),
                                 "new-id", "valid", "BAD"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("invalid slug", result.stderr)

    def test_new_ids_reject_unsafe_metadata_without_reading_link_targets(self):
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "item.json").write_text(text(item("1-outside")))
        (self.a / "workitems/1-outside").symlink_to(outside, target_is_directory=True)
        with mock.patch.object(runtime, "read_json", wraps=runtime.read_json) as reader:
            with self.assertRaisesRegex(runtime.ProjectError, "symlink"):
                runtime.new_ids(self.a, ["safe"])
        self.assertFalse(any(call.args[0].parent.name == "1-outside" for call in reader.call_args_list))

    def test_hierarchy_parent_and_dependency_dag_are_independent(self):
        self.add_item(self.a, "1-parent", kind="aggregate", repository=None,
                      depends_on=["11-child"])
        self.add_item(self.a, "11-child", split_from="1-parent")
        self.add_item(self.a, "111-grandchild", split_from="11-child", depends_on=["A"])
        self.assertEqual(runtime.validate_project(self.a), [])
        self.add_item(self.a, "111-grandchild", split_from="1-parent")
        self.assertTrue(any("split_from must be full hierarchy parent id 11-child" in error
                            for error in runtime.validate_project(self.a)))
        self.add_item(self.a, "111-grandchild", split_from="11-child", depends_on=["111"])
        self.assertTrue(any("dangling dependency 111" in error for error in runtime.validate_project(self.a)))
        self.add_item(self.a, "1-parent", split_from="A")
        self.add_item(self.a, "21-orphan", split_from="1-parent")
        self.add_item(self.a, "11-duplicate", split_from="1-parent", archived=True)
        errors = runtime.validate_project(self.a)
        for expected in ("hierarchy root split_from must be null", "missing hierarchy parent code 2", "duplicate hierarchy code 11"):
            self.assertTrue(any(expected in error for error in errors), errors)

    def test_stale_code_collision_rejects_publish_then_refresh_reallocates(self):
        first_id = runtime.new_ids(self.a, ["first"])[0]
        stale_id = runtime.new_ids(self.b, ["second"])[0]
        first = self.publish(self.a, self.new_item_bundle(first_id))
        stale_bundle = self.new_item_bundle(stale_id)
        with self.assertRaisesRegex(runtime.ProjectError, "duplicate hierarchy code 1"):
            self.publish(self.b, stale_bundle)
        self.assertEqual(self.remote_head(), first["commit"])
        self.assertEqual(git(self.b, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.b, "status", "--porcelain"), "")
        self.assertFalse((self.b / f"workitems/{stale_id}").exists())
        self.assertEqual(stale_bundle, self.new_item_bundle(stale_id))
        git(self.b, "fetch", "origin", "main")
        git(self.b, "merge", "--ff-only", "origin/main")
        fresh_id = runtime.new_ids(self.b, ["second"])[0]
        self.assertEqual(fresh_id, "2-second")
        second = self.publish(self.b, self.new_item_bundle(fresh_id))
        self.assertEqual(self.remote_head(), second["commit"])
        self.assertTrue((self.b / f"workitems/{first_id}/item.json").exists())
        self.assertTrue((self.b / f"workitems/{fresh_id}/item.json").exists())
        self.assertEqual(runtime.validate_project(self.b), [])

    def test_disjoint_stale_clones_publish_merged_tree(self):
        a_bundle = self.bundle(self.a, "A", {"title": "A updated"})
        b_bundle = self.bundle(self.b, "B", {"title": "B updated"})
        first = self.publish(self.a, a_bundle)
        second = self.publish(self.b, b_bundle)
        self.assertNotEqual(first["commit"], second["commit"])
        self.assertEqual(self.remote_head(), second["commit"])
        self.assertEqual(runtime.read_json(self.b / "workitems/A/item.json")["title"], "A updated")
        self.assertEqual(runtime.read_json(self.b / "workitems/B/item.json")["title"], "B updated")
        self.assertEqual(git(self.b, "status", "--porcelain"), "")
        self.assertEqual(runtime.validate_project(self.b), [])
        self.assertEqual(runtime.read_json(Path(second["journal"]))["state"], "published")


    def test_merged_dependency_cycle_stops_before_push(self):
        first = self.bundle(self.a, "A", {"depends_on": ["B"]})
        second = self.bundle(self.b, "B", {"depends_on": ["A"]})
        published = self.publish(self.a, first)["commit"]
        with self.assertRaisesRegex(runtime.ProjectError, "dependency cycle"):
            self.publish(self.b, second)
        self.assertEqual(self.remote_head(), published)
        self.assertEqual(git(self.b, "rev-parse", "HEAD"), self.base)

    def test_dirty_and_in_progress_roots_are_not_modified(self):
        bundle = self.bundle(self.a, "A", {"title": "changed"})
        before = (self.a / "AGENTS.md").read_bytes()
        self.write(self.a, "AGENTS.md", "user staged changes\n")
        git(self.a, "add", "AGENTS.md")
        staged = git(self.a, "diff", "--cached")
        with self.assertRaisesRegex(runtime.ProjectError, "root is dirty"):
            self.publish(self.a, bundle)
        self.assertEqual(git(self.a, "diff", "--cached"), staged)
        self.assertEqual(self.remote_head(), self.base)
        self.assertFalse((self.a / ".project-local").exists())
        self.write(self.a, "AGENTS.md", before.decode())
        git(self.a, "add", "AGENTS.md")
        operation = self.a / ".git/rebase-merge"
        operation.mkdir()
        with self.assertRaisesRegex(runtime.ProjectError, "unfinished Git operation"):
            self.publish(self.a, bundle)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)

    def test_publish_rejects_unapproved_paths_links_and_missing_item_check(self):
        good = self.bundle(self.a, "A", {"title": "changed"})
        for path in ("../escape.md", "/tmp/escape.md", ".git/config", ".project-local/x.json",
                     "worktrees/code/AGENTS.md", "README.md", "evidence/private.key", "workitems/A/../B/item.json"):
            bundle = copy.deepcopy(good)
            bundle["checks"][path] = None
            bundle["writes"][path] = "dangerous"
            with self.subTest(path=path), self.assertRaises(runtime.ProjectError):
                self.publish(self.a, bundle)
        missing_check = {"checks": {"workitems/A/spec.md": None},
                         "writes": {"workitems/A/spec.md": "spec\n"},
                         "message": "spec", "session": "a", "token": None}
        with self.assertRaisesRegex(runtime.ProjectError, "must check"):
            self.publish(self.a, missing_check)
        (self.a / "workitems/A/spec.md").symlink_to(self.directory / "outside")
        self.assertTrue(any("symlink" in error for error in runtime.validate_project(self.a)))
        with self.assertRaises(runtime.ProjectError):
            self.publish(self.a, good)
        self.assertEqual(self.remote_head(), self.base)

    def test_failed_push_retains_bundle_candidate_and_clean_root(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\necho publication-rejected >&2\nexit 1\n")
        hook.chmod(0o755)
        bundle = self.bundle(self.a, "A", {"title": "candidate"})
        with self.assertRaisesRegex(runtime.ProjectError, "publication-rejected"):
            self.publish(self.a, bundle)
        journals = list((self.a / ".project-local/publish").glob("*/journal.json"))
        self.assertEqual(len(journals), 1)
        state = runtime.read_json(journals[0])
        self.assertEqual(state["state"], "failed")
        self.assertEqual(git(self.a, "cat-file", "-t", state["candidate"]), "commit")
        self.assertEqual(runtime.read_json(Path(state["bundle"])), bundle)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertEqual(self.remote_head(), self.base)

    def test_pre_push_rejections_are_retained_without_becoming_recovery_candidates(self):
        bundle = self.bundle(self.a, "A", {"title": "unsubmitted intent"})
        bundle["checks"]["workitems/A/item.json"] = "0" * 64
        for _ in range(3):
            with self.assertRaisesRegex(runtime.ProjectError, "byte check conflict"):
                self.publish(self.a, bundle)
        journals = sorted((self.a / ".project-local/publish").glob("*/journal.json"))
        retained = {path: path.read_bytes() for path in journals}
        self.assertEqual(len(journals), 3)
        self.assertTrue(all(runtime.publication_disposition(runtime.read_json(path)) == "rejected_before_push"
                            for path in journals))
        self.assertEqual(runtime.resume_publication(self.a)["code"], "publication_none_pending")
        result = runtime.resume_publication(self.a, journal=journals[0])
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["code"], "publication_rejected_before_push")
        self.assertEqual({path: path.read_bytes() for path in journals}, retained)
        self.assertEqual(self.remote_head(), self.base)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)

    def test_successful_push_with_server_ref_rollback_is_not_publication_success(self):
        hook = self.remote / "hooks/post-receive"
        hook.write_text('#!/bin/sh\nwhile read old new ref; do git update-ref "$ref" "$old" "$new"; done\nexit 0\n')
        hook.chmod(0o755)
        owner = {"machine": "m", "session": "test", "token": "t"}
        with self.assertRaisesRegex(runtime.ProjectError, "candidate is not contained"):
            self.publish(self.a, self.bundle(self.a, "A", {"owner": owner}, token="t"))
        self.assertEqual(self.remote_head(), self.base)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)
        self.assertNotIn("owner", runtime.read_json(self.a / 'workitems/A/item.json'))
        journal = next((self.a / ".project-local/publish").glob("*/journal.json"))
        state = runtime.read_json(journal)
        self.assertEqual(state["state"], "remote_verification_failed")
        self.assertEqual(git(self.a, "cat-file", "-t", state["candidate"]), "commit")

    def test_remote_can_advance_with_candidate_and_intended_state_unchanged(self):
        git(self.remote, "config", "user.name", "Server Test")
        git(self.remote, "config", "user.email", "server@example.invalid")
        hook = self.remote / "hooks/post-receive"
        hook.write_text('#!/bin/sh\nwhile read old new ref; do\n'
                        'tree=$(git rev-parse "$new^{tree}")\n'
                        'child=$(printf "server follow-up\\n" | git commit-tree "$tree" -p "$new")\n'
                        'git update-ref "$ref" "$child" "$new"\ndone\n')
        hook.chmod(0o755)
        published = self.publish(self.a, self.bundle(self.a, "A", {"title": "intended"}))
        self.assertNotEqual(published["commit"], published["verified_remote_commit"])
        self.assertEqual(published["verified_remote_commit"], self.remote_head())
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.remote_head())
        self.assertEqual(git(self.remote, "rev-parse", "HEAD^"), published["commit"])

    def test_post_receive_owner_change_invalidates_nonwrite_item_guard(self):
        owner = {"machine": "m", "session": "test", "token": "t"}
        self.publish(self.a, self.bundle(self.a, "A", {"owner": owner}, token="t"))
        original = self.remote_head()
        git(self.remote, "config", "user.name", "Server Test")
        git(self.remote, "config", "user.email", "server@example.invalid")
        hook = self.remote / "hooks/post-receive"
        hook.write_text(f"#!{sys.executable}\n" + '''import json, os, subprocess, sys, tempfile
def git(*args, data=None, env=None):
    return subprocess.run(["git", *args], input=data, env=env, check=True,
                          stdout=subprocess.PIPE).stdout.strip().decode()
for line in sys.stdin:
    old, new, ref = line.split()
    metadata = json.loads(git("show", new + ":workitems/A/item.json"))
    metadata["owner"] = None
    with tempfile.TemporaryDirectory() as directory:
        env = {**os.environ, "GIT_INDEX_FILE": directory + "/index"}
        git("read-tree", new, env=env)
        blob = git("hash-object", "-w", "--stdin", data=json.dumps(metadata).encode())
        git("update-index", "--add", "--cacheinfo", "100644", blob, "workitems/A/item.json", env=env)
        tree = git("write-tree", env=env)
    child = git("commit-tree", tree, "-p", new, data=b"owner released by server\\n")
    git("update-ref", ref, child, new)
''')
        hook.chmod(0o755)
        metadata = "workitems/A/item.json"
        bundle = {"checks": {metadata: hashlib.sha256((self.a / metadata).read_bytes()).hexdigest(),
                              "workitems/A/spec.md": None},
                  "writes": {"workitems/A/spec.md": "intended spec\n"},
                  "message": "spec", "session": "test", "token": "t"}
        with self.assertRaisesRegex(runtime.ProjectError, "guard state changed"):
            self.publish(self.a, bundle)
        self.assertNotEqual(self.remote_head(), original)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), original)
        self.assertFalse((self.a / "workitems/A/spec.md").exists())

    def test_byte_checks_do_not_accept_semantically_equal_json(self):
        bundle = self.bundle(self.b, "A", {"title": "changed"})
        self.publish(self.a, self.bundle(self.a, "A", {}, extra={"workitems/A/item.json": json.dumps(item("A"))}))
        with self.assertRaisesRegex(runtime.ProjectError, "byte check conflict"):
            self.publish(self.b, bundle)

    def test_find_project_stops_at_nested_git_and_local_boundaries(self):
        self.assertEqual(runtime.find_project(self.a / "workitems/A"), self.a)
        code = self.a / "worktrees/code"
        code.mkdir(parents=True)
        git(code, "init", "--quiet")
        with self.assertRaises(runtime.ProjectError):
            runtime.find_project(code)
        local = self.a / ".project-local"
        local.mkdir()
        with self.assertRaises(runtime.ProjectError):
            runtime.find_project(local)
        self.assertEqual(runtime.validate_project(self.a), [])
        alias = self.directory / "project-alias"
        alias.symlink_to(self.a)
        with self.assertRaisesRegex(runtime.ProjectError, "symlink"):
            runtime.find_project(alias / "workitems/A")
        internal = self.a / "workitems/alias"
        internal.symlink_to(self.a / "workitems/A")
        with self.assertRaisesRegex(runtime.ProjectError, "symlink"):
            runtime.find_project(internal)

    def test_validation_rejects_invalid_schema_tracked_code_and_missing_ignore(self):
        malformed = item("A")
        malformed.update(id="wrong", status=[], depends_on=["missing"], repository=["code"])
        self.write(self.a, "workitems/A/item.json", text(malformed))
        errors = runtime.validate_project(self.a)
        self.assertTrue(any("id must match" in error for error in errors))
        self.assertTrue(any("dangling" in error for error in errors))
        self.assertTrue(any("invalid status" in error for error in errors))
        self.write(self.a, ".gitignore", "/.project-local/\n")
        self.assertTrue(any("ignore worktrees" in error for error in runtime.validate_project(self.a)))
        self.write(self.a, "code.py", "print('not project data')\n")
        git(self.a, "add", "code.py")
        git(self.a, "commit", "--quiet", "-m", "forbidden code")
        self.assertTrue(any("not an approved" in error for error in runtime.validate_project(self.a)))

    def test_done_evidence_and_aggregate_dependencies_cleanup_independent(self):
        done = item("A")
        done.update(status="done", cleanup="pending",
                    delivery={"required": ["merged"], "status": "delivered",
                              "evidence": [{"kind": "merged", "reference": "https://example.invalid/pr/1"}]})
        self.write(self.a, "workitems/A/item.json", text(done))
        aggregate = item("B")
        aggregate.update(kind="aggregate", status="done", repository=None, depends_on=["A"],
                         delivery={"required": ["dependencies"], "status": "delivered",
                                   "evidence": [{"kind": "dependencies", "reference": "workitems/A/item.json"}]})
        self.write(self.a, "workitems/B/item.json", text(aggregate))
        self.assertEqual(runtime.validate_project(self.a), [])
        done["status"] = "cancelled"
        self.write(self.a, "workitems/A/item.json", text(done))
        self.assertTrue(any("non-cancelled dependency" in error for error in runtime.validate_project(self.a)))

    def test_required_delivery_kinds_cannot_be_empty_or_unsubstantiated(self):
        malformed = item("A")
        malformed.update(status="done", delivery={"required": [], "status": "delivered", "evidence": []})
        self.write(self.a, "workitems/A/item.json", text(malformed))
        self.assertTrue(any("nonempty list" in error for error in runtime.validate_project(self.a)))
        malformed.update(status="awaiting_delivery", delivery={"required": ["merged"], "status": "delivered", "evidence": []})
        self.write(self.a, "workitems/A/item.json", text(malformed))
        self.assertTrue(any("delivered requires evidence" in error for error in runtime.validate_project(self.a)))

    def test_development_paths_are_portable_normalized_and_relative(self):
        development = {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": self.base}
        for path in (str(self.a / "worktrees/A"), "worktrees/../A", "worktrees//A", "worktrees/./A", "worktrees\\A"):
            changed = item("A")
            changed["development"] = {**development, "worktree": path}
            self.write(self.a, "workitems/A/item.json", text(changed))
            with self.subTest(path=path):
                self.assertTrue(any("normalized relative" in error for error in runtime.validate_project(self.a)))
        self.write(self.a, "workitems/A/item.json", text(item("A")))
        self.publish(self.a, self.bundle(self.a, "A", {"development": development}))
        git(self.b, "pull", "--ff-only", "--quiet")
        self.assertEqual(runtime.validate_project(self.b), [])
        self.publish(self.b, self.bundle(self.b, "B", {"title": "portable"}))

    def test_digest_ignores_owner_formatting_and_receipts_but_tracks_business(self):
        original = runtime.item_digest(self.a, "A")
        metadata = runtime.read_json(self.a / "workitems/A/item.json")
        metadata["owner"] = {"machine": "m", "session": "s", "token": "t"}
        self.write(self.a, "workitems/A/item.json", json.dumps(metadata, sort_keys=True))
        self.write(self.a, ".project/sync/A.json", text({"state": "unknown"}))
        self.assertEqual(runtime.item_digest(self.a, "A"), original)
        self.write(self.a, "workitems/A/spec.md", "业务内容\n")
        expected = hashlib.sha256()
        metadata.pop("owner")
        normalized = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        for name, content in (("workitems/A/item.json", normalized), ("workitems/A/spec.md", "业务内容\n".encode())):
            expected.update(name.encode() + b"\x00" + content + b"\x00")
        self.assertEqual(runtime.item_digest(self.a, "A"), expected.hexdigest())
        self.assertNotEqual(expected.hexdigest(), original)

    def test_evidence_metadata_and_json_are_strict(self):
        card = {"id": "ev1", "repository": "code", "topic": "flow", "summary": "fact",
                "kind": "verification", "sources": [{"path": "src/example.py", "revision": self.base}],
                "scope": "single repository", "inputs": {}, "body": "evidence/ev1.md"}
        self.write(self.a, "evidence/ev1.json", text(card))
        self.write(self.a, "evidence/ev1.md", "Recorded evidence\n")
        self.assertEqual(runtime.validate_project(self.a), [])
        self.write(self.a, "evidence/ev1.json", '{"id":"ev1", "id":"ev2"}')
        self.assertTrue(any("duplicate JSON key" in error for error in runtime.validate_project(self.a)))

    def test_sync_receipt_requires_record_guards_and_business_digest(self):
        owner = {"machine": "m", "session": "a", "token": "t"}
        receipt_path = ".project/sync/A.json"
        receipt = {"intent_id": "intent-1", "content_sha256": runtime.item_digest(self.a, "A"),
                   "state": "verified", "external_id": "aone-1", "baseline_fields": {"title": "A"},
                   "git_source_commit": self.base, "checked_at": "2026-10-14T00:00:00Z"}
        self.publish(self.a, self.bundle(self.a, "A", {"owner": owner}, "a", "t", extra={receipt_path: text(receipt)}))
        self.assertEqual(runtime.validate_project(self.a), [])
        receipt["checked_at"] = "2026-10-15T00:00:00Z"
        self.publish(self.a, self.bundle(self.a, "A", {}, "later-session", extra={receipt_path: text(receipt)}))
        wrong = self.bundle(self.a, "A", {}, "other", extra={receipt_path: text({**receipt, "state": "unknown"})})
        wrong["checks"].pop("workitems/A/item.json")
        wrong["writes"].pop("workitems/A/item.json")
        with self.assertRaisesRegex(runtime.ProjectError, "must check"):
            self.publish(self.a, wrong)
        with self.assertRaisesRegex(runtime.ProjectError, "current item business digest"):
            self.publish(self.a, self.bundle(self.a, "A", {"title": "new business"}, "a", "t"))
        pending = {**receipt, "content_sha256": "0" * 64, "state": "pending",
                   "external_id": None, "baseline_fields": None, "git_source_commit": None, "checked_at": None}
        self.publish(self.a, self.bundle(self.a, "A", {"title": "new business"}, "a", "t",
                                         extra={receipt_path: text(pending)}))
        receipt["content_sha256"] = runtime.item_digest(self.a, "A")
        self.publish(self.a, self.bundle(self.a, "A", {"owner": None}, "a", "t", extra={receipt_path: text(receipt)}))
        self.assertEqual(runtime.validate_project(self.a), [])

    def test_receipt_schema_is_data_validation_without_aone_calls(self):
        self.write(self.a, ".project/sync/missing.json", text({"intent_id": "x", "content_sha256": "bad",
                                                              "state": "verified"}))
        errors = runtime.validate_project(self.a)
        self.assertTrue(any("existing workitem" in error for error in errors))
        self.assertTrue(any("SHA256 digest" in error for error in errors))
        self.assertTrue(any("nonempty baseline_fields" in error for error in errors))

    def test_validation_can_run_before_initial_commit(self):
        fresh = self.directory / "fresh"
        fresh.mkdir()
        git(fresh, "init", "--quiet")
        self.write(fresh, ".project/project.json", text(self.project))
        self.write(fresh, ".gitignore", "/worktrees/\n/.project-local/\n")
        git(fresh, "add", ".")
        self.assertEqual(runtime.validate_project(fresh), [])

    def test_ignore_rules_must_cover_local_directories_not_one_probe_file(self):
        self.write(self.a, ".gitignore", "/worktrees/probe\n/.project-local/probe\n")
        errors = runtime.validate_project(self.a)
        self.assertTrue(any("must ignore worktrees/" in error for error in errors))
        self.assertTrue(any("must ignore .project-local/" in error for error in errors))

    def use_main_workspace(self, repository=None):
        main = self.directory / "main-workspace"
        main.mkdir(exist_ok=True)
        self.write(main, "AGENTS.md", "Main workspace instructions.\n")
        project = copy.deepcopy(self.project)
        project["main_workspace"] = {"id": "workspace-demo", "name": "主工作区", "repository": repository}
        project["worktrees"] = {"base": "main_workspace", "path": "worktrees/project-demo"}
        self.write(self.a, ".project/project.json", text(project))
        self.write(self.a, ".project/main-workspace.md", "Main workspace context and repository routes.\n")
        updated = item("A")
        updated["development"] = {"worktree": "worktrees/project-demo/A", "branch": "feature/A", "base_commit": self.base}
        self.write(self.a, "workitems/A/item.json", text(updated))
        return main, project

    def bind_main(self, root, main, identifier="workspace-demo"):
        self.write(root, ".project-local/main-workspace.json", text({"id": identifier, "root": str(main)}))

    def test_placeholder_clone_preserves_directory_and_publish_excludes_code(self):
        self.write(self.a, ".gitignore", "/worktrees/*\n!/worktrees/.gitkeep\n/.project-local/\n")
        self.write(self.a, "worktrees/.gitkeep", "")
        self.write(self.a, "worktrees/code/nested/example.py", "source\n")
        self.write(self.a, "worktrees/.hidden-code/example.py", "hidden source\n")
        git(self.a, "add", ".")
        tracked = git(self.a, "ls-files").splitlines()
        self.assertEqual([name for name in tracked if name.startswith("worktrees/")], ["worktrees/.gitkeep"])
        git(self.a, "commit", "--quiet", "-m", "portable placeholder")
        git(self.a, "push", "--quiet", "origin", "main")
        relocated = self.directory / "fresh-location"
        git(self.directory, "clone", "--quiet", str(self.remote), str(relocated))
        self.configure(relocated)
        self.assertTrue((relocated / "worktrees").is_dir())
        self.assertEqual((relocated / "worktrees/.gitkeep").read_bytes(), b"")
        self.assertEqual(runtime.validate_project(relocated), [])
        self.assertEqual(runtime.worktree_root(relocated), relocated / "worktrees")
        self.publish(self.a, self.bundle(self.a, "A", {"title": "published with ignored code"}))
        remote_paths = git(self.remote, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        self.assertEqual([name for name in remote_paths if name.startswith("worktrees/")], ["worktrees/.gitkeep"])
        self.assertEqual(runtime.validate_project(self.a), [])
        with self.assertRaisesRegex(runtime.ProjectError, "zero-byte"):
            self.publish(self.a, self.bundle(self.a, "A", {}, extra={"worktrees/.gitkeep": "code"}))
        for name in ("worktrees/code/example.py", "worktrees/other/.gitkeep"):
            with self.subTest(name=name), self.assertRaises(runtime.ProjectError):
                runtime._managed_path(name)

    def test_new_ignore_rules_cannot_reopen_code_directories_or_hide_marker(self):
        self.write(self.a, "worktrees/.gitkeep", "")
        for suffix in ("!/worktrees/leaked/\n", "!/worktrees/*/\n", "!leaked\n", "!/worktrees/.gitkeep/\n"):
            self.write(self.a, ".gitignore", "/worktrees/*\n!/worktrees/.gitkeep\n/.project-local/\n" + suffix)
            with self.subTest(suffix=suffix):
                self.assertTrue(any("recursively" in error for error in runtime.validate_project(self.a)))
        self.write(self.a, ".gitignore", "/worktrees/\n/.project-local/\n")
        self.assertTrue(any("must not ignore" in error for error in runtime.validate_project(self.a)))

    def test_main_layout_publishes_and_validates_without_local_binding(self):
        main, project = self.use_main_workspace()
        self.assertEqual(runtime.validate_project(self.a), [])
        for resolver in (lambda: runtime.worktree_root(self.a), lambda: runtime.worktree_path(self.a, "A")):
            with self.assertRaisesRegex(runtime.ProjectError, "not bound"):
                resolver()
        # Pure metadata publication must not consult a stale machine-local file.
        self.write(self.a, ".project-local/main-workspace.json", "not JSON")
        git(self.a, "add", ".project/project.json", "workitems/A/item.json")
        git(self.a, "add", ".project/main-workspace.md")
        git(self.a, "commit", "--quiet", "-m", "external portable layout")
        git(self.a, "push", "--quiet", "origin", "main")
        self.publish(self.a, self.bundle(self.a, "B", {"title": "metadata only"},
                                        extra={".project/main-workspace.md": "Main workspace context.\n"}))
        clone = self.directory / "relocated-project"
        git(self.directory, "clone", "--quiet", str(self.remote), str(clone))
        self.assertEqual(runtime.validate_project(clone), [])
        self.assertFalse((clone / ".project-local").exists())
        self.bind_main(clone, main)
        self.assertEqual(runtime.worktree_root(clone), main / "worktrees/project-demo")
        self.assertEqual(runtime.worktree_path(clone, "A"), main / "worktrees/project-demo/A")
        self.assertFalse((main / "worktrees").exists())

    def test_binding_rejects_wrong_identity_invalid_root_and_symlinks(self):
        main, _ = self.use_main_workspace()
        self.bind_main(self.a, main)
        self.assertEqual(runtime.worktree_path(self.a, "A"), main / "worktrees/project-demo/A")
        self.bind_main(self.a, main, "wrong-id")
        with self.assertRaisesRegex(runtime.ProjectError, "id does not match"):
            runtime.worktree_root(self.a)
        for bad in ("relative", str(self.directory / "missing"), str(self.a), str(self.a / "workitems")):
            self.bind_main(self.a, bad)
            with self.subTest(root=bad), self.assertRaises(runtime.ProjectError):
                runtime.worktree_root(self.a)
        self.bind_main(self.a, main)
        (main / "AGENTS.md").unlink()
        (main / "AGENTS.md").symlink_to(self.a / "AGENTS.md")
        with self.assertRaisesRegex(runtime.ProjectError, "regular AGENTS"):
            runtime.worktree_root(self.a)
        (main / "AGENTS.md").unlink()
        self.write(main, "AGENTS.md", "Main instructions.\n")
        (main / "worktrees").symlink_to(self.directory)
        self.assertEqual(runtime.validate_project(self.a), [])
        with self.assertRaisesRegex(runtime.ProjectError, "symlinks"):
            runtime.worktree_root(self.a)
        (main / "worktrees").unlink()
        alias = self.directory / "main-alias"
        alias.symlink_to(main)
        self.bind_main(self.a, alias)
        with self.assertRaisesRegex(runtime.ProjectError, "symlinks"):
            runtime.worktree_path(self.a, "A")
        self.bind_main(self.a, main)
        binding = self.a / ".project-local/main-workspace.json"
        binding.unlink()
        binding.symlink_to(self.directory / "binding.json")
        with self.assertRaisesRegex(runtime.ProjectError, "symlink"):
            runtime.worktree_root(self.a)

    def test_main_repository_checks_effective_remote_url_without_fetch(self):
        expected = "https://example.invalid/main.git"
        main, _ = self.use_main_workspace({"url": expected, "ref": "refs/heads/main"})
        self.bind_main(self.a, main)
        git(main, "init", "--quiet")
        git(main, "remote", "add", "origin", "https://example.invalid/wrong.git")
        with self.assertRaisesRegex(runtime.ProjectError, "effective remote URL"):
            runtime.worktree_root(self.a)
        git(main, "remote", "add", "matching", "workspace:main.git")
        git(main, "config", "url.https://example.invalid/.insteadOf", "workspace:")
        self.assertEqual(runtime.worktree_root(self.a), main / "worktrees/project-demo")
        self.assertEqual(git(main, "for-each-ref"), "")
        self.assertFalse((main / ".git/FETCH_HEAD").exists())

    def test_layout_paths_and_refs_enforce_portable_scope(self):
        _, project = self.use_main_workspace()
        for layout in ({"base": "main_workspace", "path": "worktrees"},
                       {"base": "other", "path": "worktrees/demo"},
                       {"base": "project", "path": "worktrees/../escape"},
                       {"base": "project", "path": "worktrees//demo"},
                       {"base": "project", "path": "/worktrees/demo"}):
            self.write(self.a, ".project/project.json", text({**project, "worktrees": layout}))
            with self.subTest(layout=layout):
                self.assertTrue(runtime.validate_project(self.a))
        for container in (".worktrees/project-demo", "dev/trees/project-demo"):
            custom = {**project, "worktrees": {"base": "main_workspace", "path": container}}
            changed = item("A")
            changed["development"] = {"worktree": container + "/A", "branch": "feature/A", "base_commit": self.base}
            self.write(self.a, ".project/project.json", text(custom))
            self.write(self.a, "workitems/A/item.json", text(changed))
            self.bind_main(self.a, self.directory / "main-workspace")
            with self.subTest(container=container):
                self.assertEqual(runtime.validate_project(self.a), [])
                self.assertEqual(runtime.worktree_path(self.a, "A"), self.directory / "main-workspace" / container / "A")
        self.write(self.a, ".project/project.json", text(project))
        for path in ("worktrees/project-demo", "worktrees/other/A", "worktrees/project-demo/../A", "worktrees/project-demo//A"):
            changed = item("A")
            changed["development"] = {"worktree": path, "branch": "feature/A", "base_commit": self.base}
            self.write(self.a, "workitems/A/item.json", text(changed))
            with self.subTest(path=path):
                self.assertTrue(any("normalized relative" in error for error in runtime.validate_project(self.a)))
                with self.assertRaisesRegex(runtime.ProjectError, "normalized relative"):
                    runtime.worktree_path(self.a, "A")
        for ref in ("main", "HEAD", "refs/heads/../escape"):
            changed = copy.deepcopy(project)
            changed["main_workspace"]["repository"] = {"url": "example", "ref": ref}
            self.write(self.a, ".project/project.json", text(changed))
            with self.subTest(ref=ref):
                self.assertTrue(any("full Git ref" in error for error in runtime.validate_project(self.a)))

    def test_nested_independent_project_resolves_outer_main_and_linked_root_stays_forbidden(self):
        outer = self.directory / "outer"
        outer.mkdir()
        git(outer, "init", "--initial-branch=main", "--quiet")
        self.configure(outer)
        self.write(outer, "AGENTS.md", "Outer main workspace.\n")
        git(outer, "add", ".")
        git(outer, "commit", "--quiet", "-m", "main workspace")
        nested = outer / "projects/demo"
        git(self.directory, "clone", "--quiet", str(self.remote), str(nested))
        project = {**self.project, "main_workspace": {"id": "workspace-demo", "name": "Outer", "repository": None},
                   "worktrees": {"base": "main_workspace", "path": "worktrees/project-demo"}}
        self.write(nested, ".project/project.json", text(project))
        self.write(nested, ".project/main-workspace.md", "Outer workspace routes.\n")
        self.bind_main(nested, outer)
        self.assertEqual(runtime.find_project(nested), nested)
        self.assertEqual(runtime.worktree_root(nested), outer / "worktrees/project-demo")
        escaped = {**project, "worktrees": {"base": "main_workspace", "path": "projects/demo"}}
        self.write(nested, ".project/project.json", text(escaped))
        with self.assertRaisesRegex(runtime.ProjectError, "management directory"):
            runtime.worktree_root(nested)
        linked = outer / "linked-project"
        git(outer, "worktree", "add", "--quiet", str(linked), "-b", "linked")
        self.write(linked, ".project/project.json", text(project))
        with self.assertRaisesRegex(runtime.ProjectError, "linked Git worktree"):
            runtime.find_project(linked)

    def test_worktree_cli_is_read_only_and_default_layout_relocates(self):
        changed = item("A")
        changed["development"] = {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": self.base}
        self.write(self.a, "workitems/A/item.json", text(changed))
        self.assertEqual(runtime.validate_project(self.a), [])
        script = Path(runtime.__file__)
        for command, expected in ((["worktree-root"], self.a / "worktrees"),
                                  (["worktree-path", "A"], self.a / "worktrees/A")):
            result = subprocess.run([sys.executable, str(script), "--root", str(self.a), *command],
                                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.stdout.decode().strip(), str(expected))
        self.assertFalse((self.a / "worktrees").exists())
        self.assertFalse((self.a / ".project-local").exists())
        self.write(self.a, "workitems/A/item.json", text(item("A")))
        self.publish(self.a, self.bundle(self.a, "A", {"development": changed["development"]}))
        git(self.b, "pull", "--ff-only", "--quiet")
        self.assertEqual(runtime.worktree_path(self.b, "A"), self.b / "worktrees/A")

    def test_remote_url_divergence_and_local_unpublished_commits_stop(self):
        bundle = self.bundle(self.a, "A", {"title": "changed"})
        git(self.a, "config", "remote.origin.pushurl", str(self.directory / "other.git"))
        with self.assertRaisesRegex(runtime.ProjectError, "URL/push URL differs"):
            self.publish(self.a, bundle)
        git(self.a, "config", "--unset", "remote.origin.pushurl")
        self.write(self.a, "AGENTS.md", "Unpublished local commit.\n")
        git(self.a, "add", "AGENTS.md")
        git(self.a, "commit", "--quiet", "-m", "local only")
        local_head = git(self.a, "rev-parse", "HEAD")
        with self.assertRaisesRegex(runtime.ProjectError, "unpublished/divergent"):
            self.publish(self.a, bundle)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), local_head)
        self.assertEqual(self.remote_head(), self.base)


class PublicationDispositionTest(unittest.TestCase):
    def test_any_candidate_or_later_push_evidence_keeps_failed_outcome_pending(self):
        self.assertEqual(runtime.publication_disposition({"state": "failed"}), "rejected_before_push")
        for evidence in ({"candidate": None}, {"candidate": "a" * 40},
                         {"verified_remote_commit": "a" * 40}, {"recovery_attempts": 0}):
            with self.subTest(evidence=evidence):
                self.assertEqual(runtime.publication_disposition({"state": "failed", **evidence}), "pending")
        self.assertEqual(runtime.publication_disposition({"state": "prepared"}), "pending")
        self.assertEqual(runtime.publication_disposition({"state": "published"}), "published")


if __name__ == "__main__":
    unittest.main()
