"""Explicit user decisions replace verification gates without inventing reviews."""
import os
import unittest
from unittest import mock

import project
import project_autonomy as autonomy
import project_runtime as runtime
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

    def test_human_acceptance_keeps_design_gate_and_allows_later_session(self):
        self.implement()
        item = self.f.record()
        item["design"]["review"]["result"] = "fail"
        self.f.install(item)
        with self.assertRaisesRegex(runtime.ProjectError, "design"):
            autonomy.accept(self.root, "A", approval_source="User accepts implementation", publish=self.f.publisher)
        self.waive("design-review")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "later-session"}):
            result = autonomy.accept(self.root, "A", approval_source="User accepts implementation", publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record()["workflow"]["autonomy"]["acceptance"]["recorded_by"], "later-session")

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
        workflow._implementation_approved(runtime._working_files(self.root), item)

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
