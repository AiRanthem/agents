"""Applicability assessments preserve actual independent review and approval."""
import copy
import os
from pathlib import Path
import unittest
from unittest import mock

import project_autonomy as autonomy
import project_runtime as runtime
import project_workflow as workflow
import test_project_autonomy as autonomy_tests
import test_project_workflow as workflow_tests


class DesignReuseTest(unittest.TestCase):
    def setUp(self):
        self.f = workflow_tests.WorkflowTest("runTest")
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.root = self.f.a

    def update(self, operation="design-update", text="# Design\n\nPrecise behavior\n\nEquivalent wording.\n"):
        edit = self.f.begin(operation)
        self.f.edit(edit, text)
        self.assertEqual(self.f.finish(edit)["status"], "published")

    def assess(self, outcome="pass", publisher=None):
        edit = self.f.begin("design-reuse")
        self.f.edit(edit, "Compared original approved contract, assumptions and current complete inputs.\n")
        result = workflow.finish(self.root, edit["ticket"],
            options={"result": outcome, "provenance": "Actual owner comparison"},
            publish=publisher or self.f.publisher)
        return edit, result

    def test_equivalent_document_keeps_original_reviewer_approval_and_exact_guards(self):
        self.f.designed()
        old = copy.deepcopy(self.f.record()["design"])
        self.update()
        with self.assertRaises(runtime.ProjectError):
            workflow._approved(runtime._working_files(self.root), self.f.record())
        edit, result = self.assess()
        self.assertEqual(result["status"], "published", result)
        item = self.f.record()
        self.assertEqual(item["design"]["review"], old["review"])
        self.assertEqual(item["design"]["approval"]["source"], old["approval"]["source"])
        self.assertEqual(item["design"]["approval"]["original_user_approval"], old["approval"])
        self.assertEqual(edit["design_basis"]["review"], old["review"])
        self.assertIn("Precise behavior", "".join(row["content"] for row in edit["design_basis"]["read"]))
        self.assertNotIn("Equivalent wording", "".join(row["content"] for row in edit["design_basis"]["read"]))
        workflow._approved(runtime._working_files(self.root), item)
        self.f.write(self.root, "workitems/A/context.md", "A changed assumption\n")
        with self.assertRaises(runtime.ProjectError):
            workflow._approved(runtime._working_files(self.root), self.f.record())
        _, result = self.assess()
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record()["design"]["review"], old["review"])
        result = autonomy.authorize(self.root, items=["A"], approval_source="User advances the same reviewed contract", publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        captured = self.f.record()["workflow"]["autonomy"]["approved_contract"]
        self.assertEqual(captured["approval"], old["approval"])
        self.assertIn("Precise behavior", captured["spec"])
        self.assertNotIn("Equivalent wording", captured["spec"])

    def test_no_pass_waiver_and_author_reviewer_are_not_reusable(self):
        self.assertEqual(workflow.begin(self.root, "design-reuse", "A", publish=self.f.publisher)["status"], "blocked")
        waiver = self.f.begin("development-start", "B", skip_design_review=True, approval_source="User waives only initial design review")
        self.assertEqual(self.f.finish(waiver)["status"], "published")
        self.assertEqual(workflow.begin(self.root, "design-reuse", "B", publish=self.f.publisher)["status"], "blocked")
        self.f.designed()
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "reviewer"}):
            self.update("requirement-update", "Equivalent requirement phrasing\n")
        self.assertIn("reviewer", self.f.record()["workflow"]["design_authors"])
        self.assertEqual(workflow.begin(self.root, "design-reuse", "A", publish=self.f.publisher)["status"], "blocked")

    def test_known_independent_failure_cannot_resurrect_earlier_pass(self):
        self.f.designed()
        edit = self.f.begin("decision-record", approval_source="Actual unchanged user approval")
        self.assertEqual(self.f.finish(edit)["status"], "published")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "reviewer"}):
            review = self.f.begin("design-review")
            self.f.edit(review, "Blocking design finding requires independent recheck.\n")
            self.assertEqual(workflow.finish(self.root, review["ticket"],
                options={"result": "fail", "provenance": "Actual independent finding"}, publish=self.f.publisher)["status"], "published")
        self.update()
        self.assertNotIn("design_basis", self.f.record()["workflow"])
        self.assertEqual(workflow.begin(self.root, "design-reuse", "A", publish=self.f.publisher)["status"], "blocked")

    def test_stale_target_and_partially_published_report_are_rejected(self):
        self.f.designed()
        self.update()
        edit = self.f.begin("design-reuse")
        self.f.edit(edit, "Applicability assessment\n")
        self.f.write(self.root, "workitems/A/context.md", "Concurrent new context\n")
        stale = workflow.finish(self.root, edit["ticket"], options={"result": "pass", "provenance": "Old assessment"}, publish=self.f.publisher)
        self.assertEqual(stale["code"], "stale_evidence", stale)
        edit, partial = self.assess(publisher=lambda *args, **kwargs: {"status": "partial"})
        self.assertEqual(partial["status"], "partial", partial)
        self.f.edit(edit, "Changed report after publication began\n")
        result = workflow.resume(self.root, edit["ticket"], publish=self.f.publisher)
        self.assertEqual(result["status"], "blocked", result)
        self.assertIn("cannot be edited", result["message"])

    def test_partial_publication_resumes_the_exact_assessment(self):
        self.f.designed()
        self.update()
        edit, partial = self.assess(publisher=lambda *args, **kwargs: {"status": "partial"})
        self.assertEqual(partial["status"], "partial", partial)
        result = workflow.resume(self.root, edit["ticket"], publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(workflow.resume(self.root, edit["ticket"], publish=self.f.publisher)["status"], "no_op")
        workflow._approved(runtime._working_files(self.root), self.f.record())

    def test_formal_code_review_acknowledgement_retains_exact_design_coverage(self):
        self.f.designed()
        self.update()
        _, result = self.assess()
        self.assertEqual(result["status"], "published", result)
        item = self.f.record()
        files = runtime._working_files(self.root)
        pre = {"phase": "reconciling", "rebased": True, "generation": "a" * 32,
               "inputs": {}, "formal_base": "a" * 40,
               "rebase": {"generation": "b" * 32, "target": "a" * 40}}
        item["workflow"].setdefault("autonomy", {})["predevelopment"] = pre
        assessment = item["workflow"]["design_reuse"]
        assessment["target"]["binding"] = autonomy._binding(self.root, files, item, code=False)
        captured = copy.deepcopy(assessment)
        workflow._approved(files, item)
        pre["phase"] = "formal"
        workflow._approved(files, item)
        self.assertEqual(assessment, captured)
        for field, value in (("generation", "c" * 32), ("inputs", {"other": {"id": "changed"}}),
                             ("formal_base", "c" * 40), ("rebase", {"target": "c" * 40}),
                             ("rebased", False), ("phase", "speculative")):
            changed = copy.deepcopy(item)
            changed["workflow"]["autonomy"]["predevelopment"][field] = value
            with self.subTest(field=field), self.assertRaises(runtime.ProjectError):
                workflow._approved(files, changed)
        changed = copy.deepcopy(item)
        changed["development"]["base_commit"] = "c" * 40
        with self.assertRaises(runtime.ProjectError):
            workflow._approved(files, changed)

    def test_pending_comparison_requires_actual_independent_contract_confirmation(self):
        self.f.designed()
        original = self.f.record()["design"]["approval"]
        self.update()
        _, result = self.assess("fail")
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record()["design"]["approval"]["kind"], "derived_reuse_pending")
        blocked = workflow.begin(self.root, "development-start", "A", options={"skip_design_review": True, "approval_source": "Waive design review"}, publish=self.f.publisher)
        self.assertEqual(blocked["status"], "blocked", blocked)
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "reviewer"}):
            edit = self.f.begin("design-review")
            self.f.edit(edit, "Independent comparison confirms unchanged approved user contract.\n")
            options = {"result": "pass", "provenance": "Actual original independent reviewer"}
            self.assertEqual(workflow.finish(self.root, edit["ticket"], options=options, publish=self.f.publisher)["status"], "blocked")
            self.assertEqual(edit["design_basis"]["approval"], original)
            failure = workflow.finish(self.root, edit["ticket"], options={"result": "fail", "provenance": "Independent blocking finding"}, publish=self.f.publisher)
            self.assertEqual(failure["status"], "published", failure)
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "separate-author"}):
            self.update(text="# Design\n\nPrecise behavior; corrected internal explanation.\n")
        self.assertEqual(self.f.record()["design"]["approval"]["kind"], "derived_reuse_pending")
        self.assertEqual(workflow.begin(self.root, "design-reuse", "A", publish=self.f.publisher)["status"], "blocked")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "reviewer"}):
            edit = self.f.begin("design-review")
            self.assertEqual(edit["design_basis"]["approval"], original)
            self.f.edit(edit, "Separate author fixed the finding within the original approved contract.\n", "report.md")
            options = {"result": "pass", "provenance": "Actual original independent reviewer"}
            result = workflow.finish(self.root, edit["ticket"], options={**options, "contract_unchanged": True}, publish=self.f.publisher)
            self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record()["design"]["approval"]["original_user_approval"], original)
        workflow._approved(runtime._working_files(self.root), self.f.record())

    def test_first_independent_review_can_publish_declared_mechanical_correction(self):
        self.update(text="# Design\n\nPrecise behavor\n")
        approval = self.f.begin("decision-record", approval_source="User approves the precise behavior contract")
        self.f.edit(approval, "Approved precise behavior, including its established spelling.\n")
        self.assertEqual(self.f.finish(approval)["status"], "published")
        original = copy.deepcopy(self.f.record()["design"])
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "reviewer"}):
            edit = self.f.begin("design-review")
            self.f.edit(edit, "# Design\n\nPrecise behavior\n", "spec.md")
            self.f.edit(edit, "Corrected behavor to behavior as uniquely established in the approved requirement; contract unchanged.\n", "report.md")
            options = {"result": "pass", "provenance": "Actual independent typo correction"}
            self.assertEqual(workflow.finish(self.root, edit["ticket"], options=options, publish=self.f.publisher)["status"], "blocked")
            self.assertEqual(workflow.finish(self.root, edit["ticket"], options={**options, "mechanical_correction": True}, publish=self.f.publisher)["status"], "blocked")
            result = workflow.finish(self.root, edit["ticket"], options={**options, "mechanical_correction": True, "contract_unchanged": True}, publish=self.f.publisher)
            self.assertEqual(result["status"], "published", result)
        item = self.f.record()
        self.assertEqual(item["design"]["author_session"], original["author_session"])
        self.assertNotIn("reviewer", workflow._design_authors(item))
        self.assertEqual(item["design"]["review"]["session"], "reviewer")
        correction = item["design"]["review"]["mechanical_correction"]
        self.assertIn("-Precise behavor", correction["diff"])
        self.assertIn("+Precise behavior", correction["diff"])
        self.assertEqual(correction["original_binding"]["version"], original["version"])
        self.assertEqual(item["design"]["version"], original["version"] + 1)
        workflow._approved(runtime._working_files(self.root), item)
        result = autonomy.authorize(self.root, items=["A"], approval_source="User advances the independently corrected design", publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        captured = self.f.record()["workflow"]["autonomy"]["approved_contract"]
        self.assertEqual(captured["approval"]["kind"], "derived_mechanical")
        self.assertEqual(captured["spec"], "# Design\n\nPrecise behavior\n")

    def test_mechanical_candidate_is_not_applied_when_original_inputs_are_stale(self):
        self.f.designed()
        approval = self.f.begin("decision-record", approval_source="User confirms unchanged design")
        self.assertEqual(self.f.finish(approval)["status"], "published")
        original = (self.root / "workitems/A/spec.md").read_text()
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "reviewer"}):
            edit = self.f.begin("design-review")
            self.f.edit(edit, original + "\n", "spec.md")
            self.f.edit(edit, "Mechanical whitespace normalization; unchanged contract.\n", "report.md")
            self.f.write(self.root, "workitems/A/context.md", "Concurrent assumption change\n")
            result = workflow.finish(self.root, edit["ticket"], options={"result": "pass", "provenance": "Review", "mechanical_correction": True, "contract_unchanged": True}, publish=self.f.publisher)
            self.assertEqual(result["code"], "stale_evidence", result)
        self.assertEqual((self.root / "workitems/A/spec.md").read_text(), original)


