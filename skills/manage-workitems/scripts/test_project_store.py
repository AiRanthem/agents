"""Storage roundtrips and real temporary Git publication contracts."""
import copy
import hashlib
import json
import unittest
from unittest import mock
import project_store as store
import project_runtime as runtime
from test_project_runtime import item, text, git
import test_project_runtime as fixtures


def initial():
    return {".project/project.yaml": store.dump_yaml({"schema_version": 2, "id": "p"}).encode()}


class StoreTest(unittest.TestCase):
    def test_strict_yaml_roundtrip(self):
        value = {"中文": [None, False, 12, "2026-10-16", "yes"], "nested": {"a": "b"}}
        self.assertEqual(store.load_yaml(store.dump_yaml(value)), value)
        for invalid in ("a: 1\na: 2\n", "a: 2026-10-16\n", "a: .inf\n", "a: !!set {x: null}\n", "a: &a [*a]\n", "1: value\n"):
            with self.subTest(invalid=invalid), self.assertRaises(store.StoreError):
                store.load_yaml(invalid)

    def test_expanded_roundtrip_and_state_ownership(self):
        files = initial()
        record = item("1-feature")
        record.update(owner={"session": "s", "machine": "m", "token": "t"}, fixes="2-original",
                      custom_business={"decision": "保留"}, design={"file": "spec.md", "version": 1, "state": "draft", "approval": {"identity": "reviewer"}}, workflow={"review": {"identity": "reviewer"}})
        record["delivery"]["provenance"] = {"source": "test"}
        writes = store.write_item(files, record)
        metadata = store.load_yaml(writes["workitems/1-feature/metadata.yaml"])
        state = store.load_yaml(writes[".project/state/1-feature.yaml"])
        self.assertNotIn("owner", metadata)
        self.assertNotIn("evidence", metadata["delivery"])
        self.assertNotIn("approval", metadata["design"])
        self.assertEqual(state["design"]["approval"], record["design"]["approval"])
        self.assertEqual(state["owner"], record["owner"])
        files = store.apply_writes(files, writes)
        expanded = store.item(files, "1-feature")
        for key, value in record.items():
            self.assertEqual(expanded[key], value)
        legacy = store.as_legacy(files)
        self.assertNotIn(".project/project.yaml", legacy)
        self.assertEqual(json.loads(legacy["workitems/1-feature/item.json"]), expanded)
        self.assertEqual(store.project(files)["schema_version"], 2)

    def test_mixed_authority_and_operational_shadowing(self):
        files = store.apply_writes(initial(), store.write_item(initial(), item("A")))
        for name in (".project/project.json", "workitems/A/item.json", ".project/sync/A.json"):
            with self.subTest(name=name), self.assertRaisesRegex(store.StoreError, "mixed"):
                store.as_legacy(dict(files, **{name: b"{}"}))
        metadata = store.load_yaml(files["workitems/A/metadata.yaml"])
        metadata["owner"] = {"session": "hidden"}
        files["workitems/A/metadata.yaml"] = store.dump_yaml(metadata).encode()
        with self.assertRaisesRegex(store.StoreError, "operational state"):
            store.items(files)

    def test_owner_claim_requires_matching_session_and_token_in_both_formats(self):
        v1 = {".project/project.json": text({"schema_version": 1}).encode()}
        for marker in (v1, initial()):
            with self.subTest(v2=store.is_v2(marker)):
                current = store.apply_writes(marker, store.write_item(marker, item("A")))
                claimed = dict(item("A"), owner={"machine": "m", "session": "s", "token": "stranded"})
                writes = store.write_item(current, claimed)
                bundle = {"session": "s", "token": "real", "writes": writes,
                          "checks": {name: None for name in writes}}
                with self.assertRaisesRegex(runtime.ProjectError, "owner.session/token"):
                    runtime._check_owners(bundle, current, store.apply_writes(current, writes))
                claimed["owner"]["token"] = "real"
                writes = store.write_item(current, claimed)
                bundle["writes"] = writes
                owned = store.apply_writes(current, writes)
                runtime._check_owners(bundle, current, owned)
                # A retained claim and an explicit release remain legal for this identity.
                runtime._check_owners(bundle, owned, owned)
                writes = store.write_item(owned, dict(claimed, owner=None))
                bundle["writes"] = writes
                runtime._check_owners(bundle, owned, store.apply_writes(owned, writes))

    def test_v1_read_and_writes_stay_explicit_v1(self):
        files = {".project/project.json": text({"schema_version": 1}).encode(), "workitems/A/item.json": text(item("A")).encode()}
        self.assertEqual(store.item(files, "A"), item("A"))
        self.assertEqual(set(store.write_item(files, item("A"))), {"workitems/A/item.json"})
        self.assertFalse(store.is_v2(files))


