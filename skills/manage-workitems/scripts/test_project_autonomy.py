"""Advancement contracts exercised through persisted workflow checkpoints."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import project_autonomy as autonomy
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_workflow as workflow_tests


class AutonomyTest(unittest.TestCase):
    def setUp(self):
        # Reuse the workspace, guarded publisher and development adapter without
        # inheriting (and rerunning) the ordinary workflow test methods.
        self.f = workflow_tests.WorkflowTest("runTest")
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.root = self.f.a
        self.snapshot = {"head": "a" * 40, "tree": "b" * 40,
                         "dirty_digest": "c" * 64, "clean": False}
        self.f.fake_development.snapshot = lambda *args: copy.deepcopy(self.snapshot)

    def approved(self, identifier="A"):
        draft = self.f.begin("design-update", identifier)
        self.f.edit(draft, "# Design\n\nApproved behavior and acceptance.\n")
        self.assertEqual(self.f.finish(draft)["status"], "published")
        approval = self.f.begin("decision-record", identifier,
                                approval_source="User approves this initial requirement and design")
        self.f.edit(approval, "Keep the approved interface and acceptance.\n")
        self.assertEqual(self.f.finish(approval)["status"], "published")

    def authorize(self, **options):
        result = autonomy.authorize(self.root, items=["A"],
                                    approval_source="User requests autonomous advancement of A",
                                    publish=self.f.publisher, **options)
        self.assertEqual(result["status"], "published", result)

    def state(self, identifier="A"):
        return autonomy.status(self.root, items=[identifier])["items"][0]

    def dispatch(self, role, worker, identifier="A"):
        result = autonomy.dispatch(self.root, identifier, role=role,
            receipt={"host": "codex", "tool": "spawn_agent", "call_id": "spawn-" + worker,
                     "worker_id": worker, "raw": {"agent_id": worker}},
            publish=self.f.publisher)
        self.assertEqual(result["status"], "ready", result)
        return result

    def receipt(self, execution, outcome="pass", **changes):
        report = self.f.directory / (execution["attempt"] + "-report.md")
        report.write_text("Actual worker report covering the current original artifacts.\n")
        return {"host": "codex", "tool": "wait_agent", "call_id": "wait-" + execution["attempt"],
                "raw": {"arguments": {"target": execution["worker_id"]},
                        "result": {"worker_status": "completed"}}, "worker_id": execution["worker_id"],
                "attempt": execution["attempt"], "role": execution["role"],
                "input_binding": copy.deepcopy(execution["input_binding"]), "outcome": outcome,
                "terminal_status": "completed", "descendants_stopped": True,
                "report_file": str(report), **changes}

    def finish_execution(self, execution, outcome="pass", **changes):
        result = autonomy.result(self.root, "A", receipt=self.receipt(execution, outcome, **changes),
                                 publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        return result

    def reviewed(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        self.finish_execution(self.dispatch("code-review", "code-reviewer"))

    def test_status_does_not_create_a_coordinator_identity(self):
        with mock.patch.object(workflow, "_identity", side_effect=AssertionError("status created an identity")):
            result = autonomy.status(self.root, items=["A"])
        self.assertEqual(result["blocked"], ["A"])
        self.assertFalse((self.root / ".project-local").exists())

    def test_scope_uses_explicit_hierarchy_and_does_not_add_dependencies(self):
        item = self.f.record("B")
        item["split_from"] = "A"
        self.f.install(item)
        files = runtime._working_files(self.root)
        self.assertEqual(autonomy.scope(files, tree="A"), ["A", "B"])
        self.assertEqual(autonomy.scope(files, items=["A", "A"]), ["A"])
        self.assertEqual(autonomy.scope(files, all_items=True), ["A", "B"])
        for options in ({}, {"all_items": True, "items": ["A"]}, {"tree": "missing"}):
            with self.subTest(options=options), self.assertRaises(runtime.ProjectError):
                autonomy.scope(files, **options)

    def test_unavailable_worktree_blocks_only_its_item(self):
        self.reviewed()
        self.approved("B")
        autonomy.authorize(self.root, items=["B"], approval_source="User advances B",
                           publish=self.f.publisher)
        self.f.fake_development.worktree_location = lambda root, item, project: self.f.directory / item["id"]
        for failure in (runtime.ProjectError("recorded source worktree is missing"),
                        OSError("source instructions are unreadable")):
            def snapshot(location):
                if location.name == "A":
                    raise failure
                return copy.deepcopy(self.snapshot)

            with self.subTest(failure=type(failure).__name__), mock.patch.object(
                    self.f.fake_development, "snapshot", side_effect=snapshot):
                result = autonomy.status(self.root, all_items=True)
                self.assertEqual(result["blocked"], ["A"])
                self.assertEqual(result["ready"], ["B"])
                self.assertFalse(result["round_finished"])
                blocked = next(entry for entry in result["items"] if entry["id"] == "A")
                self.assertEqual(blocked["reasons"], ["input_unavailable"])
                self.assertEqual(blocked["error"], str(failure))

    def test_dependency_requires_delivery_and_acceptance_and_open_fix_still_blocks(self):
        self.approved()
        item = self.f.record()
        item["depends_on"] = ["B"]
        self.f.install(item)
        dependency = self.f.record("B")
        dependency["kind"] = "aggregate"
        dependency["repository"] = None
        self.f.install(dependency)
        self.authorize()
        self.assertEqual(autonomy.status(self.root, items=["A"])["blocked"], ["A"])
        self.assertIn("undelivered:B", self.state()["reasons"])
        self.assertIn("unaccepted:B", self.state()["reasons"])
        dependency = self.f.record("B")
        dependency.update(status="done", delivery={"required": ["merged"], "status": "delivered",
                          "evidence": [{"kind": "merged", "reference": "actual merge"}]})
        self.f.install(dependency)
        self.assertEqual(self.state()["reasons"], ["unaccepted:B"])
        self.assertEqual(autonomy.accept(self.root, "B", approval_source="User accepts B",
                                         publish=self.f.publisher)["status"], "published")
        self.assertEqual(self.state()["next_role"], "design-review")
        fix = self.f.begin("fix", None, fixes="B", title="上游修复", slug="upstream-fix", repository="code")
        self.f.edit(fix, "Repair the delivered prerequisite.\n", "requirement.md")
        self.assertEqual(self.f.finish(fix)["status"], "published")
        self.assertIn("open_fix:1-upstream-fix", self.state()["reasons"])
        self.assertEqual([entry["id"] for entry in autonomy.status(self.root, items=["A"])["items"]], ["A"])

    def test_aggregate_is_not_scheduled_as_a_code_stage(self):
        item = self.f.record()
        item.update(kind="aggregate", repository=None)
        self.f.install(item)
        self.authorize()
        self.assertEqual(self.state()["reasons"], ["aggregate_manual_acceptance"])
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("implementation", "implementer")

    def test_advancement_authorization_does_not_invent_initial_design_approval(self):
        self.authorize(skip_design_review=True)
        self.assertIn("approved_initial_design_required", self.state()["reasons"])
        self.assertNotIn("approval", self.f.record()["design"])
        self.approved()
        self.authorize(skip_design_review=True)
        execution = self.dispatch("implementation", "implementer")
        self.assertEqual(execution["role"], "implementation")
        waiver = self.f.record()["workflow"]["design_waiver"]
        self.assertIn("User requests autonomous advancement", waiver["source"])

    def test_current_approved_draft_after_prior_failed_review_can_advance(self):
        self.approved()
        original_approval = copy.deepcopy(self.f.record()["design"]["approval"])
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "prior-reviewer"}):
            review = self.f.begin("design-review")
            self.f.edit(review, "Implementation details require independent reconsideration.\n")
            result = workflow.finish(self.root, review["ticket"],
                options={"result": "fail", "provenance": "Actual prior independent review"},
                publish=self.f.publisher)
            self.assertEqual(result["status"], "published", result)
        self.assertEqual(self.f.record()["design"]["state"], "draft")
        self.assertEqual(self.f.record()["design"]["approval"], original_approval)
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "ordinary-reviewer"}):
            blocked = workflow.begin(self.root, "design-review", "A", publish=self.f.publisher)
            self.assertEqual(blocked["action_code"], "approval_required")
        self.authorize()
        self.assertEqual(self.state()["next_role"], "design-review")
        execution = self.dispatch("design-review", "fresh-autonomous-reviewer")
        self.assertFalse(execution["worker_paused"])
        self.finish_execution(execution)
        self.assertEqual(self.f.record()["design"]["state"], "implementable")
        self.assertEqual(self.f.record()["design"]["approval"], original_approval)

    def test_result_identity_attempt_role_and_report_are_required(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "design-reviewer")
        receipt = self.receipt(execution)
        for change in ({"worker_id": "other-worker"}, {"role": "code-review"},
                       {"attempt": "0" * 32}, {"host": "other-host"},
                       {"input_binding": {}}, {"raw": {}},
                       {"raw": {"arguments": {"target": "wrong-worker"}, "result": {"worker_status": "completed"}}},
                       {"report_file": "missing-report"}):
            with self.subTest(change=change), self.assertRaises(runtime.ProjectError):
                autonomy.result(self.root, "A", receipt={**receipt, **change}, publish=self.f.publisher)
            self.assertEqual(self.state()["state"], "running")
        without_call_id = dict(receipt)
        without_call_id.pop("call_id")
        finished = autonomy.result(self.root, "A", receipt=without_call_id, publish=self.f.publisher)
        self.assertEqual(finished["status"], "published", finished)
        review = self.f.record()["design"]["review"]
        self.assertEqual(review["session"], "design-reviewer")
        self.assertEqual(review["recorded_by"], "author")
        with self.assertRaises(runtime.ProjectError):
            autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)

    def test_running_executor_blocks_redispatch_and_other_coordinator_takeover(self):
        self.approved()
        self.authorize()
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "new-coordinator"}):
            mixed = autonomy.authorize(self.root, all_items=True, approval_source="User resumes project",
                                       publish=self.f.publisher)
            self.assertEqual(mixed["authorized"], ["B"])
            self.assertEqual(mixed["blocked_items"][0]["id"], "A")
            self.assertNotIn("current", self.f.record()["workflow"]["autonomy"])
        self.dispatch("design-review", "design-reviewer")
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("design-review", "duplicate-reviewer")
        unchanged = copy.deepcopy(self.f.record()["workflow"]["autonomy"])
        renewal = autonomy.authorize(self.root, items=["A"], approval_source="User resumes A",
                                     publish=self.f.publisher)
        self.assertEqual(renewal["authorized"], [])
        self.assertEqual(renewal["blocked_items"][0]["id"], "A")
        self.assertEqual(self.f.record()["workflow"]["autonomy"], unchanged)
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "new-coordinator"}):
            self.assertIn("unknown_owner_liveness", self.state()["reasons"])
            observed = autonomy.status(self.root, items=["A"])
            self.assertEqual(observed["running"], ["A"])
            self.assertFalse(observed["round_finished"])
            self.assertEqual(observed["items"][0]["attempt"], unchanged["current"])
            mixed = autonomy.authorize(self.root, all_items=True, approval_source="User resumes project",
                                       publish=self.f.publisher)
            self.assertEqual(mixed["authorized"], ["B"])
            self.assertEqual(mixed["blocked_items"][0]["id"], "A")
        self.assertFalse(autonomy.status(self.root, items=["A"])["round_finished"])

    def test_result_requires_observed_termination_and_descendant_cleanup(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "live-reviewer")
        receipt = self.receipt(execution)
        invalid = [
            {**receipt, "raw": {"agent_id": execution["worker_id"]}},
            {key: value for key, value in receipt.items() if key != "terminal_status"},
            {**receipt, "terminal_status": "running"},
            {**receipt, "descendants_stopped": False},
            {**receipt, "raw": {"worker_id": execution["worker_id"], "status": "running"}},
            {**receipt, "terminal_status": "failed", "raw": {"worker_id": execution["worker_id"], "status": "failed"}},
        ]
        for value in invalid:
            with self.subTest(receipt=value), self.assertRaises(runtime.ProjectError):
                autonomy.result(self.root, "A", receipt=value, publish=self.f.publisher)
            state = self.f.record()["workflow"]["autonomy"]
            self.assertEqual(state["current"], execution["attempt"])
            self.assertNotIn("result", state["executions"][execution["attempt"]])
        self.assertEqual(autonomy.result(self.root, "A", receipt=receipt,
                                        publish=self.f.publisher)["status"], "published")

    def test_captured_review_rejects_changed_report_and_forged_pass(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "design-reviewer")
        receipt = self.receipt(execution, "fail")
        # Interrupt between result capture and its ordinary workflow checkpoint,
        # then exercise the checkpoint with a modified draft or invented verdict.
        with mock.patch.object(workflow, "finish", return_value={"status": "blocked", "code": "test_interruption"}):
            captured = autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)
        self.assertEqual(captured["code"], "test_interruption")
        record = self.f.record()
        entry = record["workflow"]["autonomy"]["executions"][execution["attempt"]]
        checkpoint = autonomy._stage_ticket(self.root, runtime._working_files(self.root), record, entry)
        self.assertEqual(checkpoint["status"], "ready", checkpoint)
        self.f.edit(checkpoint, "Coordinator rewrote the worker report.\n")
        changed = workflow.finish(self.root, checkpoint["ticket"],
                                  options={"result": "fail", "provenance": receipt["call_id"]},
                                  publish=self.f.publisher)
        self.assertEqual(changed["status"], "blocked")
        self.assertIn("captured", changed["message"])
        self.f.edit(checkpoint, Path(receipt["report_file"]).read_text(encoding="utf-8"))
        forged = workflow.finish(self.root, checkpoint["ticket"],
                                 options={"result": "pass", "provenance": receipt["call_id"]},
                                 publish=self.f.publisher)
        self.assertEqual(forged["status"], "blocked")
        self.assertIn("captured", forged["message"])
        self.assertNotEqual(self.f.record()["design"]["state"], "implementable")

    def test_design_author_and_implementation_repair_authors_cannot_self_review(self):
        self.approved()
        self.authorize()
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("design-review", "author")
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("code-review", "implementer")
        self.finish_execution(self.dispatch("code-review", "code-reviewer"), "fail")
        self.assertEqual(self.state()["next_role"], "fix")
        self.finish_execution(self.dispatch("fix", "repairer"))
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("code-review", "repairer")
        self.finish_execution(self.dispatch("code-review", "independent-recheck"))
        self.assertEqual(self.state()["state"], "awaiting_acceptance")
        self.assertEqual(self.f.record()["delivery"]["status"], "pending")

    def test_review_result_is_stale_after_dirty_code_or_contract_changes(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "design-reviewer")
        receipt = self.receipt(execution)
        self.f.write(self.root, "workitems/A/requirement.md", "Changed approved contract.\n")
        with self.assertRaisesRegex(runtime.ProjectError, "stale"):
            autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)
        self.f.write(self.root, "workitems/A/requirement.md", "Requirement A\n")
        self.finish_execution(execution)
        writer = self.dispatch("implementation", "implementer")
        self.snapshot["dirty_digest"] = "d" * 64
        self.finish_execution(writer)  # Writer results may change their dirty code.
        reviewer = self.dispatch("code-review", "code-reviewer")
        self.snapshot["dirty_digest"] = "e" * 64
        with self.assertRaisesRegex(runtime.ProjectError, "stale"):
            autonomy.result(self.root, "A", receipt=self.receipt(reviewer), publish=self.f.publisher)
        self.assertEqual(self.state()["state"], "running")

    def test_design_revision_keeps_user_approval_but_requires_a_new_independent_reviewer(self):
        self.approved()
        original = self.f.record()
        original["design"]["author_session"] = "initial-designer"
        self.f.install(original)
        self.authorize()
        revision = self.dispatch("design-review", "design-editor")
        candidate = self.f.directory / "candidate.md"
        candidate.write_text("# Revised internal design\n\nThe approved interface remains unchanged.\n")
        self.finish_execution(revision, "revised", candidate_file=str(candidate))
        record = self.f.record()
        self.assertEqual(record["design"]["state"], "review-pending")
        self.assertEqual(record["design"]["author_session"], "design-editor")
        self.assertEqual(record["design"]["approval"]["kind"], "derived_revision")
        self.assertEqual(record["design"]["approval"]["original_user_approval"]["kind"], "user")
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("design-review", "design-editor")
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("design-review", "initial-designer")
        reviewer = self.dispatch("design-review", "fresh-design-reviewer")
        self.assertEqual(reviewer["approved_contract"]["requirement"], "Requirement A\n")
        self.assertEqual(reviewer["approved_contract"]["spec"], "# Design\n\nApproved behavior and acceptance.\n")
        self.assertEqual(reviewer["approved_contract"]["approval"]["kind"], "user")
        with self.assertRaisesRegex(runtime.ProjectError, "contract"):
            autonomy.result(self.root, "A", receipt=self.receipt(reviewer), publish=self.f.publisher)
        self.finish_execution(reviewer, contract_unchanged=True)
        self.assertEqual(self.state()["next_role"], "implementation")

    def test_acceptance_is_distinct_from_review_and_code_changes_require_reacceptance(self):
        self.reviewed()
        self.assertEqual(self.state()["state"], "awaiting_acceptance")
        report = self.f.directory / "unbound-review.md"
        report.write_text("A report without a dispatched execution cannot establish review.\n")
        for operation in ("design-review", "development-start", "development-finish"):
            options = {"result": "pass", "provenance": "manual registration",
                       "reviewer_session": "unbound-reviewer", "review_file": str(report)} if operation == "development-finish" else {}
            with self.subTest(operation=operation):
                unbound = workflow.begin(self.root, operation, "A", options=options, publish=self.f.publisher)
                self.assertEqual(unbound["status"], "blocked", unbound)
                self.assertIn("execution", unbound["message"])
        self.assertTrue(autonomy.status(self.root, items=["A"])["round_finished"])
        self.assertEqual(autonomy.accept(self.root, "A", approval_source="User inspected and accepts A",
                                         publish=self.f.publisher)["status"], "published")
        self.assertEqual(self.state()["state"], "accepted_awaiting_delivery")
        self.assertNotEqual(self.f.record()["status"], "done")
        self.snapshot["dirty_digest"] = "f" * 64
        self.snapshot["tree"] = "f" * 40
        with self.assertRaises(runtime.ProjectError):
            autonomy.accept(self.root, "A", approval_source="Old acceptance cannot cover changes",
                            publish=self.f.publisher)
        self.authorize()
        self.assertEqual(self.state()["next_role"], "code-review")
        self.finish_execution(self.dispatch("code-review", "updated-code-reviewer"))
        self.assertEqual(self.state()["state"], "awaiting_acceptance")

    def test_delivered_cleaned_item_can_record_acceptance_without_losing_live_read_guards(self):
        code = self.f.directory / "fake-code"
        code.mkdir()
        (code / "AGENTS.md").write_text("Code instructions at review.\n")
        ancestor = self.f.directory / "AGENTS.md"
        ancestor.write_text("Ancestor instructions at review.\n")
        self.reviewed()
        autonomy.accept(self.root, "A", approval_source="User accepts the reviewed source",
                        publish=self.f.publisher)
        delivery = self.f.begin("delivery-record", kind=["merged"], reference=["actual merge"],
                                provenance="Verified real delivery")
        self.f.edit(delivery, "The reviewed change is delivered.\n")
        self.assertEqual(self.f.finish(delivery)["status"], "published")
        (code / "AGENTS.md").unlink()
        code.rmdir()
        cleanup = self.f.begin("cleanup-record", cleanup_status="done", mode="verify",
                               reference="Recorded code worktree removed")
        self.assertEqual(self.f.finish(cleanup)["status"], "published")
        item = self.f.record()
        item["workflow"]["autonomy"].pop("acceptance")
        self.f.install(item)  # A previously delivered item with no structured acceptance.
        downstream = self.f.record("B")
        downstream["depends_on"] = ["A"]
        self.f.install(downstream)
        self.approved("B")
        autonomy.authorize(self.root, items=["B"], approval_source="User advances B",
                           publish=self.f.publisher)
        self.assertIn("unaccepted:A", self.state("B")["reasons"])
        with self.subTest(guard="cleanup record required"):
            invalid = copy.deepcopy(item)
            invalid["workflow"].pop("cleanup_record")
            self.f.install(invalid)
            with self.assertRaises(runtime.ProjectError):
                autonomy.accept(self.root, "A", approval_source="User accepts delivered A",
                                publish=self.f.publisher)
            self.f.install(item)
        for path in (ancestor, self.root / "AGENTS.md"):
            with self.subTest(guard=str(path)):
                original = path.read_bytes() if path.exists() else None
                path.write_text("Changed instructions invalidate the review.\n")
                with self.assertRaises(runtime.ProjectError):
                    autonomy.accept(self.root, "A", approval_source="User accepts delivered A",
                                    publish=self.f.publisher)
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        with mock.patch.object(self.f.fake_development, "snapshot", side_effect=AssertionError("removed source must not be read")):
            self.assertEqual(autonomy.accept(self.root, "A", approval_source="User confirms historical acceptance",
                                            publish=self.f.publisher)["status"], "published")
        self.assertEqual(self.f.record()["status"], "done")
        self.assertEqual(self.state("B")["next_role"], "design-review")
        self.assertFalse(code.exists())

    def test_contract_change_stops_only_affected_work_and_does_not_renew_user_approval(self):
        self.approved()
        self.approved("B")
        autonomy.authorize(self.root, all_items=True, approval_source="User requests A and B",
                           publish=self.f.publisher)
        self.finish_execution(self.dispatch("design-review", "design-reviewer"), "contract-change")
        self.assertIn("user_contract_decision_required", self.state()["reasons"])
        self.assertNotIn("approval", self.f.record()["design"])
        self.assertEqual(self.state("B")["next_role"], "design-review")
        self.authorize()
        self.assertIn("approved_initial_design_required", self.state()["reasons"])

    def _unpublished_result(self, execution, receipt):
        # Exercise the actual retained journal path: fail fetch before any push,
        # rather than publishing the item and only then returning partial.
        import project
        self.f.commit("stable pre-capture authority")
        with mock.patch.object(runtime, "_fetch_selected", side_effect=runtime.ProjectError("git fetch Broken pipe")):
            response = autonomy.result(self.root, "A", receipt=receipt, publish=project.publish_changes)
        self.assertEqual(response["status"], "partial", response)
        self.assertTrue(response["stage_result_pending"])
        self.assertTrue(response["worker_paused"])
        self.assertNotIn("result", self.f.record()["workflow"]["autonomy"]["executions"][execution["attempt"]])
        return response

    def test_resume_recovers_first_capture_failure_without_report_or_redispatch(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        execution = self.dispatch("code-review", "code-reviewer")
        receipt = self.receipt(execution)
        report = Path(receipt["report_file"]).read_text()
        response = self._unpublished_result(execution, receipt)
        journal = response["recovery"]["journal"]
        Path(receipt["report_file"]).unlink()
        with mock.patch.object(autonomy, "_continue_dispatch", side_effect=AssertionError("completed worker re-dispatched")):
            resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
        self.assertEqual(resumed["status"], "published", resumed)
        self.assertEqual(runtime.publication_disposition(runtime.read_json(journal)), "rejected_before_push")
        state = self.f.record()["workflow"]["autonomy"]
        saved = state["executions"][execution["attempt"]]
        self.assertEqual(saved["worker_id"], execution["worker_id"])
        self.assertEqual(saved["result"], receipt)
        self.assertEqual(saved["report"]["body"], report)
        self.assertEqual(self.state()["state"], "awaiting_acceptance")
        self.assertEqual(autonomy.resume(self.root, "A", attempt=execution["attempt"],
                                        publish=self.f.publisher)["outcome"], "execution_completed")

    def test_first_capture_failure_preserves_revised_candidate_bytes(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "design-editor")
        candidate = self.f.directory / "candidate.md"
        candidate.write_text("# Design\nContract-preserving clarified design.\n")
        receipt = self.receipt(execution, "revised", candidate_file=str(candidate))
        self._unpublished_result(execution, receipt)
        Path(receipt["report_file"]).unlink()
        candidate.unlink()
        resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
        self.assertEqual(resumed["status"], "published", resumed)
        self.assertIn("clarified design", (self.root / "workitems/A/spec.md").read_text())
        self.assertEqual(self.state()["next_role"], "design-review")

    def test_pending_result_never_republishes_an_uncertain_journal(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "reviewer")
        receipt = self.receipt(execution)
        response = self._unpublished_result(execution, receipt)
        journal = response["recovery"]["journal"]
        before = len(self.f.calls)
        blocked = {"status": "blocked", "code": "publication_remote_outcome_unknown", "journal": journal}
        with mock.patch.object(runtime, "resume_publication", return_value=blocked) as recover:
            resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
        self.assertTrue(resumed["stage_result_pending"])
        self.assertTrue(resumed["worker_paused"])
        recover.assert_called_once_with(self.root, session="author",
                                       token=workflow._identity(self.root)["token"], journal=journal)
        self.assertEqual(len(self.f.calls), before)
        repeated = autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)
        self.assertEqual(repeated["code"], blocked["code"])
        self.assertEqual(len(self.f.calls), before)

    def test_resume_checks_unlinked_publication_after_capture_process_interruption(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "reviewer")
        self._unpublished_result(execution, self.receipt(execution))
        directory = autonomy._capture_directory(self.root, execution["attempt"])
        saved = workflow._load_manifest(self.root, directory)
        saved.pop("publication")
        autonomy._save_capture(self.root, execution["attempt"], saved)
        before = len(self.f.calls)
        blocked = {"status": "blocked", "code": "publication_journal_ambiguous"}
        with mock.patch.object(runtime, "resume_publication", return_value=blocked) as recover:
            resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
        recover.assert_called_once_with(self.root, session="author", token=workflow._identity(self.root)["token"],
                                        expected_write_hashes=saved["capture_write_hashes"])
        self.assertEqual(resumed["code"], "publication_journal_ambiguous")
        self.assertTrue(resumed["worker_paused"])
        self.assertEqual(len(self.f.calls), before)

    def test_unlinked_capture_rejects_an_unrelated_owned_publication(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "reviewer")
        response = self._unpublished_result(execution, self.receipt(execution))
        directory = autonomy._capture_directory(self.root, execution["attempt"])
        saved = workflow._load_manifest(self.root, directory)
        saved.pop("publication")
        autonomy._save_capture(self.root, execution["attempt"], saved)
        journal = Path(response["recovery"]["journal"])
        state = runtime.read_json(journal)
        state["state"] = "prepared"
        runtime._write_journal(journal, state)
        bundle_path = Path(state["bundle"])
        bundle = runtime.read_json(bundle_path)
        original_bundle = copy.deepcopy(bundle)
        name = next(iter(saved["capture_write_hashes"]))
        bundle["writes"][name] += "\n# unrelated saved operation\n"
        runtime._write_journal(bundle_path, bundle)
        before = journal.read_bytes()
        with mock.patch.object(runtime, "_fetch_selected", side_effect=AssertionError("unrelated intent recovered")):
            for _ in range(2):
                resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
                self.assertEqual(resumed["code"], "publication_intent_mismatch")
                self.assertTrue(resumed["worker_paused"])
        self.assertEqual(journal.read_bytes(), before)
        runtime._write_journal(bundle_path, original_bundle)
        matching = runtime.resume_publication(self.root, session="author", token=saved["identity"]["token"],
                                              journal=journal, expected_write_hashes=saved["capture_write_hashes"])
        self.assertEqual(matching["code"], "publication_candidate_missing")

    def test_retained_result_is_immutable_and_revalidates_current_reads(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "reviewer")
        receipt = self.receipt(execution, "fail")
        self._unpublished_result(execution, receipt)
        with self.assertRaisesRegex(runtime.ProjectError, "immutable"):
            autonomy.result(self.root, "A", receipt={**receipt, "outcome": "pass"}, publish=self.f.publisher)
        before = len(self.f.calls)
        (self.root / "AGENTS.md").write_text("Changed instructions\n")
        with self.assertRaisesRegex(runtime.ProjectError, "read source.*stale"):
            autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
        self.assertEqual(len(self.f.calls), before)

    def test_retained_result_checkpoint_rejects_tampering(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "reviewer")
        self._unpublished_result(execution, self.receipt(execution))
        path = autonomy._capture_directory(self.root, execution["attempt"]) / "manifest.yaml"
        path.write_text(path.read_text().replace("outcome: pass", "outcome: fail"))
        with self.assertRaisesRegex(runtime.ProjectError, "manifest was modified"):
            autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)

    def test_same_code_review_result_resumes_after_checkpoint_interruption(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        execution = self.dispatch("code-review", "code-reviewer")
        receipt = self.receipt(execution)
        with mock.patch.object(workflow, "finish", return_value={"status": "blocked", "code": "test_interruption"}):
            interrupted = autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)
        self.assertEqual(interrupted["code"], "test_interruption")
        self.assertTrue(interrupted["stage_result_pending"])
        self.assertIn("autonomy resume A", interrupted["continuation_command"])
        self.assertIn(execution["attempt"], interrupted["continuation_command"])
        ticket = self.f.record()["workflow"]["autonomy"]["executions"][execution["attempt"]]["result_ticket"]
        Path(receipt["report_file"]).unlink()
        resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
        self.assertEqual(resumed["status"], "published", resumed)
        record = self.f.record()
        self.assertEqual(record["workflow"]["autonomy"]["executions"][execution["attempt"]]["result_ticket"], ticket)
        self.assertEqual(record["development"]["review"]["session"], "code-reviewer")
        self.assertEqual(self.state()["state"], "awaiting_acceptance")

    def test_revised_candidate_resumes_after_workflow_publication_before_finalization(self):
        self.approved()
        self.authorize()
        execution = self.dispatch("design-review", "design-editor")
        candidate = self.f.directory / "recoverable-candidate.md"
        candidate.write_text("# Internal revision\n\nPreserve the approved external contract.\n")
        receipt = self.receipt(execution, "revised", candidate_file=str(candidate))

        def interrupt_finalization(root, writes, identity, message, checks=None):
            if message == "Complete execution A":
                return {"status": "partial"}
            return self.f.publisher(root, writes, identity, message, checks)

        interrupted = autonomy.result(self.root, "A", receipt=receipt, publish=interrupt_finalization)
        self.assertEqual(interrupted["status"], "partial", interrupted)
        version = self.f.record()["design"]["version"]
        self.assertEqual((self.root / "workitems/A/spec.md").read_text(), candidate.read_text())
        captured_candidate = candidate.read_text()
        candidate.unlink()
        Path(receipt["report_file"]).unlink()
        resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
        self.assertEqual(resumed["status"], "published", resumed)
        self.assertEqual(self.f.record()["design"]["version"], version)
        self.assertEqual((self.root / "workitems/A/spec.md").read_text(), captured_candidate)
        self.assertEqual(self.state()["next_role"], "design-review")

    def test_ordinary_development_still_requires_its_explicit_review_or_waiver(self):
        blocked = workflow.begin(self.root, "development-start", "A", publish=self.f.publisher)
        self.assertEqual(blocked["status"], "blocked")
        self.assertNotIn("autonomy", self.f.record().get("workflow", {}))
        start = self.f.begin("development-start", skip_design_review=True,
                            approval_source="User explicitly waives review for ordinary development")
        self.assertEqual(self.f.finish(start)["status"], "published")
        self.assertEqual(self.f.record()["development"]["author_session"], "author")

    def test_real_cli_retains_dirty_source_and_publishes_only_project_records(self):
        self.approved()
        git = workflow_tests.fixtures.git
        code_remote = self.f.directory / "cli-code.git"
        code_remote.mkdir()
        git(code_remote, "init", "--bare", "--initial-branch=main", "--quiet")
        code = self.f.directory / "cli-code"
        code.mkdir()
        git(code, "init", "--initial-branch=main", "--quiet")
        self.f.configure(code)
        (code / "program.py").write_text("answer = 1\n")
        (code / "AGENTS.md").write_text("Keep the approved behavior and validate changes.\n")
        git(code, "add", ".")
        git(code, "commit", "--quiet", "-m", "code baseline")
        git(code, "remote", "add", "upstream", str(code_remote))
        git(code, "push", "--quiet", "-u", "upstream", "main")
        source_head = git(code, "rev-parse", "HEAD")
        source_refs = git(code_remote, "show-ref")
        record = self.f.record()
        record.update(development=None, cleanup="not_applicable")
        self.f.project["repositories"] = [{"id": "code", "url": str(code_remote),
            "base_ref": "refs/heads/main", "base_remote": "upstream"}]
        self.f.write(self.root, ".project/project.yaml", store.dump_yaml(self.f.project))
        self.f.write(self.root, ".project-local/repositories.yaml", store.dump_yaml({"code": str(code)}))
        for name, body in store.write_item(runtime._working_files(self.root), record).items():
            self.f.write(self.root, name, body)
        self.f.commit("bind real CLI code repository and approved contract")
        untouched = {name: body for name, body in runtime._working_files(self.root).items()
                     if name.startswith("workitems/B/")}
        environment = {**os.environ, "PROJECT_SESSION_ID": "cli-coordinator", "CODEX_THREAD_ID": "",
                       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                       "PYTHONDONTWRITEBYTECODE": "1"}
        script = Path(__file__).with_name("project.py")

        def cli(*arguments):
            completed = subprocess.run([sys.executable, str(script), "--root", str(self.root),
                "autonomy", *arguments], env=environment, text=True, capture_output=True, timeout=300)
            self.assertEqual(completed.returncode, 0, (arguments, completed.stdout, completed.stderr))
            result = json.loads(completed.stdout)
            self.assertIn(result["status"], {"ready", "published", "no_op"}, result)
            self.assertEqual(git(self.root, "status", "--porcelain"), "")
            return result

        def dispatch(role, worker):
            # Simulated native host receipts exercise the CLI boundary; no
            # external host execution or independent AI review is claimed.
            receipt = self.f.directory / (worker + "-spawn.json")
            receipt.write_text(json.dumps({"host": "codex", "tool": "spawn_agent", "worker_id": worker,
                                           "raw": {"agent_id": worker}}))
            return cli("dispatch", "A", "--role", role, "--receipt-file", str(receipt))

        def finish(execution):
            receipt = self.f.directory / (execution["attempt"] + "-result.json")
            receipt.write_text(json.dumps(self.receipt(execution)))
            return cli("result", "A", "--receipt-file", str(receipt))

        cli("authorize", "--item", "A", "--approval-source", "User authorizes this integration-test scope")
        finish(dispatch("design-review", "cli-design-reviewer"))
        reviewed_state = cli("status", "--item", "A")["items"][0]
        self.assertEqual(reviewed_state["next_role"], "implementation",
                         {"state": reviewed_state, "record": self.f.record()})
        implementation = dispatch("implementation", "cli-implementer")
        worktree = Path(implementation["code_context"]["worktree"])
        (worktree / "program.py").write_text("answer = 2\n")
        finish(implementation)
        finish(dispatch("code-review", "cli-code-reviewer"))
        self.assertEqual(cli("status", "--item", "A")["awaiting_acceptance"], ["A"])
        cli("accept", "A", "--approval-source", "User accepts the tested current source")
        self.assertEqual(cli("status", "--item", "A")["accepted_awaiting_delivery"], ["A"])
        self.assertEqual(git(worktree, "rev-parse", "HEAD"), source_head)
        self.assertEqual(git(code, "rev-parse", "HEAD"), source_head)
        self.assertIn("program.py", git(worktree, "status", "--porcelain"))
        self.assertEqual((worktree / "program.py").read_text(), "answer = 2\n")
        self.assertEqual(git(code_remote, "show-ref"), source_refs)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), git(self.f.remote, "rev-parse", "refs/heads/main"))
        current = runtime._working_files(self.root)
        self.assertEqual({name: body for name, body in current.items() if name.startswith("workitems/B/")}, untouched)

    def test_dispatch_resume_reuses_attempt_after_code_preparation_failure(self):
        self.approved()
        self.authorize()
        with mock.patch.object(self.f.fake_development, "prepare", side_effect=runtime.ProjectError("temporary code preparation failure")):
            paused = autonomy.dispatch(self.root, "A", role="design-review",
                receipt={"host": "codex", "tool": "spawn_agent", "worker_id": "retained-reviewer",
                         "raw": {"agent_id": "retained-reviewer"}}, publish=self.f.publisher)
        self.assertEqual(paused["status"], "blocked", paused)
        self.assertTrue(paused["worker_paused"])
        self.assertIn("autonomy resume", paused["continuation_command"])
        attempt, ticket = paused["attempt"], paused["ticket"]
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "other-coordinator"}), self.assertRaises(runtime.ProjectError):
            autonomy.resume(self.root, "A", attempt=attempt, publish=self.f.publisher)
        self.f.write(self.root, "workitems/A/requirement.md", "Changed dispatch contract.\n")
        with self.assertRaisesRegex(runtime.ProjectError, "stale"):
            autonomy.resume(self.root, "A", attempt=attempt, publish=self.f.publisher)
        self.f.write(self.root, "workitems/A/requirement.md", "Requirement A\n")
        resumed = autonomy.resume(self.root, "A", attempt=attempt, publish=self.f.publisher)
        self.assertEqual(resumed["status"], "ready", resumed)
        self.assertFalse(resumed["worker_paused"])
        self.assertEqual((resumed["attempt"], resumed["worker_id"]), (attempt, "retained-reviewer"))
        executions = self.f.record()["workflow"]["autonomy"]["executions"]
        self.assertEqual(list(executions), [attempt])
        self.assertEqual(executions[attempt]["workflow_ticket"], ticket)

    def test_dispatch_resume_reuses_stage_ticket_after_final_context_partial(self):
        self.approved()
        self.authorize()
        original_begin = workflow.begin
        tickets = []

        def capture_begin(*args, **kwargs):
            result = original_begin(*args, **kwargs)
            tickets.append(result["ticket"])
            return result

        def interrupt_binding(root, writes, identity, message, checks=None):
            if message == "Bind dispatch context A":
                return {"status": "partial"}
            return self.f.publisher(root, writes, identity, message, checks)

        with mock.patch.object(workflow, "begin", side_effect=capture_begin):
            paused = autonomy.dispatch(self.root, "A", role="design-review",
                receipt={"host": "codex", "tool": "spawn_agent", "worker_id": "retained-reviewer",
                         "raw": {"agent_id": "retained-reviewer"}}, publish=interrupt_binding)
            self.assertEqual(paused["status"], "partial", paused)
            self.assertTrue(paused["worker_paused"])
            resumed = autonomy.resume(self.root, "A", attempt=paused["attempt"], publish=self.f.publisher)
        self.assertEqual(resumed["status"], "ready", resumed)
        self.assertEqual(len(tickets), 1)
        executions = self.f.record()["workflow"]["autonomy"]["executions"]
        self.assertEqual(list(executions), [paused["attempt"]])
        self.assertEqual(executions[paused["attempt"]]["workflow_ticket"], tickets[0])
        self.assertEqual(resumed["worker_id"], "retained-reviewer")

    def test_blocked_fixer_remains_an_author_after_another_fixer_succeeds(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        self.finish_execution(self.dispatch("code-review", "code-reviewer"), "fail")
        first = self.dispatch("fix", "first-fixer")
        self.snapshot.update(tree="d" * 40, dirty_digest="d" * 64)
        self.finish_execution(first, "blocked")
        self.authorize()
        self.finish_execution(self.dispatch("fix", "second-fixer"))
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("code-review", "first-fixer")
        self.assertEqual(self.state()["next_role"], "code-review")

    def test_delivered_upstream_fix_requires_fresh_design_review_without_new_user_approval(self):
        dependency = self.f.record("B")
        dependency.update(kind="aggregate", repository=None, status="done",
            delivery={"required": ["merged"], "status": "delivered",
                      "evidence": [{"kind": "merged", "reference": "delivered prerequisite"}]})
        self.f.install(dependency)
        autonomy.accept(self.root, "B", approval_source="User accepts the prerequisite", publish=self.f.publisher)
        item = self.f.record()
        item["depends_on"] = ["B"]
        self.f.install(item)
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "original-design-reviewer"))
        approval = copy.deepcopy(self.f.record()["design"]["approval"])
        self.assertEqual(self.state()["next_role"], "implementation")
        fix = self.f.begin("fix", None, fixes="B", title="已交付上游修复", slug="delivered-fix", repository="code")
        self.f.edit(fix, "The delivered prerequisite needs its independently delivered correction.\n", "requirement.md")
        self.assertEqual(self.f.finish(fix)["status"], "published")
        correction = self.f.record("1-delivered-fix")
        correction.update(status="done", delivery={"required": ["merged"], "status": "delivered",
            "evidence": [{"kind": "merged", "reference": "delivered upstream correction"}]})
        self.f.install(correction)
        state = self.state()
        self.assertEqual((state["state"], state["next_role"], state["reasons"]), ("ready", "design-review", []))
        self.assertEqual(self.f.record()["design"]["approval"], approval)
        self.finish_execution(self.dispatch("design-review", "fresh-baseline-reviewer"))
        self.assertEqual(self.state()["next_role"], "implementation")
        self.assertEqual(self.f.record()["design"]["approval"], approval)

    def test_changed_original_instruction_rejects_dispatched_code_review_result(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        review = self.dispatch("code-review", "code-reviewer")
        self.f.write(self.root, "AGENTS.md", "Changed original project instructions after dispatch.\n")
        with self.assertRaisesRegex(runtime.ProjectError, "read source.*stale"):
            autonomy.result(self.root, "A", receipt=self.receipt(review), publish=self.f.publisher)
        state = self.f.record()["workflow"]["autonomy"]
        self.assertEqual(state["current"], review["attempt"])
        self.assertNotIn("result", state["executions"][review["attempt"]])

    def test_stale_review_retirement_requires_observed_stop_cleanup_and_explicit_restart(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        review = self.dispatch("code-review", "retired-reviewer")
        receipt = self.receipt(review)
        self.snapshot.update(tree="e" * 40, dirty_digest="e" * 64)
        with self.assertRaisesRegex(runtime.ProjectError, "stale"):
            autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)
        retirement = {key: value for key, value in receipt.items() if key not in {"outcome", "report_file"}}
        retirement.update(terminal_status="completed", descendants_stopped=True)
        for changes in ({"worker_id": "wrong-worker"}, {"terminal_status": "running"},
                        {"descendants_stopped": False},
                        {"raw": {"arguments": {"target": review["worker_id"]},
                                 "result": {"worker_status": "running"}}}):
            with self.subTest(changes=changes), self.assertRaises(runtime.ProjectError):
                autonomy.retire(self.root, "A", receipt={**retirement, **changes}, publish=self.f.publisher)
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "wrong-coordinator"}), self.assertRaises(runtime.ProjectError):
            autonomy.retire(self.root, "A", receipt=retirement, publish=self.f.publisher)
        retired = autonomy.retire(self.root, "A", receipt=retirement, publish=self.f.publisher)
        self.assertEqual(retired["status"], "published", retired)
        record = self.f.record()
        state = record["workflow"]["autonomy"]
        self.assertNotIn("current", state)
        self.assertNotIn("result", state["executions"][review["attempt"]])
        self.assertIn("retirement", state["executions"][review["attempt"]])
        self.assertNotEqual(record["development"].get("review", {}).get("result"), "pass")
        self.assertIn("retired_execution_requires_explicit_restart", self.state()["reasons"])
        self.authorize()
        fresh = self.dispatch("code-review", "fresh-reviewer")
        self.assertNotEqual(fresh["attempt"], review["attempt"])

    def test_applied_partial_result_continues_without_replacing_formal_review(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        for index, boundary in enumerate(("Capture execution result A", "Complete execution A")):
            with self.subTest(boundary=boundary):
                if index:
                    self.snapshot.update(tree="f" * 40, dirty_digest="f" * 64)
                execution = self.dispatch("code-review", "partial-reviewer-" + str(index))
                receipt = self.receipt(execution)

                def applied_partial(root, writes, identity, message, checks=None):
                    published = self.f.publisher(root, writes, identity, message, checks)
                    return {"status": "partial"} if message == boundary else published

                interrupted = autonomy.result(self.root, "A", receipt=receipt, publish=applied_partial)
                self.assertEqual(interrupted["status"], "partial", interrupted)
                self.assertIn("autonomy resume A", interrupted["continuation_command"])
                before = (self.f.record().get("development") or {}).get("review")
                if index:
                    self.assertNotIn("current", self.f.record()["workflow"]["autonomy"])
                resumed = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
                self.assertEqual(resumed["status"], "no_op" if index else "published", resumed)
                if index:
                    self.assertEqual(resumed["outcome"], "execution_completed")
                    self.assertEqual(self.f.record()["development"]["review"]["id"], before["id"])
                review_id = self.f.record()["development"]["review"]["id"]
                repeated = autonomy.resume(self.root, "A", attempt=execution["attempt"], publish=self.f.publisher)
                self.assertEqual((repeated["status"], repeated["outcome"]), ("no_op", "execution_completed"))
                self.assertEqual(self.f.record()["development"]["review"]["id"], review_id)

    def test_new_instruction_presence_and_changed_decision_invalidate_review_and_acceptance(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.finish_execution(self.dispatch("implementation", "implementer"))
        instructions = self.root / ".project/business-instructions.md"
        self.assertFalse(instructions.exists())
        review = self.dispatch("code-review", "code-reviewer")
        decision = self.root / "workitems/A/decision.md"
        read_decision = next(entry for entry in review["read"] if entry["path"] == str(decision))
        self.assertEqual(read_decision["content"], decision.read_text())
        receipt = self.receipt(review)
        instructions.write_text("Additional original business instructions discovered after dispatch.\n")
        with self.assertRaises(runtime.ProjectError):
            autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)
        instructions.unlink()
        resumed = autonomy.result(self.root, "A", receipt=receipt, publish=self.f.publisher)
        self.assertEqual(resumed["status"], "published", resumed)
        self.assertEqual(self.state()["state"], "awaiting_acceptance")
        decision.write_text("Changed approved decision after the independent code review.\n")
        with self.assertRaises(runtime.ProjectError):
            autonomy.accept(self.root, "A", approval_source="User cannot reuse the obsolete review",
                            publish=self.f.publisher)

    def test_project_configuration_change_invalidates_both_reviews_before_acceptance(self):
        self.reviewed()
        path = self.root / ".project/project.yaml"
        original = path.read_bytes()
        project = store.load_yaml(original)
        project["repositories"][0]["url"] = "https://example.invalid/changed-repository.git"
        path.write_text(store.dump_yaml(project))
        files = runtime._working_files(self.root)
        for check in (workflow._approved, workflow._implementation_approved):
            with self.subTest(check=check.__name__), self.assertRaises(runtime.ProjectError):
                check(files, self.f.record())
        with self.assertRaises(runtime.ProjectError):
            autonomy.accept(self.root, "A", approval_source="User cannot accept a stale repository review",
                            publish=self.f.publisher)
        path.write_bytes(original)
        self.assertEqual(autonomy.accept(self.root, "A", approval_source="User accepts the current repository",
                                        publish=self.f.publisher)["status"], "published")

    def test_prior_acceptance_does_not_unlock_dependents_after_instruction_change(self):
        self.reviewed()
        autonomy.accept(self.root, "A", approval_source="User accepts reviewed source", publish=self.f.publisher)
        delivery = self.f.begin("delivery-record", kind=["merged"], reference=["actual merge"],
                                provenance="Verified actual delivery")
        self.f.edit(delivery, "Reviewed and accepted source is delivered.\n")
        self.assertEqual(self.f.finish(delivery)["status"], "published")
        downstream = self.f.record("B")
        downstream["depends_on"] = ["A"]
        self.f.install(downstream)
        files = runtime._working_files(self.root)
        self.assertEqual(autonomy._dependency_blocks(self.root, files, downstream), [])
        instruction = self.f.directory / "AGENTS.md"
        self.assertFalse(instruction.exists())
        instruction.write_text("New ancestor instruction after human acceptance.\n")
        files = runtime._working_files(self.root)
        accepted = self.f.record()
        self.assertEqual(accepted["workflow"]["autonomy"]["acceptance"]["binding"], autonomy._artifact_binding(self.root, files, accepted))
        self.assertFalse(autonomy._acceptance_valid(self.root, files, accepted))
        self.assertIn("unaccepted:A", autonomy._dependency_blocks(self.root, files, downstream))
        instruction.unlink()
        self.assertTrue(autonomy._acceptance_valid(self.root, files, accepted))


class CapturedResultValidationTest(unittest.TestCase):
    def test_tool_call_errors_and_mutation_completion_are_not_worker_lifecycle_evidence(self):
        receipt = {"host": "codex", "tool": "collaboration.followup_task", "worker_id": "worker",
                   "raw": {"arguments": {"target": "worker"}, "result": {"status": "completed"}},
                   "role": "code-review", "outcome": "pass", "terminal_status": "completed",
                   "descendants_stopped": True}
        for tool in ("spawn_agent", "followup_task", "send_message", "interrupt_agent"):
            for prefix in ("", "collaboration."):
                with self.subTest(tool=prefix + tool), self.assertRaises(runtime.ProjectError):
                    autonomy._result_outcome({**receipt, "tool": prefix + tool})
        for failure in ({"error": {"code": "worker_not_found"}}, {"isError": True}):
            for raw in ({**receipt["raw"], **failure}, {**receipt["raw"], "result": failure}):
                with self.subTest(raw=raw), self.assertRaises(runtime.ProjectError):
                    autonomy._receipt({**receipt, "raw": raw})
        failed_worker = {**receipt, "tool": "collaboration.list_agents", "outcome": "blocked",
                         "terminal_status": "failed", "raw": {"result": {"agents": [
                             {"agent_name": "worker", "agent_status": {"failed": "worker exception"}}]}}}
        self.assertEqual(autonomy._result_outcome(autonomy._receipt(failed_worker)), "blocked")

    def test_persisted_verdict_requires_lifecycle_evidence_and_revision_body(self):
        attempt, worker = "a" * 32, "worker"
        receipt = {"host": "codex", "tool": "wait_agent", "worker_id": worker,
                   "raw": {"worker_id": worker, "status": "completed"},
                   "attempt": attempt, "role": "design-review", "input_binding": {},
                   "outcome": "pass", "terminal_status": "completed", "descendants_stopped": True}
        body = "Frozen review report.\n"
        entry = {"attempt": attempt, "item": "A", "worker_id": worker, "role": "design-review",
                 "input_binding": {}, "spawn": {"host": "codex", "tool": "spawn_agent",
                 "worker_id": worker, "raw": {"agent_id": worker}}, "result": receipt,
                 "report": {"body": body, "sha256": workflow._hash(body)}}
        item = {"id": "A", "workflow": {"autonomy": {"executions": {attempt: entry}, "current": attempt}}}
        autonomy.validate_state(item)
        for changes in ({"terminal_status": None}, {"descendants_stopped": False},
                        {"raw": {"agent_id": worker}}, {"outcome": "unknown"},
                        {"terminal_status": "stopped", "raw": {"worker_id": worker, "status": "stopped"}}):
            with self.subTest(changes=changes):
                entry["result"] = {**receipt, **changes}
                with self.assertRaises(runtime.ProjectError):
                    autonomy.validate_state(item)
        entry["result"] = {**receipt, "outcome": "revised"}
        with self.assertRaises(runtime.ProjectError):
            autonomy.validate_state(item)
        candidate = "Frozen revised design.\n"
        entry["candidate_sha256"] = workflow._hash(candidate)
        entry["candidate"] = {"body": candidate, "sha256": workflow._hash(candidate)}
        autonomy.validate_state(item)
        for role, outcome in (("implementation", "revised"), ("design-revision", "pass")):
            with self.subTest(role=role, outcome=outcome):
                entry["role"] = entry["result"]["role"] = role
                entry["result"]["outcome"] = outcome
                with self.assertRaises(runtime.ProjectError):
                    autonomy.validate_state(item)
        entry["role"] = entry["result"]["role"] = "design-review"
        entry["result"]["outcome"] = "revised"
        entry["candidate"]["body"] = "Corrupted persisted candidate.\n"
        with self.assertRaises(runtime.ProjectError):
            autonomy.validate_state(item)


if __name__ == "__main__":
    unittest.main()
