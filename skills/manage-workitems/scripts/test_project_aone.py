"""Local a1 fixtures: v0.2.46 read-only whoami/list/get shape checked 2026-10-16.

Fixtures use the observed structural identifiers, never a fabricated JSON API
envelope. Mutation ID capture uses documented --quiet, followed by JSON get.
No test authenticates or contacts a real service.
"""

import copy
import json
from pathlib import Path
import subprocess
import unittest

from project_aone import AoneAdapter, AoneError, BEGIN, END
from project_runtime import STATUSES, _business_digest


COMMIT = "a" * 40


class FakeA1:
    def __init__(self):
        self.calls = []
        self.items = {}
        self.identity = "employee-1"
        self.create_output = "500"
        self.mutation_error = None
        self.reject_transition = False
        self.read_error = None
        self.list_error = None
        self.version = "a1 version 0.2.46 (2026-08-12)"

    def add(self, identifier, title, status, body, assignee="employee-1", custom=None):
        self.items[identifier] = {"id": identifier, "title": title,
                                  "status": status, "description": body,
                                  "assignee": assignee, "space": "space-1", "type": "type-1",
                                  "category": "Req", "custom": custom or {}}

    def __call__(self, argv, **kwargs):
        assert kwargs == {"capture_output": True, "text": True, "timeout": 45, "check": False}
        self.calls.append(list(argv))
        args = argv[2:]
        def option(key):
            return args[args.index(key) + 1]
        def result(value):
            return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
        if "--help" in args:
            return subprocess.CompletedProcess(argv, 0, "--project --scope --description --page --page-size --id --type --category --title --assignee --status --body-file --cfs --quiet --format", "")
        if args == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, self.version, "")
        if args[:2] == ["auth", "whoami"]:
            return result({"emp_id": self.identity})
        action = args[2]
        if action == "get":
            if self.read_error:
                return result(self.read_error)
            item = self.items[args[3]]
            values = {"status": item["status"], "space": item["space"],
                      "workitemType": item["type"], "assignedTo": item["assignee"], **item["custom"]}
            return result({"id": item["id"], "title": item["title"],
                           "url": "https://example.invalid/workitem/" + item["id"],
                           "createdAt": "2026-10-16", "updatedAt": "2026-10-16",
                           "description": item["description"],
                           "fields": [{"identifier": key, "label": key, "value": value,
                                       "displayValue": value, "format": "list", "className": "",
                                       "sourceType": "system", "isRequired": False}
                                      for key, value in values.items()]})
        if action == "list":
            if self.list_error is not None:
                return result(self.list_error)
            items = list(self.items.values())
            if "--id" in args:
                items = [item for item in items if item["id"] == option("--id")]
            if "--description" in args:
                items = [item for item in items if option("--description") in item["description"]]
            start = (int(option("--page")) - 1) * int(option("--page-size"))
            return result([{"identifier": item["id"], "subject": item["title"],
                            "status": item["status"], "spaceIdentifier": item["space"],
                            "workitemType": item["type"], "categoryIdentifier": item["category"],
                            "assignedTo": item["assignee"], "creator": "employee-1", "gmtModified": "0"}
                           for item in items[start:start + int(option("--page-size"))]])
        if action in {"create", "update"}:
            custom = {}
            for index, argument in enumerate(args):
                if argument == "--cfs":
                    key, value = args[index + 1].split("=", 1)
                    custom[key] = value
            body = Path(option("--body-file")).read_text(encoding="utf-8")
            identifier = "500" if action == "create" else args[3]
            if action == "create":
                self.add(identifier, option("--title"), option("--status"), body, option("--assignee"), custom)
            else:
                if "--status" in args and (option("--status") == self.items[identifier]["status"] or self.reject_transition):
                    return subprocess.CompletedProcess(argv, 1, "", "workflow transition rejected")
                self.items[identifier].update(title=option("--title"), description=body)
                if "--status" in args:
                    self.items[identifier]["status"] = option("--status")
                self.items[identifier]["custom"].update(custom)
            if self.mutation_error:
                raise self.mutation_error
            return subprocess.CompletedProcess(argv, 0, self.create_output if action == "create" else "updated", "")
        raise AssertionError(argv)

    @property
    def writes(self):
        return [call for call in self.calls if len(call) > 4 and call[4] in {"create", "update"} and "--help" not in call]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.project = {"id": "project-1", "name": "项目", "storage": {"url": "git@example:team/docs.git"},
                        "backends": {"aone": {"space_id": "space-1", "type": "type-1", "category": "req",
                                               "status_map": {status: status for status in STATUSES}}}}
        self.item = {"id": "1-example", "title": "需求", "status": "new", "owner": None,
                     "archived": False, "depends_on": []}
        self.files = {"workitems/1-example/item.json": json.dumps(self.item).encode(),
                      "workitems/1-example/requirement.md": "# 需求\n\n完整验收条件\n".encode(),
                      "workitems/1-example/spec.md": b"# Full spec remains in Git\n"}
        self.runner = FakeA1()
        self.adapter = AoneAdapter(self.project, self.runner)
        self.receipt = {"intent_id": "intent-1", "content_sha256": _business_digest(self.files, self.item["id"]),
                        "git_source_commit": COMMIT, "state": "pending", "external_id": None,
                        "baseline_fields": None, "checked_at": None, "release_owner": True}

    def created(self):
        plan = self.adapter.prepare_sync(self.item, self.files, self.receipt)
        return self.adapter.execute(plan)

    def changed(self, receipt):
        self.item["title"] = "更新需求"
        self.files["workitems/1-example/item.json"] = json.dumps(self.item).encode()
        result = copy.deepcopy(receipt)
        result.update(state="pending", intent_id="intent-2", content_sha256=_business_digest(self.files, self.item["id"]))
        return result

    def test_create_readback_and_immutable_references(self):
        receipt = self.created()
        self.assertEqual(receipt["state"], "verified")
        self.assertEqual(receipt["external_id"], "500")
        self.assertTrue(receipt["release_owner"])
        self.assertEqual(len(self.runner.writes), 1)
        self.assertIn("--quiet", self.runner.writes[0])
        body = receipt["baseline_fields"]["managed_body"]
        self.assertIn("完整验收条件", body)
        self.assertIn(f"Commit: {COMMIT}", body)
        self.assertIn("Path: workitems/1-example/spec.md", body)
        self.assertIn("Clone URL: git@example:team/docs.git", body)
        self.assertEqual(receipt["baseline_fields"]["title"], "【项目】需求")

    def test_create_must_read_back_the_intended_fields(self):
        original = self.runner
        def server_changes_title(argv, **kwargs):
            result = original(argv, **kwargs)
            if len(argv) > 4 and argv[4] == "create" and "--help" not in argv:
                original.items["500"]["title"] = "Unexpected server title"
            return result
        self.adapter.runner = server_changes_title
        with self.assertRaisesRegex(AoneError, "readback mismatch: title"):
            self.created()
        self.assertEqual(len(self.runner.writes), 1)

    def test_update_preserves_external_body_and_other_fields(self):
        receipt = self.created()
        item = self.runner.items["500"]
        item["description"] = "Manual notes\n" + item["description"] + "\nHuman footer"
        item["assignee"] = "manual-reassignment"
        plan = self.adapter.prepare_sync(self.item, self.files, self.changed(receipt))
        self.assertEqual(plan["action"], "update")
        # A manual edit outside the owned section between prepare/execute survives.
        item["description"] += "\nNew note"
        verified = self.adapter.execute(plan)
        self.assertEqual(verified["state"], "verified")
        self.assertTrue(item["description"].startswith("Manual notes\n"))
        self.assertTrue(item["description"].endswith("\nHuman footer\nNew note"))
        self.assertEqual(item["assignee"], "manual-reassignment")
        self.assertNotIn("--project", self.runner.writes[-1])
        self.assertNotIn("--status", self.runner.writes[-1])
        self.assertEqual(verified["baseline_fields"]["title"], "【项目】更新需求")

    def test_different_status_requests_transition_and_rejection_does_not_claim_other_writes(self):
        receipt = self.created()
        self.item["status"] = "developing"
        pending = self.changed(receipt)
        plan = self.adapter.prepare_sync(self.item, self.files, pending)
        before = copy.deepcopy(self.runner.items["500"])
        original_plan = copy.deepcopy(plan)
        self.runner.reject_transition = True
        with self.assertRaisesRegex(AoneError, "command failed"):
            self.adapter.execute(plan)
        args = self.runner.writes[-1]
        self.assertEqual(args[args.index("--status") + 1], "developing")
        self.assertEqual(self.runner.items["500"], before)
        self.assertEqual(plan, original_plan)
        self.assertEqual(pending["state"], "pending")
        self.runner.reject_transition = False
        verified = self.adapter.execute(plan)
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(verified["baseline_fields"]["status"], "developing")
        self.assertEqual(verified["baseline_fields"]["title"], "【项目】更新需求")

    def test_update_without_status_transition_still_checks_readback(self):
        receipt = self.created()
        plan = self.adapter.prepare_sync(self.item, self.files, self.changed(receipt))
        original = self.runner

        def corrupt_title(argv, **kwargs):
            result = original(argv, **kwargs)
            if len(argv) > 4 and argv[4] == "update" and "--help" not in argv:
                original.items["500"]["title"] = "Unexpected server title"
            return result

        self.adapter.runner = corrupt_title
        with self.assertRaisesRegex(AoneError, "readback mismatch: title"):
            self.adapter.execute(plan)
        self.assertNotIn("--status", self.runner.writes[-1])

    def test_manual_owned_drift_reports_exact_field(self):
        receipt = self.created()
        self.runner.items["500"]["title"] = "Human title"
        with self.assertRaisesRegex(AoneError, "managed-field drift: title$"):
            self.adapter.prepare_sync(self.item, self.files, self.changed(receipt))
        self.assertEqual(len(self.runner.writes), 1)

    def test_drift_between_prepare_execute_stops(self):
        receipt = self.created()
        plan = self.adapter.prepare_sync(self.item, self.files, self.changed(receipt))
        self.runner.items["500"]["status"] = "manual"
        with self.assertRaisesRegex(AoneError, "readback mismatch: status"):
            self.adapter.execute(plan)
        self.assertEqual(len(self.runner.writes), 1)

    def unknown_create(self):
        plan = self.adapter.prepare_sync(self.item, self.files, self.receipt)
        unknown = copy.deepcopy(self.receipt)
        unknown.update(state="unknown", operation=plan)
        return plan, unknown

    def test_lost_create_recovers_once_without_recreate(self):
        plan, unknown = self.unknown_create()
        self.runner.mutation_error = subprocess.TimeoutExpired("a1", 45)
        with self.assertRaisesRegex(AoneError, "timed out"):
            self.adapter.execute(plan)
        recovered = self.adapter.prepare_sync(self.item, self.files, unknown)
        self.assertEqual(recovered["action"], "adopt")
        self.assertEqual(self.adapter.execute(recovered)["external_id"], "500")
        self.assertEqual(len(self.runner.writes), 1)

    def test_absent_unknown_create_never_recreated(self):
        _, unknown = self.unknown_create()
        with self.assertRaisesRegex(AoneError, "0 candidates"):
            self.adapter.prepare_sync(self.item, self.files, unknown)
        self.assertEqual(self.runner.writes, [])

    def test_crash_after_journaling_adoption_can_resume(self):
        plan, unknown = self.unknown_create()
        self.adapter.execute(plan)
        adopted = self.adapter.prepare_sync(self.item, self.files, unknown)
        unknown["operation"] = adopted
        for external_id in (None, "500"):
            with self.subTest(external_id=external_id):
                unknown["external_id"] = external_id
                resumed = self.adapter.prepare_sync(self.item, self.files, unknown)
                self.assertEqual(resumed["action"], "adopt")
                self.assertEqual(self.adapter.execute(resumed)["external_id"], "500")
        self.assertEqual(len(self.runner.writes), 1)

    def test_ambiguous_unknown_create_never_recreated(self):
        plan, unknown = self.unknown_create()
        for identifier in ("500", "501"):
            self.runner.add(identifier, plan["expected_fields"]["title"], "new", plan["body"])
        with self.assertRaisesRegex(AoneError, "2 candidates"):
            self.adapter.prepare_sync(self.item, self.files, unknown)
        self.assertEqual(self.runner.writes, [])

    def test_unknown_create_wrong_identity_stops(self):
        plan, unknown = self.unknown_create()
        self.runner.add("500", plan["expected_fields"]["title"], "new", plan["body"], "other-employee")
        with self.assertRaisesRegex(AoneError, "assignedTo"):
            self.adapter.prepare_sync(self.item, self.files, unknown)

    def test_unknown_create_wrong_projection_stops(self):
        plan, unknown = self.unknown_create()
        self.runner.add("500", "wrong title", "new", plan["body"])
        with self.assertRaisesRegex(AoneError, "readback mismatch: title"):
            self.adapter.prepare_sync(self.item, self.files, unknown)

    def test_unknown_update_adopts_readback_without_second_write(self):
        receipt = self.created()
        pending = self.changed(receipt)
        plan = self.adapter.prepare_sync(self.item, self.files, pending)
        unknown = copy.deepcopy(pending)
        unknown.update(state="unknown", operation=plan)
        self.runner.mutation_error = subprocess.TimeoutExpired("a1", 45)
        with self.assertRaises(AoneError):
            self.adapter.execute(plan)
        recovered = self.adapter.prepare_sync(self.item, self.files, unknown)
        self.assertEqual(recovered["action"], "adopt")
        self.adapter.execute(recovered)
        self.assertEqual(len(self.runner.writes), 2)

    def test_schema_mismatch_stops_before_update(self):
        receipt = self.created()
        self.runner.read_error = {"id": "500", "title": "title", "fields": {}}
        with self.assertRaisesRegex(AoneError, "fields array"):
            self.adapter.prepare_sync(self.item, self.files, self.changed(receipt))

    def test_list_wrapper_not_guessed(self):
        _, unknown = self.unknown_create()
        self.runner.list_error = {"items": []}
        with self.assertRaisesRegex(AoneError, "array of objects"):
            self.adapter.prepare_sync(self.item, self.files, unknown)

    def test_old_baseline_requires_explicit_reconciliation(self):
        receipt = self.created()
        receipt["baseline_fields"] = {"description": "legacy"}
        with self.assertRaisesRegex(AoneError, "unsupported baseline_fields"):
            self.adapter.prepare_sync(self.item, self.files, receipt)

    def test_wrong_space_type_and_category_stop(self):
        receipt = self.created()
        for key in ("space", "type", "category"):
            with self.subTest(key=key):
                original = self.runner.items["500"][key]
                self.runner.items["500"][key] = "wrong"
                with self.assertRaisesRegex(AoneError, "identity mismatch"):
                    self.adapter.prepare_sync(self.item, self.files, receipt)
                self.runner.items["500"][key] = original

    def test_required_custom_fields_argv_and_readback(self):
        self.project["backends"]["aone"]["required_custom_fields"] = {"cf-1": "Required=Value"}
        self.adapter = AoneAdapter(self.project, self.runner)
        receipt = self.created()
        self.assertEqual(receipt["baseline_fields"]["custom_fields"], {"cf-1": "Required=Value"})
        args = self.runner.writes[0]
        self.assertEqual(args[args.index("--cfs") + 1], "cf-1=Required=Value")
        receipt = self.adapter.execute(self.adapter.prepare_sync(self.item, self.files, self.changed(receipt)))
        args = self.runner.writes[-1]
        self.assertNotIn("--status", args)
        self.assertEqual(args[args.index("--cfs") + 1], "cf-1=Required=Value")
        self.assertEqual(receipt["baseline_fields"]["custom_fields"], {"cf-1": "Required=Value"})
        self.runner.items["500"]["custom"]["cf-1"] = "Manual"
        with self.assertRaisesRegex(AoneError, "custom_fields.cf-1"):
            self.adapter.prepare_sync(self.item, self.files, receipt)

    def test_status_mapping_missing_cli_and_unsupported_config(self):
        for key, value, message in (("status_map", {"new": "new"}, "every local status"),
                                    ("dependency_relations", {"blocked_by": "blocked-by"}, "unsupported Aone configuration"),
                                    ("custom_fields", {"field": "value"}, "unsupported Aone configuration")):
            with self.subTest(key=key):
                project = copy.deepcopy(self.project)
                project["backends"]["aone"][key] = value
                with self.assertRaisesRegex(AoneError, message):
                    AoneAdapter(project, self.runner).preflight()
        def missing(*args, **kwargs):
            raise FileNotFoundError()
        with self.assertRaisesRegex(AoneError, "requires installed a1"):
            AoneAdapter(self.project, missing).preflight()

    def test_preflight_cached_and_unknown_version_rejected(self):
        self.adapter.preflight()
        count = len(self.runner.calls)
        self.adapter.preflight()
        self.assertEqual(len(self.runner.calls), count)
        self.runner.version = "a1 version 0.2.47"
        with self.assertRaisesRegex(AoneError, "unsupported a1 version"):
            AoneAdapter(self.project, self.runner).preflight()

    def test_changed_identity_between_prepare_execute_stops(self):
        plan, _ = self.unknown_create()
        self.runner.identity = "other-employee"
        with self.assertRaisesRegex(AoneError, "identity changed"):
            self.adapter.execute(plan)
        self.assertEqual(self.runner.writes, [])

    def test_non_single_create_id_remains_unknown(self):
        plan, unknown = self.unknown_create()
        self.runner.create_output = '{"id":"500"}'
        with self.assertRaisesRegex(AoneError, "no single ID"):
            self.adapter.execute(plan)
        self.assertEqual(self.adapter.prepare_sync(self.item, self.files, unknown)["action"], "adopt")

    def test_duplicate_or_nonfinite_json_is_rejected_without_diagnostics(self):
        def invalid(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, '{"emp_id":"a","emp_id":"b"}', "secret-token")
        self.adapter.runner = invalid
        with self.assertRaisesRegex(AoneError, "invalid JSON") as caught:
            self.adapter._whoami()
        self.assertNotIn("secret-token", str(caught.exception))

    def test_release_hint_and_journal_do_not_nest_recursively(self):
        receipt = self.created()
        receipt["operation"]["release_owner"] = True
        plan = self.adapter.prepare_sync(self.item, self.files, receipt)
        self.assertTrue(plan["release_owner"])
        self.assertNotIn("operation", plan["receipt"])
        self.assertEqual(plan["action"], "noop")
        self.assertTrue(self.adapter.execute(plan)["release_owner"])

    def test_business_digest_guard_and_reserved_marker(self):
        invalid = copy.deepcopy(self.receipt)
        invalid["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(AoneError, "business digest"):
            self.adapter.prepare_sync(self.item, self.files, invalid)
        self.files["workitems/1-example/requirement.md"] = (BEGIN + "reserved -->" + END).encode()
        with self.assertRaisesRegex(AoneError, "reserved"):
            self.adapter.desired(self.item, self.files, COMMIT)


if __name__ == "__main__":
    unittest.main()
