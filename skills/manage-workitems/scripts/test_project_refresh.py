"""Focused snapshot and exact-ref refresh checks using local bare repositories."""

import unittest
from unittest import mock

import project_runtime as runtime
import test_project_runtime as fixtures


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.workspace = fixtures.WorkspaceTest(methodName="runTest")
        self.workspace.setUp()
        self.addCleanup(self.workspace.doCleanups)

    def test_batch_snapshot_preserves_bytes_with_constant_git_processes(self):
        workspace = self.workspace
        for index in range(40):
            workspace.write(workspace.a, f"workitems/A/reviews/check-{index}.md",
                            "中文\n\x00body\n" + str(index) + "\n")
        fixtures.git(workspace.a, "add", ".")
        fixtures.git(workspace.a, "commit", "--quiet", "-m", "snapshot")
        expected = runtime._working_files(workspace.a)
        with mock.patch.object(runtime, "_git", wraps=runtime._git) as calls:
            actual = runtime._tree_files(workspace.a, "HEAD")
        self.assertEqual(actual, expected)
        self.assertEqual(calls.call_count, 2)

    def test_refresh_fast_forwards_exact_ref_and_rejects_dirty_root(self):
        workspace = self.workspace
        publication = workspace.publish(workspace.a, workspace.bundle(workspace.a, "A", {"title": "新版"}))
        result = runtime.refresh_project(workspace.b)
        self.assertEqual(result, {"commit": publication["verified_remote_commit"], "changed": True})
        self.assertEqual(runtime.refresh_project(workspace.b)["changed"], False)
        workspace.write(workspace.b, "workitems/A/requirement.md", "local change\n")
        with self.assertRaisesRegex(runtime.ProjectError, "dirty"):
            runtime.refresh_project(workspace.b)
        self.assertEqual((workspace.b / "workitems/A/requirement.md").read_text(), "local change\n")

    def test_refresh_rejects_different_authority_before_network(self):
        workspace = self.workspace
        fixtures.git(workspace.b, "remote", "set-url", "origin", str(workspace.directory / "other.git"))
        with mock.patch.object(runtime, "_fetch_selected") as fetch:
            with self.assertRaisesRegex(runtime.ProjectError, "differs"):
                runtime.refresh_project(workspace.b)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
