"""Knowledge replacement uses the same guarded Git authority as item changes."""

from pathlib import Path
import shlex
import unittest
from unittest import mock

import project
import project_context as context
import project_knowledge as knowledge
import project_runtime as runtime
import project_store as store
import test_project_cli as cli_fixtures
import test_project_runtime as fixtures


class KnowledgeTest(unittest.TestCase):
    setUp = fixtures.WorkspaceTest.setUp
    configure = fixtures.WorkspaceTest.configure
    write = fixtures.WorkspaceTest.write
    remote_head = fixtures.WorkspaceTest.remote_head
    v2 = cli_fixtures.ProjectV2PublishTest.v2

    def update_from_read(self, read, content, **options):
        draft = Path(read["body_file"])
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(content, encoding="utf-8")
        return knowledge.update(self.a, read["id"], body_file=draft,
                                expected_metadata=read["metadata_sha256"] or "absent",
                                expected_body=read["body"]["sha256"] or "absent", options=options,
                                publish=project.publish_changes)

    def test_current_card_replace_guards_and_explicit_retirement(self):
        self.v2()
        with mock.patch.dict("os.environ", {"PROJECT_SESSION_ID": "knowledge-session"}):
            absent = knowledge.show(self.a, "current")
            self.assertFalse(absent["exists"])
            parallel = knowledge.show(self.a, "current")
            self.assertNotEqual(absent["body_file"], parallel["body_file"])
            self.assertEqual(absent["metadata_sha256"], parallel["metadata_sha256"])
            self.assertEqual(absent["body"]["sha256"], parallel["body"]["sha256"])
            command = shlex.split(absent["update_command"])
            args = project.parser().parse_args(command[2:])
            self.assertEqual(args.expect_body_sha256, "absent")
            result = self.update_from_read(absent, "# Current\n\nOld paragraph.\n", repository="code", topic="routing",
                                           summary="Routing rules", scope="current contract", kind="fact",
                                           inputs=["commit=abc"], sources=["src/router.py"],
                                           source_revision=["src/router.py=abc"], source_sha256=["src/router.py=" + "a" * 64])
            self.assertEqual(result["status"], "published", result)
            first = knowledge.show(self.a, "current")
            result = self.update_from_read(first, "# Current\n\nReplacement only.\n", summary="Latest routing")
            self.assertEqual(result["status"], "published", result)
            second = knowledge.show(self.a, "current")
            self.assertNotIn("Old paragraph", second["body"]["text"])
            self.assertEqual(second["metadata"]["inputs"], {"commit": "abc"})
            self.assertEqual(second["metadata"]["sources"], [{"path": "src/router.py", "revision": "abc", "sha256": "a" * 64}])
            with self.assertRaisesRegex(runtime.ProjectError, "byte check conflict"):
                self.update_from_read(first, "Stale overwrite")
            result = knowledge.remove(self.a, "current", expected_metadata=second["metadata_sha256"],
                                      expected_body=second["body"]["sha256"], publish=project.publish_changes)
            self.assertEqual(result["status"], "published", result)
            self.assertFalse(knowledge.show(self.a, "current")["exists"])
            self.assertEqual(runtime.validate_project(self.a), [])
            self.assertEqual(fixtures.git(self.a, "status", "--porcelain"), "")

    def test_input_security_and_pair_deletion_boundary(self):
        self.v2()
        absent = knowledge.show(self.a, "safe")
        source = self.directory / "outside.md"
        source.write_text("Body", encoding="utf-8")
        link = self.directory / "link.md"
        link.symlink_to(source)
        with self.assertRaisesRegex(context.ContextError, "symlink"):
            knowledge.update(self.a, "safe", body_file=link, expected_metadata="absent", expected_body="absent",
                             options={"repository": "code", "topic": "a", "summary": "b", "scope": "c", "kind": "fact"})
        with self.assertRaisesRegex(runtime.ProjectError, "exactly one current or --source entry"):
            knowledge.update(self.a, "safe", body_file=source, expected_metadata="absent", expected_body="absent",
                             options={"repository": "code", "topic": "a", "summary": "b", "scope": "c", "kind": "fact",
                                      "source_revision": ["unlisted=abc"]})
        files = runtime._working_files(self.a)
        files.update({"evidence/safe.yaml": b"id: safe\n", "evidence/safe.md": b"body"})
        prospective = dict(files)
        prospective.pop("evidence/safe.yaml")
        with self.assertRaisesRegex(runtime.ProjectError, "pair deletion"):
            runtime._check_deletions({"writes": {"evidence/safe.yaml": None},
                                      "checks": {"evidence/safe.yaml": "hash"}}, files, prospective)


if __name__ == "__main__":
    unittest.main()