class V2PublicationTest(unittest.TestCase):
    setUp = fixtures.WorkspaceTest.setUp
    configure = fixtures.WorkspaceTest.configure
    write = fixtures.WorkspaceTest.write
    publish = fixtures.WorkspaceTest.publish
    remote_head = fixtures.WorkspaceTest.remote_head

    def migration(self):
        old = runtime._working_files(self.a)
        project = dict(self.project, schema_version=2)
        writes = {".project/project.json": None, ".project/project.yaml": store.dump_yaml(project)}
        v2 = store.apply_writes(old, writes)
        for identifier in ("A", "B"):
            writes.update(store.write_item(v2, item(identifier)))
            writes[f"workitems/{identifier}/item.json"] = None
        checks = {name: hashlib.sha256(data).hexdigest() for name, data in old.items()}
        checks.update({name: checks.get(name) for name in writes})
        return {"message": "migrate", "session": "test", "token": None, "checks": checks, "writes": writes}

    def test_atomic_migration_publication_and_refresh(self):
        result = self.publish(self.a, self.migration())
        self.assertEqual(result["verified_remote_commit"], self.remote_head())
        self.assertFalse((self.a / ".project/project.json").exists())
        self.assertFalse((self.a / "workitems/A/item.json").exists())
        self.assertEqual(runtime.validate_project(self.a), [])
        self.assertEqual(runtime.read_project(self.a)["schema_version"], 2)
        self.assertTrue(runtime.refresh_project(self.b)["changed"])
        self.assertEqual(runtime.validate_project(self.b), [])
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertEqual(runtime.new_ids(self.a, ["feature"]), ["1-feature"])

    def test_owner_guards_and_business_digest(self):
        self.publish(self.a, self.migration())
        files = runtime._working_files(self.a)
        record = store.item(files, "A")
        record["owner"] = {"session": "test", "machine": "m", "token": "t"}
        writes = store.write_item(files, record)
        checks = {name: hashlib.sha256(files[name]).hexdigest() if name in files else None for name in writes}
        bundle = {"message": "claim", "session": "test", "token": "t", "checks": checks, "writes": writes}
        missing = copy.deepcopy(bundle)
        del missing["checks"][".project/state/A.yaml"]
        del missing["writes"][".project/state/A.yaml"]
        with self.assertRaisesRegex(runtime.ProjectError, "must check .project/state/A.yaml"):
            self.publish(self.a, missing)
        self.publish(self.a, bundle)
        files = runtime._working_files(self.a)
        record = store.item(files, "A")
        record["owner"] = None
        ownerless = store.apply_writes(files, store.write_item(files, record))
        self.assertEqual(runtime._business_digest(files, "A"), runtime._business_digest(ownerless, "A"))
        writes = store.write_item(files, record)
        bundle.update(writes=writes, checks={name: hashlib.sha256(files[name]).hexdigest() for name in writes}, session="other")
        with self.assertRaisesRegex(runtime.ProjectError, "owned by another"):
            self.publish(self.a, bundle)

    def test_deletion_requires_same_id_replacement(self):
        bundle = self.migration()
        del bundle["writes"]["workitems/A/metadata.yaml"]
        with self.assertRaisesRegex(runtime.ProjectError, "same-record YAML replacement"):
            self.publish(self.a, bundle)
        name = "workitems/A/item.json"
        files = runtime._working_files(self.a)
        bundle = {"message": "delete", "session": "test", "token": None,
                  "checks": {name: hashlib.sha256(files[name]).hexdigest()}, "writes": {name: None}}
        with self.assertRaisesRegex(runtime.ProjectError, "same-record YAML replacement"):
            self.publish(self.a, bundle)

    def test_v2_schema_keeps_markdown_opaque_and_rejects_orphan_state_and_graph(self):
        bundle = self.migration()
        files = store.apply_writes(runtime._working_files(self.a), bundle["writes"])
        self.assertEqual(runtime._validate_files(self.a, files), [])
        record = store.item(files, "A")
        record["design"] = {"file": "spec.md", "version": 1, "state": "draft"}
        files = store.apply_writes(files, store.write_item(files, record))
        files["workitems/A/spec.md"] = b"---\ndesign_status: implementable\nunparseable YAML: [\n---\n"
        self.assertEqual(runtime._validate_files(self.a, files), [])
        self.assertEqual(store.item(files, "A")["design"]["state"], "draft")
        invalid = dict(files, **{".project/state/missing.yaml": b"{}\n", ".project/graph.yaml": b"revision: true\n"})
        errors = runtime._validate_files(self.a, invalid)
        for expected in ("state must refer", "nonnegative integer revision"):
            self.assertTrue(any(expected in error for error in errors), errors)

    def interrupted_publication(self, *, sent):
        bundle = fixtures.WorkspaceTest.bundle(self, self.a, "A", {"title": "recover me"})
        original_git = runtime._git
        def interrupt(root, *args, **kwargs):
            if args and args[0] == "push":
                if sent:
                    original_git(root, *args, **kwargs)
                raise runtime.ProjectError("simulated lost push response")
            return original_git(root, *args, **kwargs)
        with mock.patch.object(runtime, "_git", side_effect=interrupt), self.assertRaisesRegex(runtime.ProjectError, "lost push response"):
            self.publish(self.a, bundle)
        journals = list((self.a / ".project-local/publish").glob("*/journal.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)
        return journals[0], runtime.read_json(journals[0])

    def test_resume_lost_push_response_recovers_already_published_candidate(self):
        journal, state = self.interrupted_publication(sent=True)
        result = runtime.resume_publication(self.a, session="test", token=None)
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(result["code"], "publication_recovered")
        self.assertEqual(result["commit"], state["candidate"])
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.remote_head())
        self.assertEqual(runtime.read_json(journal)["state"], "published")
        self.assertEqual(runtime.resume_publication(self.a, session="test")["status"], "no_op")

    def test_resume_unsent_retries_exactly_original_candidate(self):
        journal, state = self.interrupted_publication(sent=False)
        self.assertEqual(self.remote_head(), self.base)
        result = runtime.resume_publication(self.a, session="test", journal=journal)
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(result["code"], "publication_retried")
        self.assertEqual(self.remote_head(), state["candidate"])
        self.assertEqual(runtime.read_json(journal)["recovery_attempts"], 1)

    def test_resume_retry_is_bounded_after_an_unresolved_push(self):
        journal, state = self.interrupted_publication(sent=False)
        original_git = runtime._git
        pushes = []
        def refuse(root, *args, **kwargs):
            if args and args[0] == "push":
                pushes.append(args)
                return mock.Mock(returncode=1, stdout=b"", stderr=b"refused")
            return original_git(root, *args, **kwargs)
        with mock.patch.object(runtime, "_git", side_effect=refuse):
            first = runtime.resume_publication(self.a, session="test", journal=journal)
            second = runtime.resume_publication(self.a, session="test", journal=journal)
        self.assertEqual(first["status"], "blocked", first)
        self.assertEqual(second["code"], "publication_retry_exhausted", second)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(self.remote_head(), self.base)
        self.assertEqual(runtime.read_json(journal)["candidate"], state["candidate"])

    def test_resume_remote_changed_stops_without_different_intent(self):
        journal, state = self.interrupted_publication(sent=False)
        other = fixtures.WorkspaceTest.bundle(self, self.b, "B", {"title": "remote changed"})
        self.publish(self.b, other)
        before, remote = journal.read_bytes(), self.remote_head()
        result = runtime.resume_publication(self.a, session="test", journal=journal)
        self.assertEqual(result["code"], "publication_remote_changed", result)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.remote_head(), remote)
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)

    def test_resume_dirty_or_wrong_identity_preserves_journal(self):
        journal, state = self.interrupted_publication(sent=True)
        before = journal.read_bytes()
        self.assertEqual(runtime.resume_publication(self.a, session="other", journal=journal)["status"], "blocked")
        self.write(self.a, "AGENTS.md", "dirty user changes\n")
        result = runtime.resume_publication(self.a, session="test", journal=journal)
        self.assertEqual(result["code"], "publication_local_dirty", result)
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), self.base)
        self.assertEqual(self.remote_head(), state["candidate"])

    def test_delivered_loophole_and_fix_graph(self):
        files = runtime._working_files(self.a)
        delivered = item("A")
        delivered["delivery"].update(status="delivered", evidence=[{"kind": "merged", "reference": "commit"}])
        delivered["status"] = "in_progress"
        files["workitems/A/item.json"] = text(delivered).encode()
        self.assertTrue(any("delivered requires done" in error for error in runtime._validate_files(self.a, files)))
        delivered["status"] = "done"
        files["workitems/A/item.json"] = text(delivered).encode()
        fixed = dict(item("B"), fixes="A")
        files["workitems/B/item.json"] = text(fixed).encode()
        self.assertEqual(runtime._validate_files(self.a, files), [])
        fixed["fixes"] = "missing"
        files["workitems/B/item.json"] = text(fixed).encode()
        self.assertTrue(any("fixes must identify" in error for error in runtime._validate_files(self.a, files)))
        delivered["fixes"] = "A"
        files["workitems/A/item.json"] = text(delivered).encode()
        self.assertTrue(any("fix relationship cycle" in error for error in runtime._validate_files(self.a, files)))


if __name__ == "__main__":
    unittest.main()
