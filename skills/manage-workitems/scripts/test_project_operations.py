"""Behavioral checks for deterministic business operation preparation."""

import copy
import hashlib
import json
import unittest

import project_operations as operations
import project_runtime as runtime
import test_project_runtime as fixtures

text = fixtures.text


class OperationsTest(unittest.TestCase):
    setUp = fixtures.WorkspaceTest.setUp
    configure = fixtures.WorkspaceTest.configure
    write = fixtures.WorkspaceTest.write
    add_item = fixtures.WorkspaceTest.add_item
    publish = fixtures.WorkspaceTest.publish
    bundle = fixtures.WorkspaceTest.bundle

    def request(self, *entries, **options):
        return dict(session="test", message="更新项目", operations=list(entries), **options)

    def prepare(self, *entries, **options):
        return operations.prepare(self.a, self.request(*entries, **options))

    def install(self, result):
        for name, value in result["bundle"]["writes"].items():
            self.write(self.a, name, value)

    def test_create_alias_selector_and_unknown_fields_are_preserved(self):
        old = self.add_item(self.a, "A", title="原始需求", custom={"保留": True})
        result = self.prepare(
            {"op": "create", "slug": "quota-lock", "title": "统一配额锁", "requirement": "已知需求\n待确认验收", "alias": "parent"},
            {"op": "create", "slug": "quota-release", "title": "配额释放", "requirement": "释放需求", "parent": "$parent", "depends_on": ["原始需求"]},
            {"op": "update", "item": "原始需求", "set": {"title": "已更新需求"}},
            {"op": "archive", "item": "$parent"})
        writes = result["bundle"]["writes"]
        parent = json.loads(writes["workitems/1-quota-lock/item.json"])
        child = json.loads(writes["workitems/11-quota-release/item.json"])
        updated = json.loads(writes["workitems/A/item.json"])
        self.assertTrue(parent["archived"])
        self.assertEqual(child["split_from"], parent["id"])
        self.assertEqual(child["depends_on"], ["A"])
        self.assertEqual(updated["custom"], old["custom"])
        summary = next(entry for entry in result["item_summaries"] if entry["id"] == child["id"])
        self.assertEqual((summary["title"], summary["blocked_by"]), ("配额释放", ["A"]))
        effect = next(entry for entry in result["dependency_effects"] if entry["id"] == child["id"])
        self.assertFalse(effect["dependency_ready"])
        self.assertEqual(effect["blocked_by"], ["A"])
        self.assertFalse((self.a / "workitems/1-quota-lock").exists())
        for name in writes:
            self.assertIn(name, result["bundle"]["checks"])
        self.assertIn(".project/project.json", result["bundle"]["checks"])

    def test_batch_failure_cycle_and_ambiguous_selector_are_atomic(self):
        before = runtime._working_files(self.a)
        with self.assertRaisesRegex(runtime.ProjectError, "cycle"):
            self.prepare({"op": "update", "item": "A", "set": {"depends_on": ["B"]}},
                         {"op": "update", "item": "B", "set": {"depends_on": ["A"]}})
        self.assertEqual(runtime._working_files(self.a), before)
        self.add_item(self.a, "A", title="相同标题")
        self.add_item(self.a, "B", title="相同标题")
        with self.assertRaisesRegex(runtime.ProjectError, "ambiguous"):
            self.prepare({"op": "archive", "item": "相同标题"})

    def test_unknown_request_or_operation_fields_reject_the_entire_batch(self):
        before = runtime._working_files(self.a)
        create = {"op": "create", "slug": "quota-lock", "title": "统一配额锁", "requirement": "需求"}
        requests = [self.request({"op": "archive", "item": "A"}, dict(create, repo="code")),
                    self.request({"op": "archive", "item": "A"}, dict(create, dependsOn=["B"])),
                    self.request({"op": "update", "item": "A", "set": {"status": "cancelled"}, "provenance": "user correction"}),
                    self.request({"op": "archive", "item": "A", "reason": "Design handoff"}),
                    dict(self.request(create), mesage="typo"),
                    dict(self.request(create), token="obsolete-unused-token")]
        for request in requests:
            with self.subTest(request=request):
                result = None
                with self.assertRaisesRegex(runtime.ProjectError, "unknown fields"):
                    result = operations.prepare(self.a, request)
                self.assertIsNone(result)
                self.assertEqual(runtime._working_files(self.a), before)

    def test_number_phrase_selectors_and_no_op_preserve_original_bytes(self):
        self.add_item(self.a, "1-quota-lock", title="统一配额锁")
        self.assertIsNone(self.prepare({"op": "update", "item": "1", "set": {"title": "统一配额锁"}})["bundle"])
        self.assertEqual(self.prepare({"op": "archive", "item": "quota-lock", "archived": False})["changes"], [])
        self.assertEqual(self.prepare({"op": "update", "item": "统一配额锁", "set": {"title": "统一配额锁"}})["items"], [])

    def test_document_hash_paths_and_append_guards(self):
        self.write(self.a, "workitems/A/requirement.md", "原始需求\n")
        old = (self.a / "workitems/A/requirement.md").read_bytes()
        for expected in (None, "0" * 64):
            with self.subTest(expected=expected), self.assertRaisesRegex(runtime.ProjectError, "expected_sha256"):
                self.prepare({"op": "document", "item": "A", "name": "requirement.md", "text": "新版", "expected_sha256": expected})
        result = self.prepare({"op": "document", "item": "A", "name": "requirement.md", "mode": "append", "text": "新段落\n"})
        self.assertEqual(result["bundle"]["writes"]["workitems/A/requirement.md"], "原始需求\n新段落\n")
        self.assertEqual(result["bundle"]["checks"]["workitems/A/requirement.md"], hashlib.sha256(old).hexdigest())
        for name in ("../B/spec.md", "/tmp/a.md", "reviews/../../../AGENTS.md", "item.json"):
            with self.subTest(name=name), self.assertRaises(runtime.ProjectError):
                self.prepare({"op": "document", "item": "A", "name": name, "text": "bad"})
        (self.a / "workitems/A/spec.md").symlink_to(self.directory / "outside")
        with self.assertRaisesRegex(runtime.ProjectError, "symlink"):
            self.prepare({"op": "document", "item": "A", "name": "spec.md", "text": "bad"})

    def test_project_and_evidence_document_paths(self):
        old_hash = hashlib.sha256((self.a / "AGENTS.md").read_bytes()).hexdigest()
        result = self.prepare({"op": "document", "path": "AGENTS.md", "text": "New instructions\n", "expected_sha256": old_hash},
                              {"op": "document", "path": "evidence/routing.md", "text": "Observed routing\n"},
                              {"op": "document", "path": "evidence/routing.json", "text": text({
                                  "id": "routing", "repository": "code", "topic": "routing", "summary": "Observed", "scope": "code",
                                  "kind": "fact", "inputs": {}, "sources": [{"path": "src/router.py"}], "body": "evidence/routing.md"})})
        self.assertEqual(result["items"], [])
        self.assertIn("evidence/routing.json", result["bundle"]["writes"])
        for path in (".project/project.json", ".project/sync/A.json", ".gitignore", "workitems/A/item.json"):
            with self.subTest(path=path), self.assertRaises(runtime.ProjectError):
                self.prepare({"op": "document", "path": path, "text": "{}"})

    def test_historical_owner_allows_edits_and_business_gates_remain(self):
        owner = {"machine": "old", "session": "other", "token": "secret"}
        self.add_item(self.a, "A", owner=owner)
        changed = self.prepare({"op": "archive", "item": "A"})
        self.assertEqual(changed["items"], ["A"])
        self.assertNotIn("owner", json.loads(changed["bundle"]["writes"]["workitems/A/item.json"]))
        for status in ("done", "developing"):
            with self.subTest(status=status), self.assertRaisesRegex(runtime.ProjectError, "migration.*deliver"):
                self.prepare({"op": "update", "item": "B", "set": {"status": status}})
        with self.assertRaisesRegex(runtime.ProjectError, "through deliver"):
            self.prepare({"op": "update", "item": "B", "set": {"delivery": {"required": ["merged"], "status": "delivered", "evidence": [{"kind": "merged", "reference": "PR"}]}}})
        for field in ("id", "split_from", "owner"):
            with self.subTest(field=field), self.assertRaisesRegex(runtime.ProjectError, "mutable fields"):
                self.prepare({"op": "update", "item": "B", "set": {field: None}})

    def test_requirement_and_dependency_changes_invalidate_review(self):
        self.write(self.a, "workitems/A/spec.md", "---\ndesign_status: implementable\n---\nCurrent spec\n")
        self.write(self.a, "workitems/A/requirement.md", "Old requirement")
        self.add_item(self.a, "B", depends_on=["A"])
        self.write(self.a, "workitems/B/spec.md", "---\ndesign_status: 'implementable'\n---\nDependent spec\n")
        result = self.prepare({"op": "document", "item": "A", "name": "requirement.md", "text": "New requirement", "expected_sha256": hashlib.sha256(b"Old requirement").hexdigest()})
        self.assertIn("design_status: draft", result["bundle"]["writes"]["workitems/A/spec.md"])
        self.assertNotIn("workitems/B/spec.md", result["bundle"]["writes"])
        self.assertEqual(result["items"], ["A"])
        self.assertEqual({entry["item"] for entry in result["required_actions"]}, {"A", "B"})
        self.assertEqual(next(entry["action"] for entry in result["required_actions"] if entry["item"] == "B"), "assess_dependency_review")
        self.add_item(self.a, "B", depends_on=["A"], owner={"machine": "elsewhere", "session": "other", "token": "other"})
        self.assertEqual(self.prepare({"op": "document", "item": "A", "name": "requirement.md", "text": "New requirement", "expected_sha256": hashlib.sha256(b"Old requirement").hexdigest()})["items"], ["A"])

    def test_delivered_item_cannot_reopen_and_keep_dependents_ready(self):
        self.add_item(self.a, "A", status="done", delivery={
            "required": ["merged"], "status": "delivered",
            "evidence": [{"kind": "merged", "reference": "verified merge"}]})
        for values in ({"status": "in_progress"}, {"status": "cancelled"},
                       {"status": "in_progress", "delivery": {"status": "pending"}}):
            with self.subTest(values=values), self.assertRaisesRegex(runtime.ProjectError, "cannot reopen"):
                self.prepare({"op": "update", "item": "A", "set": values},
                             machine="here")

    def test_create_can_publish_after_unrelated_remote_metadata_update(self):
        prepared = self.prepare({"op": "create", "slug": "quota-lock", "title": "统一配额锁", "requirement": "需求"})
        self.assertNotIn("workitems/A/item.json", prepared["bundle"]["checks"])
        self.publish(self.b, self.bundle(self.b, "A", {"title": "远端无关变更"}))
        self.publish(self.a, prepared["bundle"])
        self.assertEqual(runtime.read_json(self.a / "workitems/A/item.json")["title"], "远端无关变更")
        self.assertEqual(runtime.read_json(self.a / "workitems/1-quota-lock/item.json")["title"], "统一配额锁")


    def test_deliver_requires_evidence_and_aggregate_acceptance(self):
        delivery = {"op": "deliver", "item": "A", "evidence": [{"kind": "merged", "reference": "PR#1@commit"}], "provenance": "verified by current agent"}
        with self.assertRaisesRegex(runtime.ProjectError, "every required"):
            self.prepare(dict(delivery, evidence=[{"kind": "tests", "reference": "local"}]))
        result = self.prepare(delivery)
        delivered = json.loads(result["bundle"]["writes"]["workitems/A/item.json"])
        self.assertEqual(delivered["status"], "done")
        self.install(result)
        self.write(self.a, "workitems/A/requirement.md", "Accepted requirement")
        with self.assertRaisesRegex(runtime.ProjectError, "reset delivered"):
            self.prepare({"op": "document", "item": "A", "name": "requirement.md", "text": "Changed acceptance", "expected_sha256": hashlib.sha256(b"Accepted requirement").hexdigest()})
        self.add_item(self.a, "A")
        self.add_item(self.a, "B", kind="aggregate", repository=None, depends_on=["A"], delivery={"required": ["dependencies"], "status": "pending", "evidence": []})
        aggregate = {"op": "deliver", "item": "B", "evidence": [{"kind": "dependencies", "reference": "A delivery"}], "provenance": "agent"}
        with self.assertRaisesRegex(runtime.ProjectError, "prerequisite"):
            self.prepare(aggregate)
        with self.assertRaisesRegex(runtime.ProjectError, "acceptance_coverage"):
            self.prepare(delivery, aggregate)
        self.assertEqual(self.prepare(delivery, dict(aggregate, acceptance_coverage="A covers all acceptance"))["items"], ["A", "B"])

    def test_sync_pending_is_preserved_and_verified_baseline_is_returned(self):
        receipt = {"intent_id": "intent", "content_sha256": runtime.item_digest(self.a, "A"), "state": "pending",
                   "external_id": None, "baseline_fields": None, "git_source_commit": None, "checked_at": None}
        self.write(self.a, ".project/sync/A.json", text(receipt))
        with self.assertRaisesRegex(runtime.ProjectError, "unresolved pending"):
            self.prepare({"op": "archive", "item": "A"})
        self.add_item(self.a, "A", owner={"machine": "here", "session": "test", "token": "mine"})
        with self.assertRaisesRegex(runtime.ProjectError, "before business update"):
            self.prepare({"op": "update", "item": "A", "set": {"title": "New pending title"}})
        self.add_item(self.a, "A")
        self.assertEqual(runtime.read_json(self.a / ".project/sync/A.json"), receipt)
        receipt.update(state="verified", external_id="123", baseline_fields={"title": "A"}, git_source_commit=self.base, checked_at="now")
        self.write(self.a, ".project/sync/A.json", text(receipt))
        result = self.prepare({"op": "archive", "item": "A"})
        self.assertEqual(result["sync_context"]["A"]["receipt"], receipt)
        self.assertTrue(result["sync_context"]["A"]["business_changed"])
        self.assertNotIn(".project/sync/A.json", result["bundle"]["writes"])


if __name__ == "__main__":
    unittest.main()
