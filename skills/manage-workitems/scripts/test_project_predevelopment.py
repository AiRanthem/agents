"""Opt-in snapshots and convergence with real Git and local bare remotes."""
import copy
from pathlib import Path
import unittest
from unittest import mock
import project
import project_autonomy as autonomy
import project_development as development
import project_predevelopment as predevelopment
import project_retention as retention
import project_runtime as runtime
import project_store as store
import project_workflow as workflow
import test_project_autonomy as helpers

git = helpers.workflow_tests.fixtures.git


class PredevelopmentTest(unittest.TestCase):
    approved = helpers.AutonomyTest.approved
    receipt = helpers.AutonomyTest.receipt
    dispatch = helpers.AutonomyTest.dispatch

    def setUp(self):
        helper = helpers.AutonomyTest("runTest")
        self.addCleanup(helper.doCleanups)
        helper.setUp()
        self.f, self.root = helper.f, helper.root
        self.f.development_patch.stop()
        self.remote = self.f.directory / "code.git"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "--quiet", "--initial-branch=main")
        git(self.remote, "config", "core.hooksPath", str(self.remote / "hooks"))
        self.code = self.f.directory / "code"
        self.code.mkdir()
        git(self.code, "init", "--quiet", "--initial-branch=main")
        self.f.configure(self.code)
        (self.code / "base.txt").write_text("base\n")
        (self.code / "AGENTS.md").write_text("Preserve the contract; verify the resulting tree.\n")
        git(self.code, "add", ".")
        git(self.code, "commit", "--quiet", "-m", "formal base")
        git(self.code, "remote", "add", "upstream", str(self.remote))
        git(self.code, "config", "remote.upstream.push", "refs/heads/*:refs/heads/devkits/*")
        git(self.code, "push", "--quiet", "upstream", "main:refs/heads/devkits/main")
        self.base = git(self.code, "rev-parse", "HEAD")
        self.f.project["repositories"] = [{"id": "code", "url": str(self.remote),
            "base_ref": "refs/heads/devkits/main", "base_remote": "upstream"}]
        self.f.write(self.root, ".project/project.yaml", store.dump_yaml(self.f.project))
        self.f.write(self.root, ".project-local/repositories.yaml", store.dump_yaml({"code": str(self.code)}))
        self.f.commit("bind source repository")

    def item(self, identifier):
        return self.f.record(identifier)

    def state(self, identifier):
        return autonomy.status(self.root, items=[identifier])["items"][0]

    def configure(self, identifier, dependencies=(), repository="code"):
        if identifier not in store.items(runtime._working_files(self.root)):
            record = copy.deepcopy(self.item("A"))
            record.update(id=identifier, title=identifier)
            record.pop("workflow", None)
            record["design"] = {"file": "spec.md", "version": 0, "state": "draft"}
            self.f.write(self.root, "workitems/" + identifier + "/requirement.md", "Requirement " + identifier + "\n")
            self.f.write(self.root, "workitems/" + identifier + "/context.md", "Context\n")
        else:
            record = self.item(identifier)
        record.update(depends_on=list(dependencies), development=None, repository=repository)
        for name, body in store.write_item(runtime._working_files(self.root), record).items():
            self.f.write(self.root, name, body)
        self.approved(identifier)

    def authorize(self, *identifiers, enabled=True):
        result = autonomy.authorize(self.root, items=list(identifiers), predevelop=enabled,
            approval_source="Explicit test opt-in scope", publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)

    def finish(self, identifier, execution, **options):
        result = autonomy.result(self.root, identifier, receipt=self.receipt(execution, **options), publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)

    def develop(self, identifier):
        for role in ("design-review", "implementation", "code-review"):
            execution = self.dispatch(role, identifier + "-" + role + "-" + str(len(self.f.calls)), identifier)
            if role == "implementation":
                worktree = Path(execution["code_context"]["worktree"])
                (worktree / (identifier + ".txt")).write_text(identifier + " implementation\n")
            self.finish(identifier, execution)
        return worktree

    def prepare(self, identifier):
        result = predevelopment.prepare(self.root, identifier, publish=self.f.publisher)
        self.assertIn(result["status"], {"published", "no_op"}, result)
        return result

    def deliver(self, identifier):
        result = autonomy.accept(self.root, identifier, approval_source="Human accepts this exact version", publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        location = development.worktree_location(self.root, self.item(identifier), self.f.project)
        git(location, "add", ".")
        git(location, "commit", "--quiet", "-m", "accepted " + identifier)
        commit = git(location, "rev-parse", "HEAD")
        git(self.code, "merge", "--quiet", "--ff-only", commit)
        git(self.code, "push", "--quiet", "upstream", "main:refs/heads/devkits/main")
        checkpoint = self.f.begin("delivery-record", identifier, kind=["merged"], reference=[commit], commit=commit,
                                  provenance="Actual human acceptance and local-remote merge verification")
        self.f.edit(checkpoint, "Actual accepted source merged into configured formal target.\n")
        self.assertEqual(self.f.finish(checkpoint)["status"], "published")
        self.assertTrue(autonomy._acceptance_valid(self.root, runtime._working_files(self.root), self.item(identifier)))

    def test_opt_in_dirty_snapshot_preserves_original_and_frozen_inputs(self):
        self.configure("A")
        self.configure("B", ["A"])
        self.authorize("A", "B", enabled=False)
        source = self.develop("A")
        self.assertEqual(self.state("B")["state"], "blocked")
        with self.assertRaisesRegex(runtime.ProjectError, "explicit"):
            predevelopment.snapshot(self.root, "A", publish=self.f.publisher)
        self.authorize("A", "B")
        (source / "base.txt").write_text("staged\n")
        git(source, "add", "base.txt")
        (source / "base.txt").write_text("unstaged\n")
        (source / "extra.txt").write_text("untracked\n")
        self.finish("A", self.dispatch("code-review", "updated-review", "A"))
        before = (git(source, "rev-parse", "HEAD"), git(source, "status", "--porcelain"),
                  git(source, "diff", "--cached"), git(source, "diff"))
        self.assertEqual(self.state("B")["next_action"], "prepare")
        self.prepare("B")
        captured = predevelopment._latest(self.item("A"))
        self.assertEqual(before, (git(source, "rev-parse", "HEAD"), git(source, "status", "--porcelain"),
                                 git(source, "diff", "--cached"), git(source, "diff")))
        self.assertEqual(git(self.remote, "show", captured["commit"] + ":base.txt"), "unstaged")
        self.assertEqual(git(self.remote, "show", captured["commit"] + ":extra.txt"), "untracked")
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/devkits/main"), self.base)
        self.assertTrue(captured["ref"].startswith("refs/heads/devkits/snapshots/"))
        self.assertEqual(git(self.remote, "rev-parse", captured["ref"]), captured["commit"])
        self.assertIn(captured["report"], retention.live_record_paths(runtime._working_files(self.root), "A"))
        self.f.write(self.root, "workitems/A/spec.md", "Human reconsideration after freeze\n")
        self.f.write(self.root, "workitems/A/requirement.md", "Changed human input\n")
        self.assertEqual(self.state("B")["next_role"], "design-review")
        execution = self.dispatch("design-review", "frozen-input-review", "B")
        self.assertIn(captured["report"], "\n".join(value["path"] for value in execution["read"]))
        self.assertFalse(any(value["path"].endswith("workitems/A/spec.md") for value in execution["read"]))
        self.finish("B", execution)
        for action in ("snapshot", "prepare"):
            parsed = project.parser().parse_args(["--root", str(self.root), "autonomy", action, "B"])
            self.assertEqual(parsed.autonomy_action, action)

    def test_chain_waits_for_delivery_and_requires_fresh_formal_reviews(self):
        for identifier, dependencies in (("A", []), ("B", ["A"]), ("C", ["B"])):
            self.configure(identifier, dependencies)
        self.f.commit("initial approved scope")
        self.authorize("A", "B", "C")
        a = self.develop("A")
        self.f.commit("capture completed upstream fixture")
        self.f.real_publish = True
        self.prepare("B")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), git(self.f.remote, "rev-parse", "refs/heads/main"))
        self.f.real_publish = False
        b = self.develop("B")
        self.assertEqual(self.state("B")["state"], "awaiting_predecessor_delivery")
        with self.assertRaisesRegex(runtime.ProjectError, "formal convergence"):
            autonomy.accept(self.root, "B", approval_source="Cannot accept speculative", publish=self.f.publisher)
        inherited = predevelopment.pins(self.item("B"))["A"]["id"]
        (a / "human-update.txt").write_text("Human update after the first freeze\n")
        self.finish("A", self.dispatch("code-review", "human-update-review", "A"))
        newer = predevelopment.snapshot(self.root, "A", publish=self.f.publisher)["snapshot"]
        self.assertNotEqual(inherited, newer["id"])
        self.prepare("C")
        c = self.develop("C")
        self.assertEqual(set(predevelopment.pins(self.item("C"))), {"A", "B"})
        self.assertEqual(predevelopment.pins(self.item("C"))["A"]["id"], inherited)
        self.assertFalse((c / "human-update.txt").exists())
        self.assertEqual(self.state("C")["state"], "awaiting_predecessor_delivery")
        self.assertTrue((c / "A.txt").exists() and (c / "B.txt").exists())
        autonomy.accept(self.root, "A", approval_source="Human accepts A", publish=self.f.publisher)
        self.assertEqual(self.state("B")["state"], "awaiting_predecessor_delivery")
        self.deliver("A")
        autonomy.authorize(self.root, items=["B"], predevelop=True, skip_design_review=True,
            approval_source="Advance B with initial design review waived", publish=self.f.publisher)
        self.assertEqual(self.state("B")["next_action"], "prepare")
        with self.assertRaisesRegex(runtime.ProjectError, "formal convergence"):
            workflow._blocked(store.items(runtime._working_files(self.root)), "B")
        old_snapshot = development.snapshot(b)
        self.prepare("B")
        rebase = self.dispatch("rebase", "formal-rebaser", "B")
        formal = Path(rebase["code_context"]["worktree"])
        self.assertNotEqual(formal, b)
        operation = rebase["git_operation"]
        git(formal, "rebase", "--onto", operation["target"], operation["old_base"])
        self.finish("B", rebase)
        self.assertEqual(development.snapshot(b), old_snapshot)
        self.assertEqual(git(formal, "rev-parse", "HEAD"), operation["target"])
        self.assertIn("B.txt", git(formal, "status", "--porcelain"))
        self.assertTrue((formal / "human-update.txt").exists())
        self.assertEqual(self.state("B")["next_role"], "design-review")
        with self.assertRaises(runtime.ProjectError):
            self.dispatch("code-review", "cannot-skip-design", "B")
        self.develop("B")
        self.assertEqual(predevelopment.state(self.item("B"))["phase"], "formal")
        for key in ("rebased", "base"):
            corrupt = copy.deepcopy(self.item("B"))
            if key == "rebased":
                predevelopment.state(corrupt)["rebased"] = False
            else:
                corrupt["development"]["base_commit"] = self.base
            with self.subTest(corruption=key), self.assertRaisesRegex(runtime.ProjectError, "completed rebase"):
                predevelopment.validate(corrupt)
        self.assertEqual(self.state("B")["state"], "awaiting_acceptance")
        self.assertEqual(self.state("C")["state"], "awaiting_predecessor_delivery")
        self.deliver("B")
        self.assertEqual(self.state("C")["next_action"], "prepare")

    def test_snapshot_uncertain_publication_reuses_identity_and_ref_is_immutable(self):
        self.configure("A")
        self.authorize("A")
        self.develop("A")
        original_git = development._git
        failed = False
        def uncertain(checkout, *args, **kwargs):
            nonlocal failed
            result = original_git(checkout, *args, **kwargs)
            if args and args[0] == "push" and not failed:
                failed = True
                raise runtime.ProjectError("network lost after remote accepted snapshot")
            return result
        with mock.patch.object(development, "_git", side_effect=uncertain), self.assertRaisesRegex(runtime.ProjectError, "network lost"):
            predevelopment.snapshot(self.root, "A", publish=self.f.publisher)
        saved = next(iter(self.item("A")["workflow"]["autonomy"]["snapshots"].values()))
        self.assertEqual(saved["status"], "committed")
        outcome = predevelopment.snapshot(self.root, "A", publish=self.f.publisher)
        self.assertEqual(outcome["snapshot"]["id"], saved["id"])
        self.assertEqual(outcome["snapshot"]["commit"], saved["commit"])
        self.assertEqual(len(self.item("A")["workflow"]["autonomy"]["snapshots"]), 1)
        git(self.remote, "update-ref", saved["ref"], self.base)
        with self.assertRaisesRegex(runtime.ProjectError, "identity changed"):
            predevelopment._fetch(self.code, outcome["snapshot"])

    def test_all_same_repository_prerequisites_must_be_integrated(self):
        for identifier, dependencies in (("A", []), ("B", []), ("C", ["A", "B"])):
            self.configure(identifier, dependencies)
        self.authorize("A", "B", "C")
        self.develop("A")
        self.develop("B")
        self.prepare("C")
        self.assertEqual(self.state("C")["next_role"], "baseline")
        execution = self.dispatch("baseline", "baseline-integrator", "C")
        location = Path(execution["code_context"]["worktree"])
        receipt = self.receipt(execution)
        branch = git(location, "symbolic-ref", "--short", "HEAD")
        git(location, "checkout", "--quiet", "-b", "unassigned-writer-branch")
        with self.assertRaisesRegex(runtime.ProjectError, "changed branches"):
            autonomy.result(self.root, "C", receipt=receipt, publish=self.f.publisher)
        self.assertEqual(git(location, "symbolic-ref", "--short", "HEAD"), "unassigned-writer-branch")
        git(location, "checkout", "--quiet", branch)
        with self.assertRaisesRegex(runtime.ProjectError, "omits"):
            autonomy.result(self.root, "C", receipt=receipt, publish=self.f.publisher)
        for commit in execution["git_operation"]["commits"]:
            git(location, "merge", "--quiet", "--no-edit", commit)
        result = autonomy.result(self.root, "C", receipt=receipt, publish=self.f.publisher)
        self.assertEqual(result["status"], "published", result)
        self.assertTrue((location / "A.txt").exists() and (location / "B.txt").exists())
        self.assertEqual(self.state("C")["next_role"], "design-review")

    def test_foreign_prerequisite_is_pinned_without_merging_its_source(self):
        remote = self.f.directory / "foreign.git"
        remote.mkdir()
        git(remote, "init", "--bare", "--quiet", "--initial-branch=main")
        git(self.code, "push", "--quiet", str(remote), "main:refs/heads/devkits/main")
        checkout = self.f.directory / "foreign"
        git(self.code, "clone", "--quiet", "--branch", "devkits/main", str(remote), str(checkout))
        self.f.configure(checkout)
        git(checkout, "remote", "rename", "origin", "upstream")
        self.f.project["repositories"].append({"id": "foreign", "url": str(remote),
            "base_remote": "upstream", "base_ref": "refs/heads/devkits/main"})
        self.f.write(self.root, ".project/project.yaml", store.dump_yaml(self.f.project))
        self.f.write(self.root, ".project-local/repositories.yaml", store.dump_yaml({"code": str(self.code), "foreign": str(checkout)}))
        self.configure("A", repository="foreign")
        self.configure("B", ["A"])
        self.authorize("A", "B")
        self.develop("A")
        self.prepare("B")
        self.assertEqual(self.state("B")["next_role"], "design-review")
        execution = self.dispatch("design-review", "foreign-contract-review", "B")
        self.assertEqual(execution["prerequisites"]["A"]["repository"], "foreign")
        self.assertFalse((Path(execution["code_context"]["worktree"]) / "A.txt").exists())
        self.finish("B", execution)

    def test_frozen_and_delivered_dependencies_share_the_pinned_formal_base(self):
        for identifier, dependencies in (("A", []), ("B", []), ("C", ["A", "B"])):
            self.configure(identifier, dependencies)
        self.authorize("A", "B", "C")
        self.develop("A")
        self.develop("B")
        self.deliver("B")
        formal = git(self.code, "rev-parse", "HEAD")
        with mock.patch.object(predevelopment, "_new_worktree", side_effect=runtime.ProjectError("interrupted creation")):
            with self.assertRaisesRegex(runtime.ProjectError, "interrupted creation"):
                self.prepare("C")
        (self.code / "later.txt").write_text("Unrelated later formal change\n")
        git(self.code, "add", ".")
        git(self.code, "commit", "--quiet", "-m", "advance formal after generation was pinned")
        git(self.code, "push", "--quiet", "upstream", "main:refs/heads/devkits/main")
        self.prepare("C")
        location = development.worktree_location(self.root, self.item("C"), self.f.project)
        self.assertTrue((location / "B.txt").is_file())
        self.assertFalse((location / "later.txt").exists())
        self.assertEqual(self.state("C")["next_role"], "baseline")
        execution = self.dispatch("baseline", "mixed-baseline", "C")
        self.assertIn(formal, execution["git_operation"]["commits"])
        for commit in execution["git_operation"]["commits"]:
            git(location, "merge", "--quiet", "--no-edit", commit)
        self.finish("C", execution)
        self.assertTrue((location / "A.txt").is_file())
        self.assertTrue((location / "B.txt").is_file())
        self.assertEqual(self.state("C")["next_role"], "design-review")

    def test_conflicted_baseline_can_record_a_blocked_terminal_result(self):
        for identifier, dependencies in (("A", []), ("B", []), ("C", ["A", "B"])):
            self.configure(identifier, dependencies)
        self.authorize("A", "B", "C")
        for identifier in ("A", "B"):
            source = self.develop(identifier)
            (source / "base.txt").write_text(identifier + " conflicting change\n")
            self.finish(identifier, self.dispatch("code-review", identifier + "-conflict-review", identifier))
        self.prepare("C")
        execution = self.dispatch("baseline", "conflicted-baseline", "C")
        location = Path(execution["code_context"]["worktree"])
        commits = execution["git_operation"]["commits"]
        for commit in commits:
            merged = development._git(location, "merge", "--quiet", "--no-edit", commit, check=False)
            if merged.returncode:
                break
        self.assertNotEqual(merged.returncode, 0)
        conflicts = git(location, "ls-files", "--unmerged")
        self.assertTrue(conflicts)
        with self.assertRaisesRegex(runtime.ProjectError, "resolved index conflicts"):
            autonomy.result(self.root, "C", receipt=self.receipt(execution), publish=self.f.publisher)
        receipt = self.receipt(execution, outcome="blocked")
        with self.assertRaisesRegex(runtime.ProjectError, "mismatches execution input_binding"):
            autonomy.result(self.root, "C", receipt={**receipt, "input_binding": {}}, publish=self.f.publisher)
        self.finish("C", execution, outcome="blocked")
        current = self.item("C")["workflow"]["autonomy"]
        self.assertNotIn("current", current)
        self.assertTrue(current["executions"][execution["attempt"]]["finished_at"])
        self.assertEqual(current["blocker"], "executor_blocked")
        self.assertEqual(git(location, "ls-files", "--unmerged"), conflicts)
        self.assertEqual(self.state("C")["state"], "blocked")

    def test_ordinary_human_acceptance_unlocks_autonomous_dependency_after_delivery(self):
        self.configure("A")
        self.configure("B", ["A"])
        self.f.designed("A")
        self.assertEqual(self.f.finish(self.f.begin("development-start", "A"))["status"], "published")
        location = development.worktree_location(self.root, self.item("A"), self.f.project)
        (location / "A.txt").write_text("Ordinary implementation\n")
        report = self.f.directory / "ordinary-review.md"
        report.write_text("Independent review of the complete current ordinary implementation.\n")
        review = self.f.begin("development-finish", "A", result="pass", provenance="Actual independent review",
                              reviewer_session="ordinary-code-reviewer", review_file=str(report))
        self.assertEqual(self.f.finish(review)["status"], "published")
        self.authorize("B", enabled=False)
        self.assertIn("unaccepted:A", self.state("B")["reasons"])
        self.assertEqual(autonomy.accept(self.root, "A", approval_source="Actual human accepts ordinary A",
                                        publish=self.f.publisher)["status"], "published")
        self.assertNotIn("authorization", self.item("A")["workflow"]["autonomy"])
        self.assertEqual(self.state("B")["reasons"], ["undelivered:A"])
        self.deliver("A")
        self.assertEqual(self.state("B")["next_role"], "design-review")

    def test_prepare_recovery_guards_configuration_and_reattaches_recorded_branch(self):
        self.configure("A")
        self.configure("B", ["A"])
        self.authorize("A", "B")
        self.develop("A")
        with mock.patch.object(predevelopment, "_new_worktree", side_effect=runtime.ProjectError("lost before creation")):
            with self.assertRaisesRegex(runtime.ProjectError, "lost before"):
                self.prepare("B")
        self.assertEqual(predevelopment.state(self.item("B"))["phase"], "preparing")
        original = (self.root / ".project/project.yaml").read_text()
        changed = copy.deepcopy(self.f.project)
        changed["name"] = "Changed configuration during recovery"
        self.f.write(self.root, ".project/project.yaml", store.dump_yaml(changed))
        for operation in (predevelopment.prepare, predevelopment.snapshot):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(runtime.ProjectError, "configuration changed"):
                operation(self.root, "B", publish=self.f.publisher)
        self.f.write(self.root, ".project/project.yaml", original)
        original_git = development._git
        def interrupted(checkout, *args, **kwargs):
            if args[:3] == ("worktree", "add", "-b"):
                original_git(checkout, "branch", args[3], args[5])
                raise runtime.ProjectError("lost after branch creation")
            return original_git(checkout, *args, **kwargs)
        with mock.patch.object(development, "_git", side_effect=interrupted), self.assertRaisesRegex(runtime.ProjectError, "after branch"):
            self.prepare("B")
        generation = predevelopment.state(self.item("B"))["generation"]
        self.prepare("B")
        self.assertEqual(predevelopment.state(self.item("B"))["generation"], generation)
        self.assertEqual(self.state("B")["next_role"], "design-review")
