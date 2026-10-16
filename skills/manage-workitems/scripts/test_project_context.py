from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path
import project_store as store


SCRIPT = Path(__file__).with_name("project_context.py")
runtime = types.ModuleType("project_runtime")
validate_calls = []


class ProjectError(Exception):
    pass


def find_project(path: Path) -> Path:
    current = path.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if ((candidate / ".project" / "project.json").is_file() or
                (candidate / ".project" / "project.yaml").is_file()):
            return candidate
    raise ProjectError(f"no project marker found from {path}")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_project(root: Path) -> list[str]:
    validate_calls.append(root)
    value = read_json(root / ".project" / "project.json")
    required = ("schema_version", "id", "name", "storage", "backends", "repositories")
    return [f"missing {key}" for key in required if key not in value]


runtime.ProjectError = ProjectError
runtime.find_project = find_project
runtime.read_json = read_json
runtime.validate_project = validate_project


def working_files(root: Path, paths):
    result = {}
    for name in paths:
        path = root / name
        if path.is_symlink():
            raise ProjectError(f"symlink path forbidden: {name}")
        if path.is_file():
            result[name] = path.read_bytes()
    return result


runtime._working_files = working_files
spec = importlib.util.spec_from_file_location("_project_context_under_test", SCRIPT)
project_context = importlib.util.module_from_spec(spec)
assert spec.loader
# Isolate the lightweight query fixture. Leaving either fake module in
# sys.modules makes subsequently collected integration tests use a stub runtime.
with mock.patch.dict(sys.modules, {"project_runtime": runtime, spec.name: project_context}):
    spec.loader.exec_module(project_context)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_yaml(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(store.dump_yaml(value), encoding="utf-8")


def item(item_id: str, title: str, status: str = "new") -> dict:
    return {
        "id": item_id,
        "title": title,
        "kind": "development",
        "status": status,
        "archived": False,
        "depends_on": [],
        "split_from": None,
        "repository": "repo-a",
        "owner": None,
        "development": {"worktree": "/outside/repo-worktree", "branch": "feature", "base_commit": None},
        "delivery": {"required": False, "status": "pending", "evidence": []},
        "cleanup": None,
    }


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        validate_calls.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        write_json(self.root / ".project/project.json", {
            "schema_version": 1, "id": "demo", "name": "Demo",
            "storage": {"remote": "origin", "branch": "main", "url": "https://example.invalid/demo.git"},
            "backends": {"aone": None},
            "repositories": [{"id": "repo-a", "url": "https://example.invalid/repo.git", "base_ref": "main"}],
        })
        write_json(self.root / "workitems/one/item.json", item("one", "First", "new"))
        write_json(self.root / "workitems/two/item.json", item("two", "Second", "done"))
        (self.root / "workitems/one/requirement.md").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "workitems/one/requirement.md").write_text("Requirement body", encoding="utf-8")
        (self.root / "workitems/one/spec.md").write_text("Spec body", encoding="utf-8")
        (self.root / "workitems/one/handoff.md").write_text("Handoff body", encoding="utf-8")
        (self.root / "workitems/one/reviews").mkdir()
        (self.root / "workitems/one/reviews/old.md").write_text("SECRET OLD REVIEW FINDING", encoding="utf-8")
        write_json(self.root / "evidence/e1.json", {
            "id": "e1", "repository": "repo-a", "topic": "implementation source", "summary": "source detail",
            "kind": "fact", "sources": [{"path": "src/main.py"}], "scope": "commit abc", "inputs": {}, "body": "evidence/e1.md"
        })
        (self.root / "evidence/e1.md").write_text("SECRET EVIDENCE BODY", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_selectors_return_canonical_item_and_review_paths(self):
        canonical = "1A-shared-quota"
        write_json(self.root / f"workitems/{canonical}/item.json", item(canonical, "共享配额"))
        directory = self.root / "workitems" / canonical
        (directory / "requirement.md").write_text("Requirement")
        (directory / "reviews").mkdir()
        review = f"workitems/{canonical}/reviews/old.md"
        (self.root / review).write_text("Prior review")
        for selector in (canonical, "1A", "shared-quota", "共享配额"):
            with self.subTest(selector=selector):
                args = project_context.parser().parse_args(["--path", str(self.root), "show", selector])
                shown = project_context.command(args)
                self.assertEqual(shown["metadata"]["id"], canonical)
                self.assertEqual(shown["metadata_path"], f"workitems/{canonical}/item.json")
                for role in ("manage", "explore", "review-design", "review-implementation", "implement"):
                    args = project_context.parser().parse_args(["--path", str(self.root), "context", selector, "--role", role])
                    payload = project_context.command(args)
                    self.assertEqual(payload["item"], canonical)
                    if role.startswith("review-"):
                        self.assertEqual(payload["deferred_inputs"], [review])
                        self.assertEqual(payload["entrypoint"], f"workitems/{canonical}/item.json")

    def test_ambiguous_slug_or_title_lists_candidates_and_full_id_wins(self):
        for identifier in ("1-shared", "2-shared"):
            write_json(self.root / f"workitems/{identifier}/item.json", item(identifier, "同名标题"))
        for selector in ("shared", "同名标题"):
            args = project_context.parser().parse_args(["--path", str(self.root), "show", selector])
            with self.subTest(selector=selector), self.assertRaises(project_context.ContextError) as caught:
                project_context.command(args)
            message = str(caught.exception)
            self.assertIn("ambiguous", message)
            self.assertIn("1-shared: 同名标题", message)
            self.assertIn("2-shared: 同名标题", message)
        write_json(self.root / "workitems/3-other/item.json", item("3-other", "1-shared"))
        args = project_context.parser().parse_args(["--path", str(self.root), "show", "1-shared"])
        self.assertEqual(project_context.command(args)["metadata"]["id"], "1-shared")

    def test_legacy_ids_and_titles_remain_readable_and_partial_matches_fail(self):
        legacy = "wi-4a1f5d26eabc"
        write_json(self.root / f"workitems/{legacy}/item.json", item(legacy, "旧工作项"))
        for selector in (legacy, "旧工作项", "one", "First"):
            args = project_context.parser().parse_args(["--path", str(self.root), "show", selector])
            expected = legacy if selector in (legacy, "旧工作项") else "one"
            self.assertEqual(project_context.command(args)["metadata"]["id"], expected)
        for selector in ("4a1f5d26eabc", "First partial", "旧工作"):
            args = project_context.parser().parse_args(["--path", str(self.root), "show", selector])
            with self.subTest(selector=selector), self.assertRaisesRegex(project_context.ContextError, "not found"):
                project_context.command(args)

    def test_management_context_does_not_read_worktree_or_evidence(self):
        original = project_context._read_bytes
        read_paths = []

        def tracked_read(root, path):
            read_paths.append(str(path))
            return original(root, path)

        project_context._read_bytes = tracked_read
        try:
            args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "manage"])
            payload = project_context.command(args)
        finally:
            project_context._read_bytes = original
        self.assertEqual(payload["inputs"], {"item.json": "workitems/one/item.json"})
        self.assertNotIn("worktree", payload["inputs"])
        self.assertFalse(any(path.endswith(".md") for path in read_paths))
        self.assertFalse(any("/evidence/" in path for path in read_paths))
        self.assertNotIn("SECRET EVIDENCE BODY", json.dumps(payload))
        self.assertNotIn("/outside/repo-worktree", json.dumps(payload))

    def test_associated_main_workspace_is_routed_without_reading_its_body_or_binding(self):
        project = read_json(self.root / ".project/project.json")
        project["main_workspace"] = {"id": "primary", "name": "Primary", "repository": None}
        project["worktrees"] = {"base": "main_workspace", "path": "repos/main-worktrees"}
        write_json(self.root / ".project/project.json", project)
        marker = self.root / ".project/main-workspace.md"
        marker.write_text("main workspace constraints", encoding="utf-8")
        original = project_context._read_bytes
        read_paths = []

        def tracked_read(root, path):
            read_paths.append(str(path))
            return original(root, path)

        project_context._read_bytes = tracked_read
        try:
            args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "manage"])
            payload = project_context.command(args)
        finally:
            project_context._read_bytes = original
        self.assertEqual(payload["main_workspace"], {
            "id": "primary", "name": "Primary", "context_path": ".project/main-workspace.md",
            "binding_path": ".project-local/main-workspace.json",
        })
        self.assertEqual(payload["worktree_layout"], {"base": "main_workspace", "path": "repos/main-worktrees"})
        self.assertIn("navigation document at context_path first", payload["main_workspace_routing_hint"])
        self.assertFalse(any(path.endswith("main-workspace.md") for path in read_paths))
        self.assertFalse((self.root / ".project-local/main-workspace.json").exists())

    def test_main_workspace_marker_change_invalidates_context_cache_without_reading_it(self):
        project = read_json(self.root / ".project/project.json")
        project["main_workspace"] = {"id": "primary", "name": "Primary", "repository": None}
        write_json(self.root / ".project/project.json", project)
        marker = self.root / ".project/main-workspace.md"
        marker.write_text("first", encoding="utf-8")
        args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "manage"])
        first = project_context.command(args)
        self.assertTrue(first["index_rebuilt"])
        marker.write_text("other", encoding="utf-8")
        second = project_context.command(args)
        self.assertTrue(second["index_rebuilt"])

    def test_associated_main_workspace_requires_a_safe_marker_file(self):
        project = read_json(self.root / ".project/project.json")
        project["main_workspace"] = {"id": "primary", "name": "Primary", "repository": None}
        write_json(self.root / ".project/project.json", project)
        args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "manage"])
        with self.assertRaisesRegex(project_context.ContextError, "cannot inspect project path"):
            project_context.command(args)
        target = Path(self.temp.name) / "main-workspace.md"
        target.write_text("private", encoding="utf-8")
        (self.root / ".project/main-workspace.md").symlink_to(target)
        with self.assertRaisesRegex(project_context.ContextError, "not a regular file"):
            project_context.command(args)

    def test_malformed_main_workspace_and_worktree_layout_fail(self):
        project = read_json(self.root / ".project/project.json")
        project["main_workspace"] = {"id": "../primary", "name": "Primary", "repository": None}
        write_json(self.root / ".project/project.json", project)
        with self.assertRaisesRegex(project_context.ContextError, "safe identifier"):
            project_context.get_index(self.root)
        project["main_workspace"] = {"id": "primary", "name": "Primary", "repository": None}
        project["worktrees"] = {"base": "main_workspace", "path": "worktrees"}
        write_json(self.root / ".project/project.json", project)
        with self.assertRaisesRegex(project_context.ContextError, "dedicated safe subdirectory"):
            project_context.get_index(self.root)
        project["worktrees"] = {"base": "project", "path": "worktrees/../outside"}
        write_json(self.root / ".project/project.json", project)
        with self.assertRaisesRegex(project_context.ContextError, "worktrees.path"):
            project_context.get_index(self.root)
        for invalid_base in ([], {}):
            project["worktrees"] = {"base": invalid_base, "path": "worktrees"}
            write_json(self.root / ".project/project.json", project)
            with self.subTest(base=invalid_base), self.assertRaisesRegex(project_context.ContextError, "worktrees.base"):
                project_context.get_index(self.root)
        for base, layout_path in (("project", "worktrees/.GIT"), ("main_workspace", "trees/.PROJECT")):
            project["worktrees"] = {"base": base, "path": layout_path}
            write_json(self.root / ".project/project.json", project)
            with self.subTest(base=base, path=layout_path), self.assertRaisesRegex(project_context.ContextError, "reserved component|dedicated safe"):
                project_context.get_index(self.root)
        project.pop("worktrees")
        project["main_workspace"]["repository"] = {"url": "https://example.invalid/main.git", "ref": "main"}
        write_json(self.root / ".project/project.json", project)
        with self.assertRaisesRegex(project_context.ContextError, "full git ref"):
            project_context.get_index(self.root)

    def test_list_filter_and_pagination_report_total_and_has_more(self):
        args = project_context.parser().parse_args(["--path", str(self.root), "list", "--status", "new", "--query", "First", "--limit", "1", "--offset", "0"])
        payload = project_context.command(args)
        self.assertEqual(payload["total"], 1)
        self.assertEqual([row["id"] for row in payload["results"]], ["one"])
        args = project_context.parser().parse_args(["--path", str(self.root), "list", "--limit", "1"])
        payload = project_context.command(args)
        self.assertEqual(payload["total"], 2)
        self.assertTrue(payload["has_more"])

    def test_added_canonical_item_is_visible_even_when_cache_was_fresh_before(self):
        first, rebuilt = project_context.get_index(self.root)
        self.assertTrue(rebuilt)
        self.assertEqual(len(first["items"]), 2)
        write_json(self.root / "workitems/three/item.json", item("three", "Third"))
        second, rebuilt = project_context.get_index(self.root)
        self.assertTrue(rebuilt)
        self.assertEqual({row["id"] for row in second["items"]}, {"one", "two", "three"})

    def test_corrupt_derived_cache_is_rebuilt(self):
        project_context.get_index(self.root)
        cache = self.root / ".project-local/index.json"
        cache.write_text("{broken", encoding="utf-8")
        index, rebuilt = project_context.get_index(self.root)
        self.assertTrue(rebuilt)
        self.assertEqual(len(index["items"]), 2)
        json.loads(cache.read_text(encoding="utf-8"))

    def test_malformed_canonical_json_is_an_error(self):
        (self.root / "workitems/one/item.json").write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(project_context.ContextError, "malformed canonical JSON"):
            project_context.get_index(self.root)

    def test_invalid_status_and_dependencies_fail_before_filtering(self):
        for field, value, message in (("status", ["new"], "status is invalid"), ("depends_on", "two", "depends_on must be a list")):
            current = item("one", "First")
            current[field] = value
            write_json(self.root / "workitems/one/item.json", current)
            with self.subTest(field=field), self.assertRaisesRegex(project_context.ContextError, message):
                project_context.get_index(self.root)

    def test_explore_context_includes_existing_contract_paths_without_loading_evidence(self):
        original = project_context._read_bytes
        read_paths = []

        def tracked_read(root, path):
            read_paths.append(str(path))
            return original(root, path)

        project_context._read_bytes = tracked_read
        try:
            args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "explore"])
            payload = project_context.command(args)
        finally:
            project_context._read_bytes = original
        self.assertEqual(payload["inputs"]["spec.md"], "workitems/one/spec.md")
        self.assertEqual(payload["inputs"]["handoff.md"], "workitems/one/handoff.md")
        self.assertNotIn("evidence_metadata", payload)
        self.assertIn("search-evidence <topic>", payload["evidence_query_hint"])
        self.assertFalse(any("/evidence/" in path for path in read_paths))

    def test_reviewer_returns_prior_reviews_as_deferred_paths_without_reading_them(self):
        original = project_context._read_bytes
        read_paths = []

        def tracked_read(root, path):
            read_paths.append(str(path))
            return original(root, path)

        project_context._read_bytes = tracked_read
        try:
            args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "review-implementation"])
            payload = project_context.command(args)
        finally:
            project_context._read_bytes = original
        self.assertIn("workitems/one/reviews/old.md", payload["deferred_inputs"])
        self.assertEqual(payload["entrypoint"], "workitems/one/item.json")
        self.assertNotIn("evidence_metadata", payload)
        self.assertNotIn("SECRET OLD REVIEW FINDING", json.dumps(payload))
        self.assertIn("Requirement body", payload["documents"]["requirement"]["text"])
        self.assertIn("Spec body", payload["documents"]["spec"]["text"])
        self.assertIn("Handoff body", payload["documents"]["context"]["text"])
        self.assertFalse(any("reviews/old.md" in path for path in read_paths))
        self.assertEqual(payload["preread_order"][0], "workitems/one/item.json")

    def test_design_reviewer_gets_contract_paths_before_deferred_reviews(self):
        args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "review-design"])
        payload = project_context.command(args)
        self.assertEqual(payload["entrypoint"], "workitems/one/item.json")
        self.assertEqual(payload["preread_order"][:3], ["workitems/one/item.json", "workitems/one/requirement.md", "workitems/one/spec.md"])
        self.assertIn("workitems/one/reviews/old.md", payload["deferred_inputs"])
        self.assertNotIn("SECRET OLD REVIEW FINDING", json.dumps(payload))

    def test_read_commands_never_call_full_workspace_validator(self):
        args = project_context.parser().parse_args(["--path", str(self.root), "list"])
        project_context.command(args)
        args = project_context.parser().parse_args(["--path", str(self.root), "context", "one", "--role", "manage"])
        project_context.command(args)
        self.assertEqual(validate_calls, [])

    def test_search_evidence_is_paged_and_warns_about_empty_results(self):
        original = project_context._read_bytes
        read_paths = []

        def tracked_read(root, path):
            read_paths.append(str(path))
            return original(root, path)

        project_context._read_bytes = tracked_read
        try:
            args = project_context.parser().parse_args(["--path", str(self.root), "search-evidence", "implementation", "--repository", "repo-a", "--limit", "1"])
            payload = project_context.command(args)
        finally:
            project_context._read_bytes = original
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["results"][0]["id"], "e1")
        self.assertIn("consumer must recheck", payload["results"][0]["applicability"])
        self.assertFalse(any(path.endswith(".md") for path in read_paths))

    def test_evidence_body_path_cannot_escape_workspace(self):
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("private", encoding="utf-8")
        write_json(self.root / "evidence/e2.json", {
            "id": "e2", "repository": "repo-a", "topic": "x", "summary": "x", "kind": "fact",
            "sources": [], "scope": "x", "inputs": {}, "body": "../outside.md"
        })
        args = project_context.parser().parse_args(["--path", str(self.root), "search-evidence", "x"])
        with self.assertRaisesRegex(project_context.ContextError, "same-id Markdown file"):
            project_context.command(args)

    def test_evidence_body_must_exist_but_is_not_read(self):
        (self.root / "evidence/e1.md").unlink()
        args = project_context.parser().parse_args(["--path", str(self.root), "search-evidence", "implementation"])
        with self.assertRaisesRegex(project_context.ContextError, "cannot inspect project path"):
            project_context.command(args)

    def v2_workspace(self) -> tuple[Path, dict[str, dict]]:
        root = Path(self.temp.name) / "v2"
        project = {
            "schema_version": 2, "id": "demo-v2", "name": "Demo v2",
            "storage": {"remote": "origin", "branch": "projects/demo", "url": "https://example.invalid/demo.git"},
            "backends": {"aone": None},
            "repositories": [{"id": "repo-a", "url": "https://example.invalid/repo.git", "base_ref": "refs/heads/main"}],
        }
        write_yaml(root / ".project/project.yaml", project)
        items = {
            "1-base": {"status": "done", "depends_on": [], "delivery_status": "delivered"},
            "11-middle": {"status": "done", "depends_on": ["1-base"], "delivery_status": "delivered"},
            "2-fix": {"status": "new", "depends_on": [], "delivery_status": "pending", "fixes": "1-base"},
            "111-target": {"status": "new", "depends_on": ["11-middle"], "delivery_status": "pending"},
        }
        files = {".project/project.yaml": (root / ".project/project.yaml").read_bytes()}
        for identifier, setup in items.items():
            record = {
                "id": identifier, "title": identifier, "kind": "development", "status": setup["status"],
                "depends_on": setup["depends_on"], "repository": "repo-a", "owner": None,
                "development": None, "fixes": setup.get("fixes"),
                "delivery": {"required": ["merged"], "status": setup["delivery_status"],
                             "evidence": ([{"kind": "merged", "reference": "commit"}]
                                          if setup["delivery_status"] == "delivered" else [])},
                "documents": {"requirement": "requirement.md", "context": "context.md",
                              "decision": "decision.md", "logs": "logs.md"},
                "design": {"file": "spec.md", "version": 1, "state": "draft"},
            }
            for name, content in store.write_item(files, record).items():
                files[name] = content.encode("utf-8")
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for identifier, doc, content in (
            ("111-target", "requirement.md", "Full requirement"),
            ("111-target", "context.md", "Current context"),
            ("111-target", "decision.md", "Approved decision"),
            ("111-target", "logs.md", "Progress log"),
            ("111-target", "spec.md", "Current design"),
        ):
            (root / "workitems" / identifier / doc).write_text(content, encoding="utf-8")
        (root / "evidence/e1.md").parent.mkdir(parents=True, exist_ok=True)
        (root / "evidence/e1.md").write_text("Evidence body", encoding="utf-8")
        return root, items

    def test_v2_state_and_receipt_yaml_invalidate_cache_and_show_current_owner(self):
        root, _ = self.v2_workspace()
        first, rebuilt = project_context.get_index(root)
        self.assertTrue(rebuilt)
        target = next(entry for entry in first["items"] if entry["id"] == "111-target")
        self.assertEqual(target["path"], "workitems/111-target/metadata.yaml")
        self.assertIsNone(target["metadata"]["owner"])

        state_path = root / ".project/state/111-target.yaml"
        state = store.load_yaml(state_path.read_bytes())
        state["owner"] = {"machine": "m", "session": "s", "token": "current"}
        write_yaml(state_path, state)
        second, rebuilt = project_context.get_index(root)
        self.assertTrue(rebuilt)
        target = next(entry for entry in second["items"] if entry["id"] == "111-target")
        self.assertEqual(target["metadata"]["owner"]["token"], "current")

        receipt_path = root / ".project/sync/111-target.yaml"
        receipt = {"intent_id": "i1", "state": "pending", "external_id": "external-1"}
        write_yaml(receipt_path, receipt)
        third, rebuilt = project_context.get_index(root)
        self.assertTrue(rebuilt)
        self.assertEqual(third["receipts"][0]["metadata"]["external_id"], "external-1")
        receipt["external_id"] = "external-2"
        write_yaml(receipt_path, receipt)
        args = project_context.parser().parse_args(["--path", str(root), "show", "111-target"])
        shown = project_context.command(args)
        self.assertTrue(shown["index_rebuilt"])
        self.assertEqual(shown["metadata_path"], "workitems/111-target/metadata.yaml")
        self.assertEqual(shown["receipt"]["metadata_path"], ".project/sync/111-target.yaml")
        self.assertEqual(shown["receipt"]["metadata"]["external_id"], "external-2")

    def test_v2_context_returns_role_documents_and_transitive_fix_blockers(self):
        root, _ = self.v2_workspace()
        args = project_context.parser().parse_args(["--path", str(root), "context", "111-target", "--role", "implement"])
        payload = project_context.command(args)
        self.assertEqual(payload["inputs"]["metadata.yaml"], "workitems/111-target/metadata.yaml")
        self.assertEqual(payload["inputs"]["requirement.md"], "workitems/111-target/requirement.md")
        self.assertEqual(payload["documents"]["requirement"]["text"], "Full requirement")
        self.assertEqual(payload["documents"]["spec"]["text"], "Current design")
        self.assertEqual(payload["documents"]["context"]["text"], "Current context")
        self.assertEqual(payload["readiness"]["blockers"]["dependencies"], [])
        self.assertEqual(payload["readiness"]["blockers"]["fixes"], ["2-fix"])
        self.assertTrue(payload["readiness"]["dependency_ready"])
        self.assertTrue(payload["readiness"]["blocked"])

    def test_v2_yaml_evidence_search_and_read_queries_do_not_write_cache(self):
        root, _ = self.v2_workspace()
        write_yaml(root / "evidence/e1.yaml", {
            "id": "e1", "repository": "repo-a", "topic": "implementation", "summary": "YAML record",
            "kind": "fact", "sources": [{"path": "src/main.py"}], "scope": "commit abc",
            "inputs": {}, "body": "evidence/e1.md",
        })
        args = project_context.parser().parse_args(["--path", str(root), "search-evidence", "implementation"])
        payload = project_context.command(args)
        self.assertEqual(payload["results"][0]["id"], "e1")
        self.assertFalse((root / ".project-local").exists())

    def test_v2_exposes_only_current_referenced_reports_without_indexing_prose(self):
        root, _ = self.v2_workspace()
        identifier = "111-target"
        prefix = f"workitems/{identifier}/records/"
        review = {"id": "current-review", "item": identifier, "kind": "design-review",
                  "report": prefix + "current-review.md"}
        state = root / f".project/state/{identifier}.yaml"
        write_yaml(state, {"design": {"review": review}})
        write_yaml(root / (prefix + "current-review.yaml"), review)
        (root / (prefix + "current-review.md")).write_text("Current review", encoding="utf-8")
        # An unreferenced malformed machine record and its prose are never read.
        (root / (prefix + "obsolete.yaml")).write_text("[malformed", encoding="utf-8")
        (root / (prefix + "obsolete.md")).write_text("Historical finding", encoding="utf-8")
        legacy = root / f"workitems/{identifier}/reviews/old.md"
        legacy.parent.mkdir()
        legacy.write_text("Old review", encoding="utf-8")
        index, _ = project_context.get_index(root, include_evidence=False)
        self.assertFalse(any("/records/" in name for name in index["sources"]))
        args = project_context.parser().parse_args(["--path", str(root), "show", identifier])
        with mock.patch.object(project_context, "_read_bytes", wraps=project_context._read_bytes) as reads:
            shown = project_context.command(args)
        self.assertIn(prefix + "current-review.md", shown["body_paths"])
        self.assertNotIn(prefix + "obsolete.md", shown["body_paths"])
        self.assertNotIn(legacy.relative_to(root).as_posix(), shown["body_paths"])
        self.assertTrue(all(call.args[1].suffix != ".md" for call in reads.call_args_list))
        args = project_context.parser().parse_args(["--path", str(root), "context", identifier, "--role", "review-design"])
        self.assertEqual(project_context.command(args)["deferred_inputs"], [prefix + "current-review.md"])
        (root / (prefix + "current-review.md")).unlink()
        with self.assertRaisesRegex(project_context.ContextError, "cannot inspect"):
            project_context.command(args)


if __name__ == "__main__":
    unittest.main()