class AutonomousDesignReuseTest(unittest.TestCase):
    def setUp(self):
        self.a = autonomy_tests.AutonomyTest("runTest")
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.f, self.root = self.a.f, self.a.root
        self.a.approved()
        self.a.authorize()
        self.a.finish_execution(self.a.dispatch("design-review", "original-reviewer"))

    def test_coordinator_can_assess_stale_inputs_without_new_user_approval(self):
        old = copy.deepcopy(self.f.record()["design"]["review"])
        edit = self.f.begin("design-update")
        self.f.edit(edit, "# Equivalent design\n\nApproved behavior and acceptance.\n")
        self.assertEqual(self.f.finish(edit)["status"], "published")
        self.assertEqual(self.a.state()["next_action"], "design_reuse_assessment")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "foreign-session"}):
            self.assertEqual(workflow.begin(self.root, "design-reuse", "A", publish=self.f.publisher)["status"], "blocked")
        edit = self.f.begin("design-reuse")
        self.f.edit(edit, "Original user contract and assumptions are unchanged.\n")
        self.assertEqual(workflow.finish(self.root, edit["ticket"], options={"result": "pass", "provenance": "Coordinator comparison"}, publish=self.f.publisher)["status"], "published")
        self.assertEqual(self.f.record()["design"]["review"], old)
        self.assertEqual(self.a.state()["next_role"], "implementation")
        execution = self.a.dispatch("implementation", "implementer")
        self.assertEqual(workflow.begin(self.root, "design-reuse", "A", publish=self.f.publisher)["status"], "blocked")
        self.a.finish_execution(execution)
        self.assertEqual(self.a.state()["next_role"], "code-review")

    def test_failed_assessment_schedules_independent_incremental_review(self):
        self.f.write(self.root, "workitems/A/context.md", "A critical assumption needs independent review\n")
        self.assertEqual(self.a.state()["next_action"], "design_reuse_assessment")
        edit = self.f.begin("design-reuse")
        self.f.edit(edit, "Cannot establish that the changed assumption retains coverage.\n")
        self.assertEqual(workflow.finish(self.root, edit["ticket"], options={"result": "fail", "provenance": "Changed assumption"}, publish=self.f.publisher)["status"], "published")
        self.assertEqual(self.a.state()["next_role"], "design-review")
        self.assertNotIn("next_action", self.a.state())
        self.a.finish_execution(self.a.dispatch("design-review", "original-reviewer"))
        self.assertEqual(self.a.state()["next_role"], "implementation")

    def test_changed_document_requires_independent_confirmation_without_reapproving_it(self):
        original = self.f.record()["workflow"]["autonomy"]["authorization"]
        edit = self.f.begin("requirement-update")
        self.f.edit(edit, "Equivalent requirement A wording\n")
        self.assertEqual(self.f.finish(edit)["status"], "published")
        edit = self.f.begin("design-reuse")
        self.f.edit(edit, "Uncertain equivalence; independent comparison required.\n")
        result = workflow.finish(self.root, edit["ticket"], options={"result": "fail", "provenance": "Owner uncertainty"}, publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record()["workflow"]["autonomy"]["authorization"], original)
        self.assertEqual(self.a.state()["next_role"], "design-review")
        review = self.a.dispatch("design-review", "original-reviewer")
        with self.assertRaisesRegex(runtime.ProjectError, "contract"):
            autonomy.result(self.root, "A", receipt=self.a.receipt(review), publish=self.f.publisher)
        self.a.finish_execution(review, "fail")
        self.assertEqual(self.a.state()["next_role"], "design-revision")
        revision = self.a.dispatch("design-revision", "separate-designer")
        candidate = self.f.directory / "pending-repair.md"
        candidate.write_text("# Internal correction\n\nApproved behavior and acceptance.\n")
        self.a.finish_execution(revision, "revised", candidate_file=str(candidate))
        self.assertEqual(workflow.begin(self.root, "design-reuse", "A", publish=self.f.publisher)["status"], "blocked")
        review = self.a.dispatch("design-review", "original-reviewer")
        self.a.finish_execution(review, contract_unchanged=True)
        self.assertEqual(self.a.state()["next_role"], "implementation")
        self.assertEqual(self.f.record()["workflow"]["autonomy"]["authorization"]["source"], original["source"])

    def test_active_source_change_stales_assessment_and_contract_change_discards_basis(self):
        edit = self.f.begin("design-reuse")
        self.f.edit(edit, "Compare baseline and assumptions.\n")
        self.a.snapshot["dirty_digest"] = "d" * 64
        result = workflow.finish(self.root, edit["ticket"], options={"result": "pass", "provenance": "Owner assessment"}, publish=self.f.publisher)
        self.assertEqual(result["code"], "stale_evidence", result)
        writer = self.a.dispatch("implementation", "implementer")
        self.a.finish_execution(writer, "contract-change")
        self.assertNotIn("design_basis", self.f.record()["workflow"])
        self.assertNotIn("design_reuse", self.f.record()["workflow"])
        self.assertEqual(self.a.state()["state"], "blocked")

    def test_failed_readonly_reviewer_can_recheck_a_separate_authors_revision(self):
        self.a.finish_execution(self.a.dispatch("implementation", "implementer"))
        # Use another item with an initial failed review rather than bypassing
        # the current pass or claiming that its reviewer edited the contract.
        self.a.approved("B")
        autonomy.authorize(self.root, items=["B"], approval_source="User advances B", publish=self.f.publisher)
        review = self.a.dispatch("design-review", "same-reviewer", "B")
        result = autonomy.result(self.root, "B", receipt=self.a.receipt(review, "fail"), publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        revision = self.a.dispatch("design-revision", "separate-designer", "B")
        candidate = self.f.directory / "separate-revision.md"
        candidate.write_text("# Revised internal design\n\nSame user contract; blocker repaired.\n")
        result = autonomy.result(self.root, "B", receipt=self.a.receipt(revision, "revised", candidate_file=str(candidate)), publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        review = self.a.dispatch("design-review", "same-reviewer", "B")
        result = autonomy.result(self.root, "B", receipt=self.a.receipt(review, contract_unchanged=True), publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record("B")["design"]["review"]["session"], "same-reviewer")

    def test_first_autonomous_review_mechanical_pass_keeps_actual_authors(self):
        self.a.approved("B")
        autonomy.authorize(self.root, items=["B"], approval_source="User advances B", publish=self.f.publisher)
        original = copy.deepcopy(self.f.record("B")["design"])
        review = self.a.dispatch("design-review", "mechanical-reviewer", "B")
        candidate = self.f.directory / "mechanical.md"
        candidate.write_text("# Design\n\nApproved behavior and acceptance.\n\n")
        with self.assertRaisesRegex(runtime.ProjectError, "candidate"):
            autonomy.result(self.root, "B", receipt=self.a.receipt(review, candidate_file=str(candidate)), publish=self.f.publisher)
        receipt = self.a.receipt(review, candidate_file=str(candidate), mechanical_correction=True, contract_unchanged=True)
        result = autonomy.result(self.root, "B", receipt=receipt, publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        item = self.f.record("B")
        self.assertEqual(item["design"]["author_session"], original["author_session"])
        self.assertNotIn("mechanical-reviewer", workflow._design_authors(item))
        self.assertEqual(item["design"]["review"]["execution"], review["attempt"])
        self.assertEqual(item["workflow"]["autonomy"]["executions"][review["attempt"]]["input_binding"], review["input_binding"])
        workflow._approved(runtime._working_files(self.root), item)
        self.assertEqual(self.a.state("B")["next_role"], "implementation")


if __name__ == "__main__":
    unittest.main()
