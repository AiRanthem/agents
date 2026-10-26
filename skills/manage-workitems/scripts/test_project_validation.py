"""Explicit user decisions replace verification gates without inventing reviews."""
import copy
import os
import unittest
from unittest import mock

import project
import project_autonomy as autonomy
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_autonomy as fixtures


class UserValidationTest(unittest.TestCase):
    def setUp(self):
        self.a = fixtures.AutonomyTest("runTest")
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.f, self.root = self.a.f, self.a.root

    def waive(self, gate):
        draft = self.f.begin("validation-waiver", gate=gate,
                             approval_source="User explicitly skips " + gate + " for current A")
        self.f.edit(draft, "User-authorized skip; no executed verification is claimed.\n")
        result = self.f.finish(draft)
        self.assertEqual(result["status"], "published", result)
        return self.f.record()["workflow"]["validation_waivers"][gate]

    def implement(self):
        self.a.approved()
        self.a.authorize()
        self.a.finish_execution(self.a.dispatch("design-review", "design-reviewer"))
        self.a.finish_execution(self.a.dispatch("implementation", "source-author"))

    def test_human_acceptance_replaces_missing_failed_and_stale_code_reviews(self):
        self.implement()
        self.a.finish_execution(self.a.dispatch("code-review", "reviewer"), outcome="fail")
        self.assertEqual(self.a.state()["next_role"], "fix")
        for tree in ("b" * 40, "f" * 40):
            self.a.snapshot["tree"] = tree
            self.assertEqual(autonomy.accept(self.root, "A", approval_source="User explicitly accepts current A",
                                             publish=self.f.publisher)["status"], "published")
            record = self.f.record()["development"]["review"]
            self.assertEqual(record["result"], "pass")
            self.assertEqual(record["approval_kind"], "human_acceptance")
            self.assertEqual(record["code_snapshot"]["tree"], tree)
            self.assertEqual(self.a.state()["state"], "accepted_awaiting_delivery")
            self.assertEqual(self.a.state()["implementation_approval_kind"], "human_acceptance")
            self.assertEqual(project._progress_item(self.f.record())["development"]["review_approval_kind"], "human_acceptance")
        self.a.snapshot["tree"] = "e" * 40
        self.assertFalse(autonomy._acceptance_valid(self.root, runtime._working_files(self.root), self.f.record()))

    def test_human_acceptance_supersedes_old_design_failure_and_keeps_actual_source(self):
        self.implement()
        item = self.f.record()
        item["design"]["review"]["result"] = "fail"
        self.f.install(item)
        old_review = copy.deepcopy(item["design"]["review"])
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "later-session"}):
            result = autonomy.accept(self.root, "A", approval_source="User accepts the current implementation", publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        item = self.f.record()
        self.assertEqual(item["design"]["review"], old_review)
        self.assertEqual(item["development"]["review"]["approval_kind"], "human_acceptance")
        self.assertEqual(item["workflow"]["autonomy"]["acceptance"]["recorded_by"], "later-session")
        self.assertEqual(self.a.state()["state"], "accepted_awaiting_delivery")

    def comparison(self, spec=None, publish=None):
        stage = self.f.begin("human-acceptance", approval_source="User explicitly confirms human acceptance passed for current A")
        if spec is not None:
            self.f.edit(stage, spec, "spec.md")
        self.f.edit(stage, "Compared the accepted code against the complete current design; aligned any implementation drift.\n", "report.md")
        return stage, workflow.finish(self.root, stage["ticket"], publish=publish or self.f.publisher)

    def test_comparison_aligns_only_current_spec_and_keeps_acceptance_deliverable(self):
        self.implement()
        self.a.approved("B")
        downstream = self.f.record("B")
        downstream["depends_on"] = ["A"]
        self.f.install(downstream)
        before = runtime._working_files(self.root)
        downstream_bytes = {name: value for name, value in before.items() if name.startswith("workitems/B/") or name == ".project/state/B.yaml"}
        dependency_binding = workflow._binding(before, downstream, workflow._base(downstream))
        original = copy.deepcopy(self.f.record())
        old_review = original["design"]["review"]
        old_pair = {name: before[name] for name in (old_review["report"], old_review["report"][:-3] + ".yaml")}
        self.a.snapshot["tree"] = "f" * 40
        self.f.fake_development.prepare = mock.Mock(side_effect=AssertionError("comparison must not prepare code"))
        spec = "# Current implementation\n\nActual behavior explicitly accepted after manual validation.\n"
        stage, result = self.comparison(spec)
        self.assertEqual(result["status"], "published", result)
        after = runtime._working_files(self.root)
        item = self.f.record()
        self.assertEqual(item["design"]["version"], original["design"]["version"] + 1)
        self.assertEqual(item["design"]["approval"]["kind"], "human_acceptance")
        self.assertEqual(item["design"]["review"], old_review)
        self.assertEqual({name: after[name] for name in old_pair}, old_pair)
        self.assertEqual({name: after[name] for name in downstream_bytes}, downstream_bytes)
        self.assertNotEqual(workflow._binding(after, downstream, workflow._base(downstream))["dependency_sha256"], dependency_binding["dependency_sha256"])
        self.assertEqual(item["workflow"]["autonomy"]["approved_contract"]["spec"], spec)
        self.assertTrue(autonomy._acceptance_valid(self.root, after, item))
        self.assertEqual(self.a.state()["state"], "accepted_awaiting_delivery")
        self.assertEqual(item["development"]["review"]["approval_kind"], "human_acceptance")
        self.assertEqual(item["development"]["review"]["code_snapshot"]["tree"], "f" * 40)
        self.assertEqual(stage["code_context"]["snapshot"]["tree"], "f" * 40)
        with self.assertRaises(runtime.ProjectError):
            workflow._approved(after, item)
        # The retained independent pass does not silently approve the new spec.
        self.assertEqual(workflow.begin(self.root, "development-start", "A", publish=self.f.publisher)["status"], "blocked")
        delivery = self.f.begin("delivery-record", kind=["merged"], reference=["Actual merge"], provenance="Actual delivery evidence")
        self.f.edit(delivery, "Verified actual merge ancestry and required delivery evidence.\n")
        self.assertEqual(self.f.finish(delivery)["status"], "published")
        self.assertEqual(self.f.record()["status"], "done")
        self.f.fake_development.prepare.assert_not_called()

    def test_comparison_without_drift_keeps_version_and_requires_explicit_source(self):
        self.implement()
        old = copy.deepcopy(self.f.record()["design"])
        parsed = project.parser().parse_args(["begin", "human-acceptance", "A", "--approval-source", "Actual explicit human acceptance"])
        self.assertEqual(parsed.operation, "human-acceptance")
        self.assertEqual(project._begin_options(parsed), {"approval_source": "Actual explicit human acceptance"})
        self.f.write(self.root, "workitems/A/decision.md", "Current implementation decisions confirmed by the same explicit human acceptance.\n")
        missing = workflow.begin(self.root, "human-acceptance", "A", publish=self.f.publisher)
        self.assertEqual(missing["status"], "blocked")
        stage, result = self.comparison()
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record()["design"]["version"], old["version"])
        self.assertEqual(self.f.record()["design"]["review"], old["review"])
        self.assertTrue(autonomy._acceptance_valid(self.root, runtime._working_files(self.root), self.f.record()))
        self.assertEqual(self.a.state()["state"], "accepted_awaiting_delivery")
        item = self.f.record()
        item["workflow"]["autonomy"].pop("authorization")
        self.f.install(item)
        self.assertEqual(self.a.state()["state"], "accepted_awaiting_delivery")
        self.a.snapshot["tree"] = "e" * 40
        self.assertFalse(autonomy._acceptance_valid(self.root, runtime._working_files(self.root), self.f.record()))
        self.assertEqual(self.a.state()["state"], "awaiting_acceptance")
        self.assertIsNone(self.a.state()["next_role"])
        self.assertTrue(self.a.state()["acceptance_refresh_required"])

    def test_comparison_rejects_code_or_document_changes_after_begin(self):
        self.implement()
        path = self.root / "workitems/A/context.md"
        for changed in ("code", "document"):
            with self.subTest(changed=changed):
                stage = self.f.begin("human-acceptance", approval_source="User accepts exactly the captured code")
                self.f.edit(stage, "Original comparison result.\n", "report.md")
                original = path.read_bytes()
                snapshot = copy.deepcopy(self.a.snapshot)
                if changed == "code":
                    self.a.snapshot["tree"] = "f" * 40
                else:
                    path.write_text("Changed assumption after comparison started.\n")
                result = self.f.finish(stage)
                self.assertEqual(result["code"], "stale_evidence", result)
                self.assertNotIn("acceptance", self.f.record()["workflow"]["autonomy"])
                self.a.snapshot.update(snapshot)
                path.write_bytes(original)

    def test_partial_comparison_recovers_same_spec_and_acceptance_intent(self):
        self.implement()
        for spec in ("# Accepted implementation\n\nCurrent observed behavior.\n", None):
            with self.subTest(spec_changed=spec is not None):
                attempts = []
                def interrupted(root, writes, identity, message, checks=None):
                    attempts.append(copy.deepcopy(writes))
                    result = self.f.publisher(root, writes, identity, message, checks)
                    return {"status": "partial"} if len(attempts) == 1 else result
                stage, result = self.comparison(spec, publish=interrupted)
                self.assertEqual(result["status"], "partial", result)
                saved = copy.deepcopy(self.f.record())
                snapshot = copy.deepcopy(self.a.snapshot)
                self.a.snapshot["tree"] = "e" * 40
                self.assertEqual(workflow.resume(self.root, stage["ticket"], publish=interrupted)["code"], "stale_evidence")
                self.a.snapshot.update(snapshot)
                with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "later-session"}):
                    result = workflow.resume(self.root, stage["ticket"], publish=interrupted)
                self.assertEqual(result["status"], "published", result)
                self.assertEqual(attempts[0], attempts[1])
                self.assertEqual(self.f.record(), saved)
                self.assertEqual(saved["development"]["review"]["recorded_by"], "author")
                self.assertEqual(self.a.state()["state"], "accepted_awaiting_delivery")

    def test_acceptance_waiver_alone_does_not_skip_implementation_review(self):
        self.implement()
        self.waive("human-acceptance")
        self.assertEqual(self.a.state()["next_role"], "code-review")
        self.a.finish_execution(self.a.dispatch("code-review", "reviewer"))
        autonomy.accept(self.root, "A", approval_source="User accepts the original code", publish=self.f.publisher)
        self.a.snapshot["tree"] = "e" * 40
        self.waive("human-acceptance")
        self.assertNotEqual(self.a.state()["state"], "accepted_awaiting_delivery")
        self.assertFalse(autonomy._acceptance_valid(self.root, runtime._working_files(self.root), self.f.record(), allow_waiver=False))

    def test_stale_human_review_cannot_borrow_code_waiver_for_design_approval(self):
        self.implement()
        _, result = self.comparison("# Accepted implementation\n\nActual current behavior.\n")
        self.assertEqual(result["status"], "published", result)
        self.a.snapshot["tree"] = "e" * 40
        self.waive("implementation-review")
        files = runtime._working_files(self.root)
        self.assertTrue(workflow._validation_waived(files, self.f.record(), "implementation-review"))
        with self.assertRaises(runtime.ProjectError):
            workflow._implementation_approved(files, self.f.record(), root=self.root)
        self.assertNotEqual(self.a.state()["state"], "accepted_awaiting_delivery")

    def test_named_waivers_require_actual_source_and_expire_with_contract(self):
        for options in ({"gate": "e2e"}, {"gate": "integrity", "approval_source": "Skip all"}):
            result = workflow.begin(self.root, "validation-waiver", "A", options=options, publish=self.f.publisher)
            self.assertEqual(result["status"], "blocked")
        record = self.waive("e2e")
        self.assertEqual(record["result"], "skipped")
        self.assertEqual(project._progress_item(self.f.record())["verification_waivers"]["e2e"]["result"], "skipped")
        self.assertTrue(workflow._validation_waived(runtime._working_files(self.root), self.f.record(), "e2e"))
        self.f.write(self.root, "workitems/A/requirement.md", "Changed contract\n")
        self.assertFalse(workflow._validation_waived(runtime._working_files(self.root), self.f.record(), "e2e"))

    def test_design_and_dependency_waivers_unlock_only_named_checks(self):
        self.a.approved()
        item = self.f.record()
        item["depends_on"] = ["B"]
        self.f.install(item)
        self.a.authorize()
        self.waive("design-review")
        self.assertIn("undelivered:B", self.a.state()["reasons"])
        self.waive("dependencies")
        self.assertEqual(self.a.state()["next_role"], "implementation")
        self.a.finish_execution(self.a.dispatch("implementation", "source-author"))
        self.assertEqual(self.a.state()["next_role"], "code-review")

    def test_implementation_skip_does_not_invent_review_or_acceptance(self):
        self.implement()
        self.waive("implementation-review")
        self.assertNotIn("review", self.f.record()["development"])
        self.assertEqual(self.a.state()["state"], "awaiting_acceptance")
        self.waive("human-acceptance")
        self.assertEqual(self.a.state()["state"], "accepted_awaiting_delivery")
        self.a.snapshot["tree"] = "e" * 40
        self.assertNotEqual(self.a.state()["state"], "accepted_awaiting_delivery")

    def test_requirement_only_design_skip_binds_first_development_base(self):
        self.assertIsNone(self.f.record()["development"])
        self.waive("design-review")
        stage = self.f.begin("development-start")
        self.assertEqual(self.f.finish(stage)["status"], "published")
        item = self.f.record()
        self.assertEqual(item["workflow"]["validation_waivers"]["design-review"]["base_commit"], item["development"]["base_commit"])
        self.assertTrue(workflow._validation_waived(runtime._working_files(self.root), item, "design-review"))
        self.assertEqual(autonomy.accept(self.root, "A", approval_source="User explicitly accepts this implementation",
                                         publish=self.f.publisher)["status"], "published")
        item = self.f.record()
        self.assertEqual(item["development"]["review"]["session"], item["development"]["author_session"])
        self.assertEqual(item["development"]["review"]["approval_kind"], "human_acceptance")
        workflow._implementation_approved(runtime._working_files(self.root), item, root=self.root)

    def test_delivery_verifications_can_be_explicitly_skipped(self):
        self.implement()
        autonomy.accept(self.root, "A", approval_source="User accepts current implementation", publish=self.f.publisher)
        self.waive("merge-verification")
        self.waive("delivery-evidence")
        self.f.fake_development.verify_merged = mock.Mock(side_effect=AssertionError("waived verification ran"))
        draft = self.f.begin("delivery-record", provenance="User explicitly declares A delivered")
        self.f.edit(draft, "Delivery declared by user; merge/evidence verification explicitly skipped.\n")
        self.assertEqual(self.f.finish(draft)["status"], "published")
        item = self.f.record()
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["delivery"]["evidence"], [])
        self.f.fake_development.verify_merged.assert_not_called()
        self.assertEqual(item["delivery"]["verification_waivers"]["delivery-evidence"]["result"], "skipped")
        self.f.write(self.root, ".project/business-instructions.md", "Later instructions do not erase a recorded delivery declaration.\n")
        self.assertEqual(runtime._validate_files(self.root, runtime._working_files(self.root)), [])


if __name__ == "__main__":
    unittest.main()
