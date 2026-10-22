"""Artifact checkpoints and scope authorization; no persisted executor lifecycle."""
import copy
import os
from pathlib import Path
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
        # Test shorthand for agent-owned orchestration; this creates no project job.
        if role in {"baseline", "rebase"}:
            stage = autonomy.begin_transform(self.root, identifier, role=role, author_session=worker, publish=self.f.publisher)
        elif role == "design-revision":
            stage = workflow.begin(self.root, "design-update", identifier, options={"author_session": worker, "contract_unchanged": True}, publish=self.f.publisher)
        elif role in {"design-review", "code-review"}:
            operation = "design-review" if role == "design-review" else "development-finish"
            stage = workflow.begin(self.root, operation, identifier, options={"reviewer_session": worker}, publish=self.f.publisher)
        else:
            stage = workflow.begin(self.root, "development-start", identifier, options={"author_session": worker}, publish=self.f.publisher)
            if stage["status"] == "ready":
                self.assertEqual(self.f.finish(stage)["status"], "published")
        if stage["status"] != "ready" and role not in {"baseline", "rebase"}:
            raise runtime.ProjectError(stage.get("message", str(stage)))
        return {**stage, "role": role, "item": identifier}

    def receipt(self, stage, **options):
        report = self.f.directory / ("product-" + str(len(self.f.calls)) + ".md")
        report.write_text("Actual completed work and verification of the current source.\n")
        return {"role": stage["role"], "report_file": str(report), "provenance": "Actual agent work report", **options}

    def finish_execution(self, stage, outcome="pass", **changes):
        identifier = stage["item"]
        candidate = changes.pop("candidate_file", None)
        if candidate:
            self.f.edit(stage, Path(candidate).read_text(), "spec.md")
        if stage["role"] == "design-revision":
            result = self.f.finish(stage)
        elif stage["role"] in {"design-review", "code-review"}:
            self.f.edit(stage, "Independent review of current original inputs.\n", "report.md")
            result = workflow.finish(self.root, stage["ticket"], options={"result": outcome, "provenance": "Actual independent reviewer report", **changes}, publish=self.f.publisher)
        else:
            result = autonomy.complete(self.root, identifier, **self.receipt(stage, **changes), publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        return result

    def reviewed(self):
        self.approved()
        self.authorize()
        for role, author in (("design-review", "designer-reviewer"), ("implementation", "implementer"), ("code-review", "code-reviewer")):
            self.finish_execution(self.dispatch(role, author))


    def test_published_split_parent_reviews_then_decomposes_without_predevelopment_stages(self):
        draft = self.f.begin("design-update", next_action="split")
        self.f.edit(draft, "# Complete design\n\nUsable stages, shared contracts and dependency DAG.\n")
        self.assertEqual(self.f.finish(draft)["status"], "published")
        item = self.f.record()
        item["design"].pop("approval")  # Separate registration is optional.
        self.f.install(item)
        self.authorize(predevelop=True)
        self.assertEqual(self.state()["next_role"], "design-review")
        self.finish_execution(self.dispatch("design-review", "parent-reviewer"))
        state = self.state()
        self.assertEqual(state["next_action"], "split")
        self.assertIsNone(state["next_role"])
        self.assertNotIn("predevelopment", self.f.record().get("workflow", {}))

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

    def test_acceptance_is_distinct_from_review_and_code_changes_require_reacceptance(self):
        self.reviewed()
        self.assertEqual(self.state()["state"], "awaiting_acceptance")
        self.assertTrue(autonomy.status(self.root, items=["A"])["round_finished"])
        self.assertEqual(autonomy.accept(self.root, "A", approval_source="User inspected and accepts A",
                                         publish=self.f.publisher)["status"], "published")
        self.assertEqual(self.state()["state"], "accepted_awaiting_delivery")
        self.assertNotEqual(self.f.record()["status"], "done")
        self.snapshot["dirty_digest"] = "f" * 64
        self.snapshot["tree"] = "f" * 40
        self.assertFalse(autonomy._acceptance_valid(self.root, runtime._working_files(self.root), self.f.record()))
        self.authorize()
        self.assertEqual(self.state()["next_role"], "code-review")
        self.finish_execution(self.dispatch("code-review", "updated-code-reviewer"))
        self.assertEqual(self.state()["state"], "awaiting_acceptance")

    def test_ordinary_development_still_requires_its_explicit_review_or_waiver(self):
        blocked = workflow.begin(self.root, "development-start", "A", publish=self.f.publisher)
        self.assertEqual(blocked["status"], "blocked")
        self.assertNotIn("autonomy", self.f.record().get("workflow", {}))
        start = self.f.begin("development-start", skip_design_review=True,
                            approval_source="User explicitly waives review for ordinary development")
        self.assertEqual(self.f.finish(start)["status"], "published")
        self.assertEqual(self.f.record()["development"]["author_session"], "author")

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
        instructions.write_text("Additional original business instructions discovered after review start.\n")
        self.f.edit(review, "Independent original assessment.\n", "report.md")
        stale = workflow.finish(self.root, review["ticket"], options={"result": "pass", "provenance": "Actual reviewer"}, publish=self.f.publisher)
        self.assertEqual(stale["status"], "blocked", stale)
        instructions.unlink()
        self.finish_execution(self.dispatch("code-review", "code-reviewer"))
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

    def test_failure_then_success_uses_current_source_without_project_worker_state(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        self.dispatch("implementation", "failed-author")
        self.snapshot.update(tree="d" * 40)
        self.finish_execution(self.dispatch("implementation", "successful-author"))
        self.assertEqual(self.state()["next_role"], "code-review")
        state = self.f.record()["workflow"]["autonomy"]
        self.assertTrue(state["implementation"]["report"]["body"])
        self.assertFalse({"executions", "current", "blocker", "next_role"} & state.keys())
        for author in ("failed-author", "successful-author", "author"):
            result = workflow.begin(self.root, "development-finish", "A", options={"reviewer_session": author}, publish=self.f.publisher)
            self.assertEqual(result["status"], "blocked", result)
        self.finish_execution(self.dispatch("code-review", "independent-reviewer"))
        self.assertEqual(self.state()["state"], "awaiting_acceptance")

    def test_completion_checks_contract_context_and_unsafe_instructions(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        stage = self.dispatch("implementation", "implementer")
        report = self.receipt(stage)
        context = self.root / "workitems/A/context.md"
        original = context.read_text()
        context.write_text("Changed contract context\n")
        with self.assertRaisesRegex(runtime.ProjectError, "required read source"):
            autonomy.complete(self.root, "A", **report, publish=self.f.publisher)
        context.write_text(original)
        instructions = self.root / "workitems/A/AGENTS.md"
        instructions.unlink(missing_ok=True)
        instructions.symlink_to(context)
        with self.assertRaises(runtime.ProjectError):
            autonomy.complete(self.root, "A", **report, publish=self.f.publisher)

    def test_instruction_change_preserves_successful_code_and_requires_current_design_coverage(self):
        self.approved()
        self.authorize()
        self.finish_execution(self.dispatch("design-review", "design-reviewer"))
        stage = self.dispatch("implementation", "implementer")
        self.snapshot.update(tree="d" * 40)
        instructions = self.root / "workitems/A/AGENTS.md"
        instructions.write_text("Check current original source.\n")
        self.finish_execution(stage)
        saved = self.f.record()["workflow"]["autonomy"]["implementation"]
        self.assertTrue(saved["instruction_changes"])
        self.assertEqual(self.state().get("next_action"), "design_reuse_assessment")
        review = self.dispatch("design-review", "fresh-reviewer")
        self.finish_execution(review)
        self.assertEqual(self.state()["next_role"], "code-review")
        self.assertEqual(self.f.record()["workflow"]["autonomy"]["implementation"], saved)

    def test_failed_review_invalidates_completion_and_current_snapshot_is_guarded(self):
        self.reviewed()
        # Reopen the same source for a new independent code review.
        stage = self.dispatch("code-review", "new-reviewer")
        self.finish_execution(stage, outcome="fail")
        self.assertEqual(self.state()["next_role"], "fix")
        self.finish_execution(self.dispatch("fix", "fix-author"))
        self.assertEqual(self.state()["next_role"], "code-review")
        stage = self.dispatch("code-review", "final-reviewer")
        self.snapshot.update(tree="e" * 40)
        self.f.edit(stage, "Review of prior snapshot.\n", "report.md")
        result = workflow.finish(self.root, stage["ticket"], options={"result": "pass", "provenance": "Actual prior snapshot review"}, publish=self.f.publisher)
        self.assertEqual(result["status"], "blocked", result)

    def test_new_design_failure_prevents_accepting_an_earlier_code_pass(self):
        self.reviewed()
        self.finish_execution(self.dispatch("design-review", "new-design-reviewer"), outcome="fail")
        self.assertEqual(self.state()["next_role"], "design-revision")
        with self.assertRaisesRegex(runtime.ProjectError, "design"):
            autonomy.accept(self.root, "A", approval_source="Earlier code pass cannot override current design findings", publish=self.f.publisher)

    def test_contract_internal_revision_needs_independent_confirmation(self):
        self.approved()
        self.authorize()
        stage = self.f.begin("design-update", author_session="revision-author", contract_unchanged=True)
        self.f.edit(stage, "# Design\n\nSame approved behavior with corrected implementation detail.\n")
        self.assertEqual(self.f.finish(stage)["status"], "published")
        approval = self.f.record()["design"]["approval"]
        self.assertEqual(approval["revision"], stage["ticket"])
        self.assertEqual(self.state()["next_role"], "design-review")
        stage = self.dispatch("design-review", "independent-reviewer")
        self.f.edit(stage, "Independently confirmed unchanged approved contract.\n", "report.md")
        failed = workflow.finish(self.root, stage["ticket"], options={"result": "pass", "provenance": "Review"}, publish=self.f.publisher)
        self.assertEqual(failed["status"], "blocked", failed)
        passed = workflow.finish(self.root, stage["ticket"], options={"result": "pass", "provenance": "Independent unchanged-contract review", "contract_unchanged": True}, publish=self.f.publisher)
        self.assertEqual(passed["status"], "published", passed)
        self.assertEqual(self.state()["next_role"], "implementation")


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


if __name__ == "__main__":
    unittest.main()
