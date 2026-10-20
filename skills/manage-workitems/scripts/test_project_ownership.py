"""Dead-conversation recovery preserves work and fences superseded control claims."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import project
import project_autonomy as autonomy
import project_ownership as ownership
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_autonomy as helpers


class OwnershipTest(unittest.TestCase):
    def setUp(self):
        self.a = helpers.AutonomyTest("runTest")
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.f, self.root = self.a.f, self.a.root
        original = self.f.publisher

        def guarded(root, writes, identity, message, checks=None):
            files = runtime._working_files(root)
            bundle = project._bundle(files, writes, identity, message, [], checks)
            runtime._check_owners(bundle, files, store.apply_writes(files, writes))
            return original(root, writes, identity, message, checks)

        self.f.publisher = guarded

    def takeover(self, **options):
        result = ownership.takeover(self.root, "A", approval_source="User explicitly transfers control after the old conversation ended",
                                    publish=self.f.publisher, **options)
        self.assertIn(result["status"], {"published", "no_op"}, result)
        return result

    def test_manual_draft_is_retained_and_old_ticket_cannot_finish(self):
        draft = self.f.begin("context-update")
        self.f.edit(draft, "Unpublished useful context.\n")
        path = Path(draft["editable"][0]["path"])
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "new-controller"}):
            self.takeover()
            self.assertEqual(path.read_text(), "Unpublished useful context.\n")
            fresh = self.f.begin("context-update")
            self.f.edit(fresh, path.read_text())
            self.assertEqual(self.f.finish(fresh)["status"], "published")
        failed = self.f.finish(draft)
        self.assertEqual(failed["status"], "blocked", failed)

    def test_real_publication_rejects_stale_controller_and_unrelated_transfer_writes(self):
        draft = self.f.begin("context-update")
        old_identity = workflow._identity(self.root, item="A")
        self.f.commit("publish existing control claim")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "new-controller"}):
            process = subprocess.run([sys.executable, project.__file__, "--root", str(self.root), "takeover", "A",
                "--approval-source", "User explicitly preempts the ended conversation"], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            result = json.loads(process.stdout)
            self.assertEqual(result["status"], "published", result)
        files = runtime._working_files(self.root)
        item = self.f.record()
        writes = store.write_item(files, item)
        bundle = project._bundle(files, writes, old_identity, "Stale controller", [], workflow._checks(files, item, "context-update"))
        with self.assertRaisesRegex(runtime.ProjectError, "control claim"):
            project._publish(self.root, bundle)
        event = next(iter(item["workflow"]["control_transfers"].values()))
        # An already-applied event cannot be replayed to smuggle a business write.
        bundle.update(session=event["to"]["session"], token=event["to"]["token"],
                      ownership_transfer={"item": "A", "id": event["id"]})
        bundle["writes"]["workitems/A/context.md"] = "Unrelated mutation\n"
        with self.assertRaises(runtime.ProjectError):
            runtime._check_owners(bundle, files, store.apply_writes(files, bundle["writes"]))

    def test_same_control_token_allows_audit_identity_change(self):
        self.a.approved()
        self.a.authorize()
        identity = workflow._identity(self.root, item="A")
        same_claim = {**identity, "session": "different-audit-session"}
        item = self.f.record()
        workflow._ownership(item, same_claim)
        self.assertTrue(ownership.authorized(item, same_claim))

    def test_returning_controller_never_reactivates_old_token_or_draft(self):
        draft = self.f.begin("context-update")
        original = workflow._identity(self.root, item="A")
        unrelated = self.f.begin("context-update", "B")
        self.f.edit(unrelated, "Unrelated work keeps its existing claim.\n")
        unrelated_before = copy.deepcopy(self.f.record("B"))
        unrelated_identity = workflow._identity(self.root, item="B")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "other-controller"}):
            self.takeover()
        self.takeover()
        current = workflow._identity(self.root, item="A")
        self.assertNotEqual(current["token"], original["token"])
        self.assertEqual(workflow._identity(self.root, item="B"), unrelated_identity)
        self.assertEqual(self.f.record("B"), unrelated_before)
        self.assertEqual(self.f.finish(unrelated)["status"], "published")
        files = runtime._working_files(self.root)
        item = self.f.record()
        bundle = project._bundle(files, {"workitems/A/context.md": "Old controller edit\n"}, original,
            "Old intent with fresh byte guards", [], workflow._checks(files, item, "context-update"))
        with self.assertRaisesRegex(runtime.ProjectError, "control claim"):
            runtime._check_owners(bundle, files, store.apply_writes(files, bundle["writes"]))
        self.assertEqual(self.f.finish(draft)["status"], "blocked")
        self.assertEqual(self.f.finish(self.f.begin("context-update"))["status"], "published")

    def test_legacy_authorization_without_owner_requires_explicit_transfer(self):
        self.a.approved()
        self.a.authorize()
        self.a.finish_execution(self.a.dispatch("design-review", "design-reviewer"))
        before = self.f.record()
        self.assertIsNone(before["owner"])
        before["workflow"]["autonomy"]["authorization"].pop("claim_token")
        self.f.install(before)
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "new-controller"}):
            denied = workflow.begin(self.root, "context-update", "A", publish=self.f.publisher)
            self.assertEqual(denied["status"], "blocked", denied)
            self.assertEqual(denied["action_code"], "control_claim_required")
            files = runtime._working_files(self.root)
            bundle = project._bundle(files, {"workitems/A/context.md": "Unauthorized context edit\n"},
                workflow._identity(self.root, item="A"), "Unauthorized edit", [], workflow._checks(files, before, "context-update"))
            with self.assertRaisesRegex(runtime.ProjectError, "control claim"):
                runtime._check_owners(bundle, files, store.apply_writes(files, bundle["writes"]))
            self.assertEqual(self.f.record(), before)
            self.takeover()
            self.assertEqual(self.a.state()["next_role"], "implementation")

    def test_cross_host_takeover_clears_legacy_executor_lock_and_preserves_code(self):
        self.a.approved()
        self.a.authorize()
        self.a.finish_execution(self.a.dispatch("design-review", "design-reviewer"))
        self.a.dispatch("implementation", "original-author")
        old = self.f.record()
        old_identity = workflow._identity(self.root, item="A")
        state = old["workflow"]["autonomy"]
        state.update(current="0" * 32, executions={"0" * 32: {"worker_id": "unreachable-qoder-worker", "spawn": {"host": "qoder"}}}, blocker="executor_blocked", next_role="implementation", code_authors=["prior-author"])
        state["authorization"].pop("claim_token")
        self.f.install(old)
        self.a.snapshot.update(tree="d" * 40, dirty_digest="d" * 64)
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "new-codex-controller"}):
            response = self.takeover()
            self.assertEqual(response["next_action"], "recompute_readiness")
            saved = self.f.record()
            self.assertEqual(saved["development"], old["development"])
            self.assertEqual(saved["design"], old["design"])
            self.assertIn("prior-author", saved["workflow"]["code_authors"])
            self.assertFalse({"current", "executions", "blocker", "next_role"} & saved["workflow"]["autonomy"].keys())
            self.assertNotEqual(saved["owner"]["token"], old_identity["token"])
            self.a.finish_execution(self.a.dispatch("implementation", "current-author"))
            self.assertEqual(self.a.state()["next_role"], "code-review")
            self.a.finish_execution(self.a.dispatch("code-review", "independent-reviewer"))
            self.assertEqual(self.a.state()["state"], "awaiting_acceptance")
        with self.assertRaisesRegex(runtime.ProjectError, "control claim"):
            autonomy.accept(self.root, "A", approval_source="Old controller cannot write", publish=self.f.publisher)

    def test_already_owned_takeover_releases_legacy_lock_without_stop_confirmation(self):
        self.a.approved()
        self.a.authorize()
        record = self.f.record()
        record["workflow"]["autonomy"].update(current="0" * 32, executions={})
        self.f.install(record)
        self.takeover()
        self.assertNotIn("current", self.f.record()["workflow"]["autonomy"])
        self.assertEqual(self.takeover()["status"], "no_op")

    def test_takeover_preserves_legacy_review_guards_and_completed_work_product(self):
        self.a.reviewed()
        record = self.f.record()
        state = record["workflow"]["autonomy"]
        product = state.pop("implementation")
        state.pop("implementation_basis")
        review = record["development"]["review"]
        hashes = review.pop("read_hashes")
        review["execution"] = "1" * 32
        state["executions"] = {
            "1" * 32: {"input_binding": {"project_sha256": product["binding"]["project_sha256"]}, "read_hashes": hashes},
            "2" * 32: {"role": "implementation", "finished_at": product["created_at"],
                "result": {"outcome": "pass"}, "report": product["report"], "output_binding": product["binding"]}}
        self.f.write(self.root, "workitems/A/records/" + review["id"] + ".yaml", store.dump_yaml(review))
        self.f.install(record)
        self.assertEqual(self.a.state()["state"], "awaiting_acceptance")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "receiving-controller"}):
            self.takeover()
            saved = self.f.record()
            self.assertNotIn("executions", saved["workflow"]["autonomy"])
            self.assertEqual(saved["development"]["review"], review)
            self.assertEqual(saved["workflow"]["autonomy"]["implementation"]["binding"], product["binding"])
            self.assertEqual(self.a.state()["state"], "awaiting_acceptance")
            self.assertTrue(saved["workflow"]["review_guards"][review["id"]]["read_hashes"])
            files = runtime._working_files(self.root)
            workflow._implementation_approved(files, saved)
            self.f.write(self.root, ".project/business-instructions.md", "Changed original instructions.\n")
            with self.assertRaises(runtime.ProjectError):
                workflow._implementation_approved(runtime._working_files(self.root), self.f.record())

    def test_mixed_scope_keeps_other_claims_and_reports_only_confirmed_authorizations(self):
        for identifier in ("A", "B"):
            self.a.approved(identifier)
        self.a.authorize()
        identity_b = workflow._identity(self.root, item="B")
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "receiving-controller"}):
            self.takeover()
            response = autonomy.authorize(self.root, all_items=True, approval_source="User continues both items", publish=self.f.publisher)
            self.assertEqual(response["authorized"], ["A", "B"])
            self.assertEqual(len(response["publications"]), 2)
            calls = []

            def partial(root, writes, identity, message, checks=None):
                calls.append(identity["token"])
                return {"status": "partial", "recovery": {"identity_file": "/tmp/immutable-intent.json"}}

            response = autonomy.authorize(self.root, all_items=True, approval_source="Same scoped instruction", publish=partial)
            self.assertEqual(response["authorized"], [])
            self.assertEqual(response["pending_authorization"], ["A"])
            self.assertEqual(response["remaining_items"], ["A", "B"])
            self.assertEqual(len(calls), 1)
        self.assertEqual(workflow._identity(self.root, item="B"), identity_b)

    def test_pending_project_intent_recovers_without_live_old_controller(self):
        self.f.begin("context-update")
        original = workflow._identity(self.root, item="A")
        directory = self.root / ".project-local/publish" / ("1" * 32)
        directory.mkdir(parents=True)
        runtime._write_journal(directory / "journal.json", {"state": "push_pending"})
        runtime._write_journal(directory / "bundle.json", {**original, "writes": {"workitems/A/context.md": "Immutable intended content"}})
        before = self.f.record()
        with mock.patch.dict(os.environ, {"PROJECT_SESSION_ID": "receiving-controller"}):
            result = ownership.takeover(self.root, "A", approval_source="User continues A", publish=self.f.publisher)
        self.assertEqual(result["code"], "takeover_publication_pending")
        import shlex
        command = shlex.split(result["next_command"])
        identity = runtime.read_json(command[command.index("--identity-file") + 1])
        self.assertEqual(identity, {key: original[key] for key in ("session", "token")})
        self.assertEqual(command[-2:], ["--journal", str(directory / "journal.json")])
        self.assertEqual(self.f.record(), before)


if __name__ == "__main__":
    unittest.main()
