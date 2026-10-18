"""Fixed workflow behavior in isolated Git workspaces with local bare remotes."""

import copy
import os
from pathlib import Path
import shlex
import unittest
from unittest import mock

import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_runtime as fixtures


class WorkflowTest(unittest.TestCase):
    configure = fixtures.WorkspaceTest.configure
    write = fixtures.WorkspaceTest.write

    def setUp(self):
        fixtures.WorkspaceTest.setUp(self)
        self.project["schema_version"] = 2
        self.write(self.a, ".project/project.yaml", store.dump_yaml(self.project))
        (self.a / ".project/project.json").unlink()
        for identifier in ("A", "B"):
            record = fixtures.item(identifier)
            record["documents"] = {"requirement": "requirement.md", "context": "context.md", "decision": "decision.md", "logs": "logs.md"}
            record["design"] = {"file": "spec.md", "version": 0, "state": "draft"}
            (self.a / f"workitems/{identifier}/item.json").unlink()
            for name, text in store.write_item({".project/project.yaml": b""}, record).items():
                self.write(self.a, name, text)
            self.write(self.a, f"workitems/{identifier}/requirement.md", "Requirement " + identifier + "\n")
            self.write(self.a, f"workitems/{identifier}/context.md", "Current context\n")
        self.commit("schema two")
        self.session = mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "author", "CODEX_THREAD_ID": ""})
        self.session.start()
        self.addCleanup(self.session.stop)
        self.calls = []
        self.real_publish = False
        self.refresh_patch = mock.patch.object(runtime, "refresh_project", return_value={"changed": False})
        self.refresh_patch.start()
        self.addCleanup(self.refresh_patch.stop)
        from types import SimpleNamespace
        self.fake_development = SimpleNamespace(
            instruction_files=lambda *args, **kwargs: [],
            reservation_for_discard=lambda *args, **kwargs: None,
            prepare=lambda root, item, project, **kwargs: item.get("development") or {"worktree": "worktrees/" + item["id"], "branch": "feature/" + item["id"], "base_commit": "a" * 40},
            worktree_location=lambda *args: self.directory / "fake-code",
            snapshot=lambda *args: {"head": "a" * 40, "tree": "b" * 40, "dirty_digest": "c" * 64, "clean": True},
            verify_merged=lambda *args, **kwargs: {"verified": True, "kind": "merged", "reference": "d" * 40})
        self.development_patch = mock.patch.object(workflow, "_development_module", return_value=self.fake_development)
        self.development_patch.start()
        self.addCleanup(self.development_patch.stop)

    def commit(self, message):
        fixtures.git(self.a, "add", ".")
        fixtures.git(self.a, "commit", "--quiet", "-m", message)
        fixtures.git(self.a, "push", "--quiet", "origin", "main")

    def publisher(self, root, writes, identity, message, checks=None):
        self.calls.append(copy.deepcopy(writes))
        if not self.real_publish:
            files = runtime._working_files(root)
            for name, expected in (checks or {}).items():
                if workflow._hash(files.get(name)) != expected:
                    raise runtime.ProjectError("byte check conflict: " + name)
            for name, text in writes.items():
                path = Path(root) / name
                if text is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
            return {"status": "published"}
        bundle = {"writes": writes, "checks": checks, "message": message,
                  "session": identity["session"], "token": identity["token"]}
        path = self.directory / "bundle.json"
        path.write_text(fixtures.text(bundle), encoding="utf-8")
        result = runtime.publish(root, path)
        return {"status": "published" if result.get("commit") else "no_op", **result}

    def begin(self, operation, selector="A", **options):
        result = workflow.begin(self.a, operation, selector, options=options, publish=self.publisher)
        self.assertEqual(result["status"], "ready", result)
        return result

    def finish(self, result):
        return workflow.finish(self.a, result["ticket"], publish=self.publisher)

    def edit(self, result, text, name=None):
        targets = result["editable"]
        target = next(value for value in targets if name is None or Path(value["path"]).name == name)
        Path(target["path"]).write_text(text, encoding="utf-8")

    def record(self, identifier="A"):
        return store.item(runtime._working_files(self.a), identifier)

    def install(self, record):
        for name, value in store.write_item(runtime._working_files(self.a), record).items():
            self.write(self.a, name, value)
        self.commit("fixture metadata")

    def designed(self, identifier="A"):
        result = self.begin("design-update", identifier)
        self.edit(result, "# Design\n\nPrecise behavior\n")
        self.assertEqual(self.finish(result)["status"], "published")
        result = self.begin("decision-record", identifier, approval_source="User said: approve this design")
        self.edit(result, "Approved behavior and tradeoffs.\n")
        self.assertEqual(self.finish(result)["status"], "published")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "reviewer"}):
            result = self.begin("design-review", identifier)
            self.edit(result, "Reviewed full requirement and design; no findings.\n")
            self.assertEqual(workflow.finish(self.a, result["ticket"], options={"result": "pass", "provenance": "Independent review session"}, publish=self.publisher)["status"], "published")

    def test_create_only_requirement_context_and_repeat_finish_is_noop(self):
        result = self.begin("create", None, title="新需求", slug="new-task", repository="code")
        self.assertEqual({Path(entry["path"]).name for entry in result["editable"]}, {"requirement.md", "context.md"})
        self.edit(result, "# New requirement\n", "requirement.md")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.finish(result)["status"], "no_op")
        directory, tombstone = workflow._load(self.a, result["ticket"])
        self.assertEqual({path.name for path in directory.iterdir()}, {"manifest.yaml"})
        self.assertEqual(set(tombstone), {"ticket", "operation", "item", "identity", "created_at", "state"})
        record = self.record("1-new-task")
        self.assertEqual(record["design"]["version"], 0)
        self.assertIsNone(record["development"])
        self.assertFalse((self.a / "workitems/1-new-task/spec.md").exists())
        for name in ("requirement.md", "context.md", "decision.md", "logs.md", "AGENTS.md", "metadata.yaml"):
            self.assertTrue((self.a / "workitems/1-new-task" / name).is_file(), name)
        self.assertEqual(store.load_yaml((self.a / ".project/graph.yaml").read_bytes())["revision"], 1)

    def test_design_version_bytes_approval_independence_and_invalidation(self):
        result = self.begin("design-update")
        self.edit(result, "# Design\n")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.record()["design"]["version"], 1)
        result = self.begin("design-update")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.record()["design"]["version"], 1)
        self.designed()
        self.assertEqual(self.record()["design"]["state"], "implementable")
        old_review = self.record()["design"]["review"]["id"]
        result = self.begin("design-update")
        self.edit(result, "# Current replacement design\n")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.record()["design"]["version"], 3)
        self.assertNotIn("review", self.record()["design"])
        for suffix in (".md", ".yaml"):
            self.assertFalse((self.a / ("workitems/A/records/" + old_review + suffix)).exists())
        self.designed()
        result = self.begin("requirement-update")
        self.edit(result, "Changed requirement\n")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.record()["design"]["state"], "draft")
        self.assertNotIn("review", self.record()["design"])

    def test_decision_and_knowledge_drafts_replace_current_documents_without_machine_log(self):
        self.write(self.a, "workitems/A/decision.md", "Current decision\n")
        self.write(self.a, "workitems/A/logs.md", "Current reusable knowledge\n")
        for operation, name in (("decision-record", "decision.md"), ("log-record", "logs.md")):
            for text in ("First replacement\n", "Latest replacement\n"):
                result = self.begin(operation)
                self.assertEqual(Path(result["editable"][0]["path"]).name, name)
                current = (self.a / "workitems/A" / name).read_text()
                self.assertEqual(result["editable"][0]["template"], current)
                self.edit(result, text)
                self.assertEqual(self.finish(result)["status"], "published")
                self.assertEqual((self.a / "workitems/A" / name).read_text(), text)
                if operation == "decision-record":
                    self.assertEqual((self.a / "workitems/A/logs.md").read_text(), "Current reusable knowledge\n")
        result = self.begin("rename", title="Current item name")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual((self.a / "workitems/A/logs.md").read_text(), "Latest replacement\n")

    def test_record_collection_retains_optimistic_guard_for_concurrent_record_changes(self):
        history = "workitems/A/records/old.md"
        self.write(self.a, history, "Obsolete report\n")
        result = self.begin("context-update")
        self.edit(result, "Current context replacement\n")
        self.write(self.a, history, "Concurrently revised report\n")
        blocked = self.finish(result)
        self.assertEqual(blocked["code"], "stale_ticket")
        self.assertEqual((self.a / history).read_text(), "Concurrently revised report\n")
        result = self.begin("context-update")
        self.edit(result, "Current context replacement\n")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertFalse((self.a / history).exists())

    def test_review_cannot_be_author_or_promoted_by_markdown(self):
        result = self.begin("design-update")
        self.edit(result, "# Design\n\n- [x] independent review passed\n")
        self.finish(result)
        self.assertEqual(self.record()["design"]["state"], "draft")
        blocked = workflow.begin(self.a, "design-review", "A", options={}, publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked")
        result = self.begin("decision-record", approval_source="Actual user approval")
        self.edit(result, "Approved\n")
        self.finish(result)
        blocked = workflow.begin(self.a, "design-review", "A", options={}, publish=self.publisher)
        self.assertEqual(blocked["action_code"], "independent_review_required")

    def test_developing_design_review_keeps_owner_and_registers_independent_report(self):
        self.designed()
        report = self.directory / "independent-design-review.md"
        body = "Independent assessment of the revised requirement, design and source.\n"
        report.write_text(body)
        unowned = workflow.begin(self.a, "design-review", "A",
            options={"reviewer_session": "fresh-reviewer", "review_file": str(report)}, publish=self.publisher)
        self.assertEqual(unowned["status"], "blocked")
        self.assertIn("owned developing item", unowned["message"])
        self.assertEqual(self.finish(self.begin("development-start"))["status"], "published")
        original = copy.deepcopy(self.record())
        revision = self.begin("design-update")
        self.edit(revision, "# Revised design during development\n")
        self.assertEqual(self.finish(revision)["status"], "published")
        approval = self.begin("decision-record", approval_source="User approves revised contract")
        self.edit(approval, "Approved revised design.\n")
        self.assertEqual(self.finish(approval)["status"], "published")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "fresh-reviewer"}):
            blocked = workflow.begin(self.a, "design-review", "A", publish=self.publisher)
            self.assertEqual(blocked["status"], "blocked")  # No takeover of source ownership.
        for inputs in ({"reviewer_session": "fresh-reviewer"}, {"review_file": str(report)},
                       {"reviewer_session": "author", "review_file": str(report)}):
            with self.subTest(inputs=inputs):
                blocked = workflow.begin(self.a, "design-review", "A", options=inputs, publish=self.publisher)
                self.assertEqual(blocked["status"], "blocked")
        options = {"reviewer_session": "fresh-reviewer", "review_file": str(report)}
        stale = self.begin("design-review", **options)
        report.write_text("Different report after review handoff.\n")
        self.assertEqual(workflow.finish(self.a, stale["ticket"], options={"result": "pass", "provenance": "Actual external reviewer"},
                                         publish=self.publisher)["code"], "stale_evidence")
        report.write_text(body)
        review = self.begin("design-review", **options)
        self.assertEqual(workflow.finish(self.a, review["ticket"], options={"result": "pass", "provenance": "Actual external reviewer"},
                                         publish=self.publisher)["status"], "published")
        item = self.record()
        self.assertEqual(item["owner"], original["owner"])
        self.assertEqual(item["development"], original["development"])
        self.assertEqual(item["design"]["review"]["session"], "fresh-reviewer")
        self.assertEqual(item["design"]["review"]["recorded_by"], "author")
        self.assertEqual(item["design"]["review"]["source"]["sha256"], workflow._hash(body))
        self.assertEqual((self.a / item["design"]["review"]["report"]).read_text(), body)
        report.unlink()
        self.assertEqual(self.finish(self.begin("development-start"))["status"], "published")


    def test_stale_draft_never_overwrites_remote_requirement(self):
        result = self.begin("requirement-update")
        self.edit(result, "My stale version\n")
        self.write(self.a, "workitems/A/requirement.md", "New remote version\n")
        self.commit("concurrent input")
        outcome = self.finish(result)
        self.assertEqual(outcome["status"], "blocked")
        self.assertEqual(outcome["code"], "stale_ticket")
        self.assertEqual(shlex.split(outcome["next_command"])[-3:], ["begin", "requirement-update", "A"])
        self.assertNotIn("finish_command", outcome)
        self.assertEqual((self.a / "workitems/A/requirement.md").read_text(), "New remote version\n")
        self.assertTrue(Path(result["editable"][0]["path"]).exists())

    def test_stale_authorization_and_review_require_new_evidence_without_continuation(self):
        waived = self.begin("development-start", skip_design_review=True, approval_source="User permits this scope")
        self.write(self.a, "workitems/A/requirement.md", "Changed authorized scope\n")
        stale_waiver = self.finish(waived)

        item = self.record("B")
        item["status"] = "awaiting_delivery"
        item["development"] = {"worktree": "worktrees/B", "branch": "feature/B", "base_commit": "a" * 40}
        self.install(item)
        report = self.directory / "review.md"
        report.write_text("Independent review of the original scope.\n")
        review = self.begin("development-finish", "B", result="pass", provenance="Actual independent review",
                            reviewer_session="independent", review_file=str(report))
        self.write(self.a, "workitems/B/requirement.md", "Changed reviewed scope\n")
        stale_review = self.finish(review)
        for result, original in ((stale_waiver, waived), (stale_review, review)):
            with self.subTest(ticket=original["ticket"]):
                self.assertEqual(result["status"], "blocked", result)
                self.assertEqual(result["code"], "stale_evidence")
                self.assertNotIn("next_command", result)
                self.assertNotIn("finish_command", result)
                self.assertEqual(result["ticket"], original["ticket"])
        self.assertNotIn("design_waiver", self.record().get("workflow", {}))
        self.assertNotIn("review", self.record("B")["development"])

    def test_manifest_tampering_extra_files_links_and_cross_session_rejected(self):
        result = self.begin("context-update")
        directory = Path(result["editable"][0]["path"]).parent
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "stranger"}):
            self.assertEqual(self.finish(result)["action_code"], "session_conflict")
        (directory / "extra.yaml").write_text("status: done\n")
        self.assertEqual(self.finish(result)["status"], "blocked")
        (directory / "extra.yaml").unlink()
        draft = Path(result["editable"][0]["path"])
        draft.unlink()
        draft.symlink_to(self.a / "AGENTS.md")
        self.assertEqual(self.finish(result)["status"], "blocked")
        draft.unlink()
        draft.write_text("safe\n")
        path = directory / "manifest.yaml"
        path.write_text(path.read_text().replace("operation: context-update", "operation: delivery-record"))
        self.assertEqual(self.finish(result)["action_code"], "invalid_ticket")

    def test_partial_retry_retains_exact_version_and_intent(self):
        result = self.begin("design-update")
        self.edit(result, "# Design\n")
        original = self.publisher
        pending = [True]
        def partial(root, writes, identity, message, checks=None):
            if pending:
                pending.pop()
                original(root, writes, identity, message, checks)
                return {"status": "partial", "stage": "synchronize"}
            # Recovery observes the already-published exact same intent.
            self.assertEqual(writes, self.calls[-1])
            return {"status": "no_op"}
        first = workflow.finish(self.a, result["ticket"], publish=partial)
        self.assertEqual(first["status"], "partial")
        self.assertEqual(self.record()["design"]["version"], 1)
        retry = workflow.finish(self.a, result["ticket"], publish=partial)
        self.assertEqual(retry["status"], "no_op")
        self.assertEqual(self.record()["design"]["version"], 1)

    def test_fix_preserves_delivered_history_and_blocks_transitive_downstream(self):
        original = self.record("A")
        original["status"] = "done"
        original["delivery"].update(status="delivered", evidence=[{"kind": "merged", "reference": "sha"}])
        self.install(original)
        downstream = self.record("B")
        downstream["depends_on"] = ["A"]
        self.install(downstream)
        self.designed("B")
        before = (self.a / "workitems/A/metadata.yaml").read_bytes()
        result = self.begin("fix", None, title="修复已交付问题", slug="bug-fix", fixes="A")
        self.edit(result, "# Regression and expected behavior\n", "requirement.md")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual((self.a / "workitems/A/metadata.yaml").read_bytes(), before)
        fix = self.record("1-bug-fix")
        self.assertEqual(fix["fixes"], "A")
        blocked = workflow.begin(self.a, "development-start", "B", publish=self.publisher)
        self.assertEqual(blocked["action_code"], "checkpoint_blocked")
        self.assertIn("1-bug-fix", blocked["message"])
        self.assertEqual(self.record("A")["status"], "done")

    def test_active_checkpoint_detects_new_fix_and_preserves_owner_and_draft(self):
        original = self.record("A")
        original["status"] = "done"
        original["delivery"].update(status="delivered", evidence=[{"kind": "merged", "reference": "sha"}])
        self.install(original)
        downstream = self.record("B")
        downstream["depends_on"] = ["A"]
        self.install(downstream)
        self.designed("B")
        result = self.begin("development-start", "B")
        fix = workflow._new_item(store.items(runtime._working_files(self.a)), {"title": "修复", "slug": "fix", "fixes": "A"}, "fix")
        self.install(fix)
        outcome = self.finish(result)
        self.assertEqual(outcome["status"], "blocked")
        self.assertEqual(outcome["action_code"], "checkpoint_blocked")
        self.assertIsNotNone(self.record("B")["owner"])

    def test_downstream_review_dependency_digest_does_not_write_another_owner(self):
        downstream = self.record("B")
        downstream["depends_on"] = ["A"]
        self.install(downstream)
        self.designed("B")
        before = (self.a / "workitems/B/metadata.yaml").read_bytes()
        result = self.begin("requirement-update", "A")
        self.edit(result, "New upstream behavior\n")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual((self.a / "workitems/B/metadata.yaml").read_bytes(), before)
        with self.assertRaisesRegex(runtime.ProjectError, "stale"):
            workflow._approved(runtime._working_files(self.a), self.record("B"))

    def test_explicit_user_waiver_preserves_draft_and_requires_independent_implementation_review(self):
        from types import SimpleNamespace
        fake = SimpleNamespace(
            instruction_files=lambda *args, **kwargs: [],
            prepare=lambda *args, **kwargs: {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": "a" * 40},
            worktree_location=lambda *args: self.directory / "fake-code",
            snapshot=lambda *args: {"head": "a" * 40, "tree": "b" * 40, "dirty_digest": "c" * 64, "clean": True},
            verify_merged=lambda *args, **kwargs: {"verified": True, "kind": "merged", "reference": "d" * 40})
        missing = workflow.begin(self.a, "development-start", "A", options={"skip_design_review": True}, publish=self.publisher)
        self.assertEqual(missing["status"], "blocked")
        report = self.directory / "independent-review.md"
        report.write_text("Reviewed the actual implementation snapshot; pass.\n")
        with mock.patch.object(workflow, "_development_module", return_value=fake):
            result = self.begin("development-start", skip_design_review=True, approval_source="User explicitly requests this simple item skip design review")
            self.assertEqual(self.finish(result)["status"], "published")
            item = self.record()
            self.assertEqual(item["design"]["state"], "draft")
            self.assertEqual(item["design"]["version"], 0)
            self.assertEqual(item["status"], "developing")
            self.assertEqual(item["workflow"]["design_waiver"]["kind"], "user_design_review_waiver")
            before_development = copy.deepcopy(item["development"])
            continuation = self.begin("development-start")
            continued = self.finish(continuation)
            self.assertIn(continued["status"], {"published", "no_op"})
            self.assertEqual(self.record()["development"], before_development)
            self.assertEqual(continued["code_context"]["branch"], before_development["branch"])
            bad = workflow.begin(self.a, "development-finish", "A", options={"result": "pass", "provenance": "self", "reviewer_session": "author", "review_file": str(report)}, publish=self.publisher)
            self.assertEqual(bad["status"], "blocked")
            result = self.begin("development-finish", result="pass", provenance="Independent reviewer execution", reviewer_session="independent", review_file=str(report))
            self.assertEqual(self.finish(result)["status"], "published")
            self.assertEqual(self.record()["status"], "awaiting_delivery")
            result = self.begin("delivery-record", provenance="Actual remote ancestry check", commit="a" * 40)
            self.edit(result, "Verified merged behavior.\n")
            self.assertEqual(self.finish(result)["status"], "published")
            self.assertEqual(self.record()["status"], "done")

    def test_waiver_invalidates_on_requirement_change_without_automatic_reapproval(self):
        result = self.begin("development-start", skip_design_review=True, approval_source="User authorizes skipping design review for this item")
        self.assertEqual(self.finish(result)["status"], "published")
        old_waiver = self.record()["workflow"]["design_waiver"]
        result = self.begin("requirement-update")
        self.edit(result, "Materially expanded requirement\n")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertNotIn("design_waiver", self.record().get("workflow", {}))
        for suffix in (".md", ".yaml"):
            self.assertFalse((self.a / ("workitems/A/records/" + old_waiver["id"] + suffix)).exists())
        with self.assertRaises(runtime.ProjectError):
            workflow._approved(runtime._working_files(self.a), self.record())

    def test_real_code_repository_design_to_independent_review_to_verified_merge(self):
        self.development_patch.stop()
        self.refresh_patch.stop()
        self.real_publish = True
        code_remote = self.directory / "code.git"
        code_remote.mkdir()
        fixtures.git(code_remote, "init", "--bare", "--initial-branch=main", "--quiet")
        code_main = self.directory / "code-main"
        code_main.mkdir()
        fixtures.git(code_main, "init", "--initial-branch=main", "--quiet")
        self.configure(code_main)
        (code_main / "program.py").write_text("answer = 1\n")
        (code_main / "AGENTS.md").write_text("Keep implementation simple.\n")
        fixtures.git(code_main, "add", ".")
        fixtures.git(code_main, "commit", "--quiet", "-m", "base")
        fixtures.git(code_main, "remote", "add", "origin", str(code_remote))
        fixtures.git(code_main, "push", "--quiet", "-u", "origin", "main")
        self.project["repositories"] = [{"id": "code", "url": str(code_remote), "base_ref": "refs/heads/main", "base_remote": "origin"}]
        self.write(self.a, ".project/project.yaml", store.dump_yaml(self.project))
        self.write(self.a, ".project-local/repositories.yaml", store.dump_yaml({"code": str(code_main)}))
        self.commit("bind real code repository")
        self.designed()
        item = self.record()
        code_base = fixtures.git(code_main, "rev-parse", "main")
        self.assertEqual(item["design"]["review"]["base_commit"], code_base)
        self.assertNotEqual(code_base, fixtures.git(self.a, "rev-parse", "HEAD"))
        result = self.begin("development-start")
        self.assertEqual(self.finish(result)["status"], "published")
        item = self.record()
        worktree = self.a / item["development"]["worktree"]
        (worktree / "program.py").write_text("answer = 2\n")
        fixtures.git(worktree, "add", "program.py")
        fixtures.git(worktree, "commit", "--quiet", "-m", "implement")
        source_commit = fixtures.git(worktree, "rev-parse", "HEAD")
        report = self.directory / "review.md"
        report.write_text("Independent implementation review of actual code: pass.\n")
        result = self.begin("development-finish", result="pass", provenance="Independent session report", reviewer_session="implementation-reviewer", review_file=str(report))
        self.assertEqual(self.finish(result)["status"], "published")
        fixtures.git(worktree, "push", "--quiet", "origin", "HEAD:" + item["development"]["publish_ref"])
        fixtures.git(code_main, "merge", "--ff-only", item["development"]["branch"])
        fixtures.git(code_main, "push", "--quiet", "origin", "main")
        # Delivery checks the current implementation snapshot and actual merge;
        # historical design-review-pending is not an extra delivery gate.
        item = self.record()
        item["design"]["state"] = "review-pending"
        item["design"].pop("review", None)
        self.install(item)
        result = self.begin("delivery-record", provenance="Verified target branch ancestry", commit=source_commit)
        self.edit(result, "Actual merge ancestry and acceptance checked.\n")
        outcome = self.finish(result)
        self.assertEqual(outcome["status"], "published", outcome)
        self.assertEqual(self.record()["status"], "done")
        self.assertEqual(self.record()["delivery"]["evidence"][-1]["reference"], source_commit)

    def test_discard_real_reservation_reprepares_at_current_base_without_old_resources(self):
        import project_development as development
        self.development_patch.stop()
        code_remote = self.directory / "code-remote.git"
        code_remote.mkdir()
        fixtures.git(code_remote, "init", "--bare", "--initial-branch=main", "--quiet")
        code = self.directory / "code"
        code.mkdir()
        fixtures.git(code, "init", "--initial-branch=main", "--quiet")
        self.configure(code)
        (code / "AGENTS.md").write_text("Current code instructions.\n")
        fixtures.git(code, "add", ".")
        fixtures.git(code, "commit", "--quiet", "-m", "base")
        fixtures.git(code, "remote", "add", "origin", str(code_remote))
        fixtures.git(code, "push", "--quiet", "-u", "origin", "main")
        self.project["repositories"] = [{"id": "code", "url": str(code_remote), "base_ref": "refs/heads/main", "base_remote": "origin"}]
        self.write(self.a, ".project/project.yaml", store.dump_yaml(self.project))
        self.write(self.a, ".project-local/repositories.yaml", store.dump_yaml({"code": str(code)}))
        self.commit("bind real code")
        self.designed()
        old = self.record()["development"]
        old_location = self.a / old["worktree"]
        reservation = development._reservation_path(self.a, development._identity(self.project, self.record()))
        old_reservation = reservation.read_bytes()
        fixtures.git(code, "worktree", "remove", str(old_location))
        discarded = self.begin("cleanup-record", cleanup_status="done", reference="Actual Git removal", discard_development=True, approval_source="User discards the old unfinished implementation")
        self.assertEqual(self.finish(discarded)["status"], "published")
        self.assertEqual(reservation.read_bytes(), old_reservation)
        ordinary = self.begin("cleanup-record", cleanup_status="done", reference="Still absent")
        self.assertEqual(self.finish(ordinary)["status"], "published")
        historical = self.a / ("workitems/A/records/" + discarded["ticket"] + ".yaml")
        self.assertTrue(historical.exists())
        self.assertEqual(store.load_yaml(historical.read_bytes())["reservation_snapshot"], store.load_yaml(old_reservation))
        (code / "next.txt").write_text("Current target branch.\n")
        fixtures.git(code, "add", ".")
        fixtures.git(code, "commit", "--quiet", "-m", "new target baseline")
        fixtures.git(code, "push", "--quiet", "origin", "main")
        current_base = fixtures.git(code, "rev-parse", "HEAD")
        foreign = store.load_yaml(old_reservation)
        foreign["branch"] = "feature/unrelated"
        reservation.write_text(store.dump_yaml(foreign))
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "fresh-reviewer"}):
            blocked = workflow.begin(self.a, "design-review", "A", publish=self.publisher)
            self.assertEqual(blocked["status"], "blocked", blocked)
            self.assertIn("reservation", blocked["message"])
            self.assertEqual(store.load_yaml(reservation.read_bytes()), foreign)
            self.assertFalse(old_location.exists())
            reservation.write_bytes(old_reservation)
            review = workflow.resume(self.a, blocked["ticket"], publish=self.publisher)
            self.assertEqual(review["status"], "ready", review)
            self.assertFalse(historical.exists())
            self.assertTrue((self.a / ("workitems/A/records/" + ordinary["ticket"] + ".yaml")).exists())
            fresh = self.record()["development"]
            self.assertEqual(fresh["base_commit"], current_base)
            self.assertNotEqual(fresh["branch"], old["branch"])
            self.assertEqual(fresh["worktree"], old["worktree"])
            self.assertNotIn("development_discard_record", self.record()["workflow"])
            self.assertTrue((old_location / "next.txt").exists())
            self.assertEqual(fixtures.git(code_remote, "rev-parse", old["publish_ref"]), old["base_commit"])
            self.edit(review, "Independent design review against current code baseline.\n")
            self.assertEqual(workflow.finish(self.a, review["ticket"], options={"result": "pass", "provenance": "Fresh independent review"}, publish=self.publisher)["status"], "published")
        started = self.begin("development-start")
        self.assertEqual(self.finish(started)["status"], "published")
        self.assertEqual(fixtures.git(old_location, "rev-parse", "HEAD"), current_base)

    def test_scoped_reads_and_unrelated_changes_do_not_stale_ticket(self):
        self.write(self.a, "workitems/B/spec.md", "Unrelated spec\n" * 100)
        upstream = self.record("B")
        upstream["design"]["version"] = 1
        self.install(upstream)
        self.write(self.a, "workitems/A/logs.md", "Historical log\n" * 100)
        self.write(self.a, "workitems/A/records/history.md", "Historical report\n" * 100)
        result = self.begin("requirement-update")
        paths = {entry["path"] for entry in result["read"]}
        for name in ("workitems/B/spec.md", "workitems/A/logs.md", "workitems/A/records/history.md"):
            self.assertNotIn(str(self.a / name), paths)
        self.write(self.a, "workitems/B/logs.md", "Concurrent unrelated event\n")
        self.assertEqual(self.finish(result)["status"], "published")
        item = self.record()
        item["depends_on"] = ["B"]
        self.install(item)
        result = self.begin("design-update")
        paths = {entry["path"] for entry in result["read"]}
        self.assertIn(str(self.a / "workitems/B/requirement.md"), paths)
        self.assertIn(str(self.a / "workitems/B/spec.md"), paths)
        self.assertNotIn(str(self.a / "workitems/B/logs.md"), paths)

    def test_claim_partial_and_prepare_failure_resume_same_ticket_with_real_base(self):
        result = workflow.begin(self.a, "design-update", "A", publish=lambda *args, **kwargs: {"status": "partial"})
        self.assertEqual(result["status"], "partial")
        original = self.fake_development.prepare
        self.fake_development.prepare = mock.Mock(side_effect=runtime.ProjectError("temporary fetch failure"))
        blocked = workflow.resume(self.a, result["ticket"], publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["ticket"], result["ticket"])
        self.assertIn("resume", blocked["next_command"])
        self.assertIsNotNone(self.record()["owner"])
        self.fake_development.prepare = original
        resumed = workflow.resume(self.a, result["ticket"], publish=self.publisher)
        self.assertEqual(resumed["status"], "ready", resumed)
        self.assertEqual(resumed["ticket"], result["ticket"])
        self.assertEqual(resumed["code_context"]["base_commit"], "a" * 40)
        self.edit(resumed, "# Resumed design\n")
        self.assertEqual(self.finish(resumed)["status"], "published")

    def test_code_context_partial_resume_replays_same_publication_without_prepare(self):
        for identifier, already_written in (("A", False), ("B", True)):
            with self.subTest(already_written=already_written):
                retained = []
                interrupted = [True]

                def publish(root, writes, identity, message, checks=None):
                    if not message.startswith("Prepare code context "):
                        return self.publisher(root, writes, identity, message, checks)
                    retained.append((copy.deepcopy(writes), copy.deepcopy(identity), message))
                    if interrupted:
                        interrupted.pop()
                        if already_written:
                            self.publisher(root, writes, identity, message, checks)
                        return {"status": "partial", "stage": "synchronize"}
                    self.assertEqual(retained[-1], retained[0])
                    return self.publisher(root, writes, identity, message, checks)

                with mock.patch.object(self.fake_development, "prepare", wraps=self.fake_development.prepare) as prepare:
                    result = workflow.begin(self.a, "design-update", identifier, publish=publish)
                    self.assertEqual(result["status"], "partial", result)
                    self.assertIn("resume", result["next_command"])
                    self.assertNotIn("finish_command", result)
                    _, manifest = workflow._load(self.a, result["ticket"])
                    self.assertEqual(manifest["state"], "context-publication-pending")
                    self.assertEqual(manifest["context_writes"], retained[0][0])
                    resumed = workflow.resume(self.a, publish=publish)
                    self.assertEqual(resumed["status"], "ready", resumed)
                    self.assertEqual(resumed["ticket"], result["ticket"])
                    self.assertEqual(resumed["code_context"]["base_commit"], "a" * 40)
                    self.assertEqual(prepare.call_count, 1)
                    self.assertEqual(len(retained), 2)
                self.edit(resumed, "# Resumed design\n")
                self.assertEqual(self.finish(resumed)["status"], "published")

    def test_cleanup_requires_absence_and_delivered_kind_cannot_change(self):
        (self.directory / "fake-code").mkdir()
        item = self.record()
        item["development"] = {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": "a" * 40}
        self.install(item)
        result = self.begin("cleanup-record", cleanup_status="done", reference="manual claim", mode="manual", approval_source="User requests manual cleanup")
        self.assertEqual(self.finish(result)["status"], "blocked")
        result = self.begin("cleanup-record", cleanup_status="not_applicable", reference="Retain manually", mode="skipped", approval_source="User explicitly retains the worktree")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.record()["workflow"]["cleanup_record"], result["ticket"])
        previous = result["ticket"]
        result = self.begin("cleanup-record", cleanup_status="not_applicable", reference="Current retention decision", mode="skipped", approval_source="User reconfirms current retention")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.record()["workflow"]["cleanup_record"], result["ticket"])
        for suffix in (".md", ".yaml"):
            self.assertFalse((self.a / ("workitems/A/records/" + previous + suffix)).exists())
            self.assertTrue((self.a / ("workitems/A/records/" + result["ticket"] + suffix)).exists())
        item = self.record()
        item["status"] = "done"
        item["delivery"].update(status="delivered", evidence=[{"kind": "merged", "reference": "sha"}])
        self.install(item)
        blocked = workflow.begin(self.a, "kind-update", "A", options={"kind": "aggregate"}, publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(self.record()["kind"], "development")

    def test_cleaned_metadata_missing_checkout_preflight_and_recovery(self):
        import project_development as development
        item = self.record()
        item.update(cleanup="pending", development={"worktree": "worktrees/removed", "branch": "feature/removed", "base_commit": "a" * 40})
        self.install(item)
        self.fake_development.instruction_files = development.instruction_files
        self.fake_development.worktree_location = development.worktree_location
        self.fake_development.prepare = mock.Mock(side_effect=AssertionError("metadata must not prepare code"))
        blocked = workflow.begin(self.a, "context-update", "A", publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked", blocked)
        self.assertNotIn("next_command", blocked)
        self.assertIsNone(self.record()["owner"])
        self.assertEqual(self.calls, [])
        item["cleanup"] = "done"
        self.install(item)
        result = self.begin("context-update")
        self.edit(result, "Removed implementation; retained requirement and design.\n")
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertIsNone(self.record()["owner"])
        self.assertEqual(self.record()["development"], item["development"])
        self.assertFalse((self.a / "worktrees/removed").exists())
        self.fake_development.prepare.assert_not_called()
        # Original associated instructions remain mandatory even after cleanup.
        self.project["main_workspace"] = {"id": "main", "name": "Main", "repository": None}
        self.write(self.a, ".project/project.yaml", store.dump_yaml(self.project))
        self.write(self.a, ".project/main-workspace.md", "Original instructions apply.\n")
        main = self.directory / "main"
        main.mkdir()
        (main / "AGENTS.md").symlink_to(self.a / "AGENTS.md")
        self.write(self.a, ".project-local/main-workspace.json", fixtures.text({"id": "main", "root": str(main)}))
        calls = len(self.calls)
        blocked = workflow.begin(self.a, "context-update", "A", publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked", blocked)
        self.assertIsNone(self.record()["owner"])
        self.assertEqual(len(self.calls), calls)

    def test_metadata_changed_after_preflight_retains_ticket_without_auto_resume(self):
        original = self.fake_development.instruction_files
        calls = []
        def changed(*args, **kwargs):
            calls.append(True)
            if len(calls) > 1:
                raise runtime.ProjectError("original instruction vanished")
            return original(*args, **kwargs)
        self.fake_development.instruction_files = changed
        blocked = workflow.begin(self.a, "context-update", "A", publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked", blocked)
        self.assertNotIn("next_command", blocked)
        self.assertIsNotNone(self.record()["owner"])
        self.fake_development.instruction_files = original
        resumed = workflow.resume(self.a, blocked["ticket"], publish=self.publisher)
        self.assertEqual(resumed["status"], "ready", resumed)
        self.edit(resumed, "Recovered context.\n")
        self.assertEqual(self.finish(resumed)["status"], "published")
        self.assertIsNone(self.record()["owner"])

    def test_cleanup_discard_preserves_contract_and_clears_old_credentials(self):
        self.designed()
        started = self.begin("development-start", skip_design_review=True, approval_source="User allows this simple contract")
        self.assertEqual(self.finish(started)["status"], "published")
        report = self.directory / "review.md"
        report.write_text("Independent implementation review.\n")
        reviewed = self.begin("development-finish", result="pass", provenance="Independent review", reviewer_session="independent", review_file=str(report))
        self.assertEqual(self.finish(reviewed)["status"], "published")
        before = self.record()
        docs = {path: (self.a / path).read_bytes() for path in [*workflow._documents(before).values(), workflow._spec(before)] if (self.a / path).exists()}
        ordinary = self.begin("cleanup-record", cleanup_status="done", reference="Worktree removed")
        self.assertEqual(self.finish(ordinary)["status"], "published")
        self.assertEqual(self.record()["development"], before["development"])
        self.assertEqual(self.record()["design"], before["design"])
        discarded = self.begin("cleanup-record", cleanup_status="done", reference="Removed old implementation", discard_development=True, approval_source="User discards this unfinished implementation")
        self.assertEqual(self.finish(discarded)["status"], "published")
        after = self.record()
        for key in ("repository", "kind", "depends_on", "delivery"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["design"]["approval"], before["design"]["approval"])
        self.assertEqual(after["design"]["version"], before["design"]["version"])
        self.assertEqual(after["design"]["state"], "review-pending")
        self.assertNotIn("review", after["design"])
        self.assertNotIn("design_waiver", after["workflow"])
        self.assertIsNone(after["development"])
        self.assertIsNone(after["owner"])
        self.assertEqual(after["status"], "in_progress")
        for path, text in docs.items():
            self.assertEqual((self.a / path).read_bytes(), text, path)
        record_path = self.a / ("workitems/A/records/" + discarded["ticket"] + ".yaml")
        historical = store.load_yaml(record_path.read_bytes())
        self.assertEqual(historical["development_snapshot"], before["development"])
        self.assertEqual(historical["approval_source"], "User discards this unfinished implementation")
        self.assertNotIn("token", record_path.read_text())
        for old in (before["design"]["review"]["id"], before["development"]["review"]["id"], before["workflow"]["design_waiver"]["id"], ordinary["ticket"]):
            self.assertFalse((self.a / ("workitems/A/records/" + old + ".yaml")).exists())
        blocked = workflow.begin(self.a, "development-start", "A", publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked", blocked)
        self.assertIn("independent design review", blocked["message"])

    def test_cleanup_discard_rejects_invalid_options_owner_and_recreated_tree(self):
        import project as command
        parsed = command.parser().parse_args(["begin", "cleanup-record", "A", "--cleanup-status", "done", "--reference", "Removed", "--discard-development", "--approval-source", "Explicit discard"])
        valid = command._begin_options(parsed)
        self.assertIs(valid["discard_development"], True)
        plain = command.parser().parse_args(["begin", "cleanup-record", "A", "--cleanup-status", "done", "--reference", "Removed"])
        self.assertNotIn("discard_development", command._begin_options(plain))
        item = self.record()
        item["development"] = {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": "a" * 40}
        self.install(item)
        for invalid in ({"approval_source": None}, {"cleanup_status": "pending"}, {"mode": "skipped"}, {"discard_development": "true"}):
            with self.subTest(invalid=invalid):
                blocked = workflow.begin(self.a, "cleanup-record", "A", options={**valid, **invalid}, publish=self.publisher)
                self.assertEqual(blocked["status"], "blocked", blocked)
                self.assertIsNone(self.record()["owner"])
        location = self.directory / "fake-code"
        location.mkdir()
        self.assertEqual(workflow.begin(self.a, "cleanup-record", "A", options=valid, publish=self.publisher)["status"], "blocked")
        self.assertIsNone(self.record()["owner"])
        location.rmdir()
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "foreign"}):
            item["owner"] = workflow._identity(self.a)
        self.install(item)
        self.assertEqual(workflow.begin(self.a, "cleanup-record", "A", options=valid, publish=self.publisher)["code"], "owner_conflict")
        item["owner"] = None
        item.update(status="done", delivery={"required": ["merged"], "status": "delivered", "evidence": [{"kind": "merged", "reference": "sha"}]})
        self.install(item)
        self.assertEqual(workflow.begin(self.a, "cleanup-record", "A", options=valid, publish=self.publisher)["status"], "blocked")
        self.assertIsNone(self.record()["owner"])
        item.update(status="in_progress", delivery={"required": ["merged"], "status": "pending", "evidence": []})
        self.install(item)
        ready = self.begin("cleanup-record", **valid)
        location.mkdir()
        self.assertEqual(self.finish(ready)["status"], "blocked")
        self.assertEqual(self.record()["development"], item["development"])
        location.rmdir()
        self.assertEqual(self.finish(ready)["status"], "published")
        self.assertEqual(self.record()["design"]["state"], "draft")
        cancelled = self.record("B")
        cancelled.update(status="cancelled", development={"worktree": "worktrees/B", "branch": "feature/B", "base_commit": "a" * 40})
        self.install(cancelled)
        discarded = self.begin("cleanup-record", "B", **valid)
        self.assertEqual(self.finish(discarded)["status"], "published")
        self.assertEqual(self.record("B")["status"], "cancelled")
        self.assertIsNone(self.record("B")["development"])

    def test_awaiting_delivery_can_add_actual_implementation_review_without_design_pass(self):
        item = self.record()
        item["status"] = "awaiting_delivery"
        item["design"].update(state="review-pending", version=1)
        self.write(self.a, "workitems/A/spec.md", "# Historical reviewed design\n")
        item["development"] = {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": "a" * 40}
        self.install(item)
        report = self.directory / "legacy-review.md"
        report.write_text("Independent review of actual current implementation.\n")
        result = self.begin("development-finish", result="pass", provenance="Actual independent reviewer", reviewer_session="fresh-reviewer", review_file=str(report))
        self.assertEqual(self.finish(result)["status"], "published")
        self.assertEqual(self.record()["status"], "awaiting_delivery")
        self.assertEqual(self.record()["design"]["state"], "review-pending")
        self.assertEqual(self.record()["development"]["review"]["session"], "fresh-reviewer")

    def test_developing_requirement_change_blocks_old_and_new_implementation_review(self):
        start = self.begin("development-start", skip_design_review=True, approval_source="User explicitly waives this simple requirement's design review")
        self.assertEqual(self.finish(start)["status"], "published")
        report = self.directory / "implementation-review.md"
        report.write_text("Independent reviewer checked the original implementation scope.\n")
        options = {"result": "pass", "provenance": "Actual independent reviewer", "reviewer_session": "independent", "review_file": str(report)}
        review = self.begin("development-finish", **options)
        change = self.begin("requirement-update")
        self.edit(change, "Expanded requirement invalidates the original user-authorized scope.\n")
        self.assertEqual(self.finish(change)["status"], "published")
        self.assertEqual(self.finish(review)["status"], "blocked")
        fresh_review = workflow.begin(self.a, "development-finish", "A", options=options, publish=self.publisher)
        self.assertEqual(fresh_review["status"], "blocked", fresh_review)
        self.assertEqual(fresh_review["code"], "approval_required")
        self.assertEqual(self.record()["status"], "developing")
        self.assertIsNotNone(self.record()["owner"])
        self.assertNotIn("review", self.record()["development"])

    def test_changed_awaiting_delivery_contract_requires_design_gate_again(self):
        item = self.record()
        item["status"] = "awaiting_delivery"
        item["design"].update(state="review-pending", version=1)
        self.write(self.a, "workitems/A/spec.md", "# Historical approved scope\n")
        historical_review = {"id": "historical", "kind": "development-finish", "item": "A", "result": "pass",
                             "report": "workitems/A/records/historical.md"}
        self.write(self.a, "workitems/A/records/historical.md", "Current independent review of the unchanged scope.\n")
        self.write(self.a, "workitems/A/records/historical.yaml", store.dump_yaml(historical_review))
        item["development"] = {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": "a" * 40,
                               "review": historical_review, "reviewed_snapshot": {"head": "a" * 40}}
        self.install(item)
        unchanged = self.begin("requirement-update")
        self.assertEqual(self.finish(unchanged)["status"], "published")
        self.assertEqual(self.record()["status"], "awaiting_delivery")
        change = self.begin("requirement-update")
        self.edit(change, "Changed contract requires a new approved implementation scope.\n")
        self.assertEqual(self.finish(change)["status"], "published")
        self.assertEqual(self.record()["status"], "in_progress")
        self.assertNotIn("review", self.record()["development"])
        self.assertNotIn("reviewed_snapshot", self.record()["development"])
        self.assertFalse((self.a / "workitems/A/records/historical.yaml").exists())
        self.assertFalse((self.a / "workitems/A/records/historical.md").exists())
        report = self.directory / "new-review.md"
        report.write_text("Fresh reviewer report cannot waive the new design approval.\n")
        blocked = workflow.begin(self.a, "development-finish", "A", options={"result": "pass", "provenance": "Actual reviewer", "reviewer_session": "independent", "review_file": str(report)}, publish=self.publisher)
        self.assertEqual(blocked["status"], "blocked", blocked)
        self.assertEqual(blocked["code"], "approval_required")

    def test_prepared_code_location_survives_kind_change_until_verified_absence(self):
        location = self.directory / "fake-code"
        location.mkdir()
        item = self.record()
        item["status"] = "in_progress"
        item["cleanup"] = "not_applicable"
        item["development"] = {"worktree": "worktrees/A", "branch": "feature/A", "base_commit": "a" * 40}
        self.install(item)
        original = copy.deepcopy(item["development"])
        change = self.begin("kind-update", kind="aggregate")
        self.assertEqual(self.finish(change)["status"], "blocked")
        self.assertEqual(self.record()["development"], original)
        self.assertEqual(self.record()["kind"], "development")
        self.assertTrue(location.is_dir())
        item = self.record()
        item["cleanup"] = "done"
        self.install(item)
        claimed_cleanup = self.begin("kind-update", kind="aggregate")
        self.assertEqual(self.finish(claimed_cleanup)["status"], "blocked")
        self.assertEqual(self.record()["development"], original)
        location.rmdir()
        absent = self.begin("kind-update", kind="aggregate")
        self.assertEqual(self.finish(absent)["status"], "published")
        self.assertEqual(self.record()["kind"], "aggregate")
        self.assertIsNone(self.record()["development"])
        self.assertIsNone(self.record()["repository"])
        self.assertEqual(self.record()["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
