"""Run with PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_make_bundle."""

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import make_bundle
import project_runtime as runtime
import test_project_runtime as runtime_tests


def git(directory, *args):
    result = subprocess.run(["git", "-C", str(directory), *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode().strip()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


ITEM = "wi-test0001"


class MakeBundleTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="make-bundle-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        git(self.root, "init", "--initial-branch=main", "--quiet")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "test")
        self.item_path = f"workitems/{ITEM}/item.json"
        self.req_path = f"workitems/{ITEM}/requirement.md"
        self.sync_path = f".project/sync/{ITEM}.json"
        (self.root / f"workitems/{ITEM}").mkdir(parents=True)
        (self.root / ".project/sync").mkdir(parents=True)
        (self.root / self.item_path).write_text(json.dumps({"id": ITEM, "title": "old", "owner": None}) + "\n")
        (self.root / self.req_path).write_text("# requirement v1\n")
        (self.root / self.sync_path).write_text(json.dumps({"state": "verified"}) + "\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "--quiet", "-m", "base")

    def bundle(self, *args):
        out = self.root / "bundle.json"
        make_bundle.main(["--root", str(self.root), "--session", "s1", "--token", "t1",
                          "--message", "m", "--out", str(out), *args])
        return json.loads(out.read_text())

    def commit_sync(self, data):
        (self.root / self.sync_path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        git(self.root, "add", self.sync_path)
        git(self.root, "commit", "--quiet", "-m", "sync")

    def pending(self):
        data = {"intent_id": "aone-update-operation", "external_id": "123", "state": "pending",
                "operation": "update", "target_status": "待发布", "target_status_id": "100020",
                "baseline_fields": None, "git_source_commit": None, "checked_at": None,
                "content_sha256": make_bundle.Snapshot(self.root, git(self.root, "rev-parse", "HEAD")).digest(ITEM)}
        self.commit_sync(data)
        return data

    def readback(self, pending, **changes):
        data = {"intent_id": pending["intent_id"], "external_id": pending["external_id"],
                "git_source_commit": git(self.root, "rev-parse", "HEAD"),
                "content_sha256": pending["content_sha256"],
                "baseline_fields": {"title": "actual title", "body": "actual body", "status": "100020"},
                "checked_at": "2026-10-15T20:01:00+08:00", "space_id": "2007386"}
        data.update(changes)
        path = self.root / "readback.json"
        path.write_text(json.dumps(data, ensure_ascii=False))
        return f"{ITEM}:{path}", data

    def test_default_head_write_guard_and_new_path(self):
        old = (self.root / self.req_path).read_text()
        (self.root / self.req_path).write_text("new body")
        bundle = self.bundle("--write", self.req_path)
        self.assertEqual(bundle["checks"][self.req_path], sha256_text(old))
        self.assertEqual(bundle["writes"][self.req_path], "new body")
        fresh = f"workitems/{ITEM}/decisions.md"
        (self.root / fresh).write_text("decisions")
        self.assertIsNone(self.bundle("--new", fresh)["checks"][fresh])
        with self.assertRaises(SystemExit):
            self.bundle("--new", self.req_path)

    def test_intents_have_prospective_digest_unique_ids_and_retain_baseline(self):
        baseline = {"title": "previous readback", "body": "previous body"}
        self.commit_sync({"state": "verified", "baseline_fields": baseline, "space_id": "456"})
        (self.root / self.req_path).write_text("new body")
        first = self.bundle("--write", self.req_path, "--intent", f"{ITEM}:123:待发布:100020")
        second = self.bundle("--write", self.req_path, "--intent", f"{ITEM}:123:待发布:100020")
        a, b = (json.loads(bundle["writes"][self.sync_path]) for bundle in (first, second))
        self.assertNotEqual(a["intent_id"], b["intent_id"])
        self.assertEqual(a["baseline_fields"], baseline)
        self.assertEqual(a["space_id"], "456")
        self.assertEqual(a["content_sha256"], runtime._business_digest(
            {self.item_path: (self.root / self.item_path).read_bytes(), self.req_path: b"new body"}, ITEM))
        self.assertIn(self.item_path, first["checks"])
        with self.assertRaises(SystemExit):
            self.bundle("--intent", "wi-missing:123:待发布:100020")

    def test_receipt_uses_actual_readback_without_history_or_repeated_item_reads(self):
        pending = self.pending()
        spec, readback = self.readback(pending)
        with mock.patch.object(make_bundle, "_git", wraps=make_bundle._git) as commands, \
                mock.patch.object(runtime, "_business_digest", wraps=runtime._business_digest) as digests:
            bundle = self.bundle("--receipt", spec, "--assert-note", "all owned fields matched")
        self.assertEqual(digests.call_count, 1)
        receipt = json.loads(bundle["writes"][self.sync_path])
        self.assertEqual(receipt["intent_id"], pending["intent_id"])
        for key in ("external_id", "content_sha256", "baseline_fields", "checked_at", "git_source_commit", "space_id"):
            self.assertEqual(receipt[key], readback[key])
        self.assertEqual(receipt["state"], "verified")
        self.assertEqual(receipt["result"], "readback-verified")
        self.assertEqual(receipt["readback_assertions"], "all owned fields matched")
        self.assertIn(self.item_path, bundle["checks"])
        self.assertEqual(bundle["checks"][self.sync_path], sha256_text((self.root / self.sync_path).read_text()))
        self.assertFalse(any(call.args[1] == "log" for call in commands.call_args_list))
        trees = [call for call in commands.call_args_list if call.args[1] == "ls-tree"]
        self.assertEqual(len(trees), 2)
        self.assertTrue(all(call.args[-1] in {f"workitems/{ITEM}/", self.sync_path} for call in trees))

    def test_selected_base_is_resolved_once_before_reading_any_content(self):
        original_commit = git(self.root, "rev-parse", "HEAD")
        expected = make_bundle.Snapshot(self.root, original_commit).digest(ITEM)
        git(self.root, "branch", "selected", original_commit)
        (self.root / self.req_path).write_text("newer business version")
        git(self.root, "add", self.req_path)
        git(self.root, "commit", "--quiet", "-m", "newer")
        resolve = make_bundle._commit

        def move_ref_after_resolution(root, revision):
            commit = resolve(root, revision)
            git(root, "update-ref", "refs/heads/selected", "HEAD")
            return commit

        with mock.patch.object(make_bundle, "_commit", side_effect=move_ref_after_resolution) as resolver:
            bundle = self.bundle("--base", "selected", "--intent", f"{ITEM}:123:待发布:100020")
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(json.loads(bundle["writes"][self.sync_path])["content_sha256"], expected)

    def test_readback_accepts_utc_z_and_preserves_original_timestamp(self):
        spec, data = self.readback(self.pending(), checked_at="2026-10-15T20:01:00Z")
        bundle = self.bundle("--receipt", spec)
        self.assertEqual(json.loads(bundle["writes"][self.sync_path])["checked_at"], data["checked_at"])

    def test_receipt_rejects_unsynchronized_business_writes_before_emitting_bundle(self):
        pending = self.pending()
        spec, _ = self.readback(pending)
        for name, content in ((self.req_path, "unsynchronized body"),
                              (self.item_path, json.dumps({"id": ITEM, "title": "new title"}))):
            with self.subTest(name=name):
                original = (self.root / name).read_text()
                (self.root / name).write_text(content)
                with self.assertRaisesRegex(SystemExit, "prospective business digest"):
                    self.bundle("--write", name, "--receipt", spec)
                self.assertFalse((self.root / "bundle.json").exists())
                (self.root / name).write_text(original)

    def test_receipt_allows_owner_release_and_semantically_unchanged_json(self):
        item = json.loads((self.root / self.item_path).read_text())
        item["owner"] = {"session": "s1", "token": "t1"}
        (self.root / self.item_path).write_text(json.dumps(item))
        git(self.root, "add", self.item_path)
        git(self.root, "commit", "--quiet", "-m", "owned")
        pending = self.pending()
        spec, _ = self.readback(pending)
        item["owner"] = None
        (self.root / self.item_path).write_text(json.dumps(item, sort_keys=True, indent=4))
        bundle = self.bundle("--write", self.item_path, "--receipt", spec)
        self.assertEqual(json.loads(bundle["writes"][self.sync_path])["content_sha256"], pending["content_sha256"])

    def test_receipt_rejects_invalid_readback_and_identity(self):
        pending = self.pending()
        for changes in ({"baseline_fields": {}}, {"baseline_fields": None},
                        {"baseline_fields": {"status": "old-status"}},
                        {"checked_at": "2026-10-15T20:01:00"}, {"checked_at": "invalid"},
                        {"external_id": "another"}, {"intent_id": "another"},
                        {"content_sha256": "0" * 64}, {"git_source_commit": "f" * 40},
                        {"git_source_commit": "HEAD"}):
            with self.subTest(changes=changes):
                spec, _ = self.readback(pending, **changes)
                with self.assertRaises(SystemExit):
                    self.bundle("--receipt", spec, "--assert-note", "not a substitute for evidence")
                self.assertFalse((self.root / "bundle.json").exists())

    def test_receipt_rejects_stale_source_and_changed_pending_identity(self):
        pending = self.pending()
        spec, _ = self.readback(pending, git_source_commit=git(self.root, "rev-parse", "HEAD~1"))
        with self.assertRaisesRegex(SystemExit, "source revision pending"):
            self.bundle("--receipt", spec)
        spec, _ = self.readback(pending)
        pending["intent_id"] = "different-operation"
        self.commit_sync(pending)
        with self.assertRaisesRegex(SystemExit, "intent_id"):
            self.bundle("--receipt", spec)

    def test_receipt_rejects_source_digest_or_base_business_changes(self):
        pending = self.pending()
        pending["content_sha256"] = "0" * 64
        self.commit_sync(pending)
        spec, _ = self.readback(pending)
        with self.assertRaisesRegex(SystemExit, "source business digest"):
            self.bundle("--receipt", spec)
        pending = self.pending()
        spec, _ = self.readback(pending)
        (self.root / self.req_path).write_text("changed after synchronization")
        git(self.root, "add", self.req_path)
        git(self.root, "commit", "--quiet", "-m", "unsynchronized business")
        with self.assertRaisesRegex(SystemExit, "base business digest"):
            self.bundle("--receipt", spec)

    def test_receipt_rejects_source_outside_selected_history(self):
        pending = self.pending()
        unrelated = git(self.root, "commit-tree", git(self.root, "rev-parse", "HEAD^{tree}"), "-m", "unrelated")
        spec, _ = self.readback(pending, git_source_commit=unrelated)
        with self.assertRaises(SystemExit):
            self.bundle("--receipt", spec)

    def test_receipt_requires_pending_and_explicit_baseline(self):
        pending = self.pending()
        spec, data = self.readback(pending)
        del data["baseline_fields"]
        (self.root / "readback.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(SystemExit, "baseline_fields"):
            self.bundle("--receipt", spec)
        self.commit_sync({"state": "verified"})
        spec, _ = self.readback(pending)
        with self.assertRaisesRegex(SystemExit, "must be pending"):
            self.bundle("--receipt", spec)

    def test_paths_are_validated_before_reading_disk(self):
        for path in ("../outside", ".env", "workitems/../outside", "unknown.txt"):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                self.bundle("--write", path)
        (self.root / self.req_path).unlink()
        (self.root / self.req_path).symlink_to(self.root / self.item_path)
        with self.assertRaisesRegex(SystemExit, "symlink"):
            self.bundle("--write", self.req_path)


class RemoteBundleTest(unittest.TestCase):
    # Reuse fixture methods without importing/inheriting its test case into discovery.
    setUp = runtime_tests.WorkspaceTest.setUp
    configure = runtime_tests.WorkspaceTest.configure
    write = runtime_tests.WorkspaceTest.write
    remote_head = runtime_tests.WorkspaceTest.remote_head

    def assemble(self, root, *args):
        out = self.directory / "constructed.json"
        make_bundle.main(["--root", str(root), "--session", "test", "--token", "t1",
                          "--message", "checkpoint", "--out", str(out), *args])
        return out, json.loads(out.read_text())

    def test_fetched_base_publishes_once_from_old_head_preserving_remote_changes(self):
        name = "workitems/A/item.json"
        remote_item = json.loads((self.b / name).read_text())
        remote_item["title"] = "remote title"
        self.write(self.b, name, runtime_tests.text(remote_item))
        self.write(self.b, ".project/context.md", "remote context\n")
        git(self.b, "add", ".")
        git(self.b, "commit", "--quiet", "-m", "remote advance")
        git(self.b, "push", "--quiet", "origin", "main")
        git(self.a, "fetch", "--quiet", "origin", "main")
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)
        original = (self.a / name).read_bytes()
        remote_item["archived"] = True
        self.write(self.a, name, runtime_tests.text(remote_item))
        out, bundle = self.assemble(self.a, "--base", "FETCH_HEAD", "--write", name)
        self.assertEqual(bundle["checks"][name], sha256_text((self.b / name).read_text()))
        (self.a / name).write_bytes(original)
        with mock.patch.object(runtime, "publish", wraps=runtime.publish) as publisher:
            result = runtime.publish(self.a, out)
        self.assertEqual(publisher.call_count, 1)
        self.assertEqual(result["verified_remote_commit"], self.remote_head())
        self.assertEqual((self.a / ".project/context.md").read_text(), "remote context\n")
        actual = json.loads((self.a / name).read_text())
        self.assertEqual(actual["title"], "remote title")
        self.assertTrue(actual["archived"])
        self.assertEqual(runtime.validate_project(self.a), [])

    def test_two_business_syncs_publish_latest_real_baselines_without_retries(self):
        item_path, req_path, sync_path = "workitems/A/item.json", "workitems/A/requirement.md", ".project/sync/A.json"
        digest = make_bundle.Snapshot(self.a, self.base).digest("A")
        prior = {"intent_id": "initial", "state": "verified", "external_id": "123",
                 "content_sha256": digest, "baseline_fields": {"title": "A", "body": "old"},
                 "git_source_commit": self.base, "checked_at": "2026-10-15T01:00:00+00:00"}
        self.write(self.a, sync_path, runtime_tests.text(prior))
        git(self.a, "add", sync_path)
        git(self.a, "commit", "--quiet", "-m", "initial receipt")
        git(self.a, "push", "--quiet", "origin", "main")
        with mock.patch.object(runtime, "publish", wraps=runtime.publish) as publisher:
            for version in (1, 2):
                old_item = (self.a / item_path).read_bytes()
                old_body = (self.a / req_path).read_bytes() if (self.a / req_path).exists() else None
                item = json.loads(old_item)
                item["title"] = f"title {version}"
                self.write(self.a, item_path, runtime_tests.text(item))
                self.write(self.a, req_path, f"body {version}\n")
                out, bundle = self.assemble(self.a, "--write", item_path,
                                           "--new" if old_body is None else "--write", req_path,
                                           "--intent", "A:123:开发中:142838")
                pending = json.loads(bundle["writes"][sync_path])
                self.assertEqual(pending["baseline_fields"], prior["baseline_fields"])
                (self.a / item_path).write_bytes(old_item)
                if old_body is None:
                    (self.a / req_path).unlink()
                else:
                    (self.a / req_path).write_bytes(old_body)
                runtime.publish(self.a, out)
                baseline = {"title": f"title {version}", "body": f"body {version}\n", "status": "142838"}
                evidence = {"intent_id": pending["intent_id"], "external_id": "123",
                            "content_sha256": pending["content_sha256"],
                            "git_source_commit": git(self.a, "rev-parse", "HEAD"),
                            "baseline_fields": baseline, "checked_at": f"2026-10-15T0{version + 1}:00:00+00:00"}
                readback = self.directory / "readback.json"
                readback.write_text(runtime_tests.text(evidence))
                out, _ = self.assemble(self.a, "--receipt", f"A:{readback}")
                runtime.publish(self.a, out)
                prior = json.loads((self.a / sync_path).read_text())
                self.assertEqual(prior["baseline_fields"], baseline)
                self.assertEqual(prior["checked_at"], evidence["checked_at"])
                self.assertEqual(runtime.validate_project(self.a), [])
            self.assertEqual(publisher.call_count, 4)  # Two pending/receipt pairs, no retry.


if __name__ == "__main__":
    unittest.main()
