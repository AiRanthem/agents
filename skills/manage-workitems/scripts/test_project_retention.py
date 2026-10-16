"""Current record reachability and scoped, fail-closed collection."""

import copy
import unittest

import project_retention as retention
import project_store as store


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.files = {".project/project.yaml": store.dump_yaml({"schema_version": 2}).encode()}
        self.item = {"id": "A", "kind": "development", "status": "new", "design": {"version": 0}}
        self.install(self.item)
        self.install({"id": "B", "kind": "development", "status": "new"})

    def install(self, item):
        self.files = store.apply_writes(self.files, store.write_item(self.files, item))

    def pair(self, record_id, kind):
        base = "workitems/A/records/" + record_id
        record = {"id": record_id, "item": "A", "kind": kind}
        if kind in {"design-review", "development-finish", "delivery-record"}:
            record["report"] = base + ".md"
        self.files[base + ".yaml"] = store.dump_yaml(record).encode()
        self.files[base + ".md"] = b"Opaque current evidence\n"
        return record

    def test_current_roots_survive_and_only_selected_item_history_is_collected(self):
        self.item["design"]["review"] = self.pair("design", "design-review")
        self.item["development"] = {"review": self.pair("implementation", "development-finish")}
        self.item["delivery"] = {"record": self.pair("delivery", "delivery-record")["id"]}
        self.item["workflow"] = {"design_waiver": self.pair("waiver", "user_design_review_waiver"),
                                 "cleanup_record": self.pair("cleanup", "cleanup")["id"]}
        self.install(self.item)
        live = {"workitems/A/records/" + name + suffix
                for name in ("design", "implementation", "delivery", "waiver", "cleanup")
                for suffix in (".md", ".yaml")}
        obsolete = {"workitems/A/records/old.md", "workitems/A/records/old.yaml",
                    "workitems/A/records/legacy-spec.md", "workitems/A/records/legacy-AGENTS.md",
                    "workitems/A/reviews/old-review.md"}
        untouched = {"workitems/B/records/old.md", ".project-local/edits/pending/draft.md",
                     ".project-local/publish/pending/journal.json", ".project/sync/A.yaml",
                     "evidence/current.json", "evidence/current.md"}
        self.files.update({name: b"Unparsed historical prose" for name in obsolete | untouched})
        original = copy.deepcopy(self.files)
        self.assertEqual(retention.live_record_paths(self.files, "A"), live)
        sparse = {name: value for name, value in self.files.items() if "/records/" not in name and "/reviews/" not in name}
        self.assertEqual(retention.record_metadata_paths(sparse, "A"), {name for name in live if name.endswith(".yaml")})
        self.assertEqual(retention.prune_records(self.files, ["A"]), dict.fromkeys(obsolete))
        self.assertEqual(self.files, original)

    def test_invalid_current_roots_are_rejected_before_deletion(self):
        record = self.pair("review", "design-review")
        self.item["design"]["review"] = record
        self.install(self.item)
        original = copy.deepcopy(self.files)
        for field, value in (("id", "../outside"), ("item", "B"), ("kind", "delivery-record"),
                             ("report", "workitems/B/records/review.md")):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.item)
                changed["design"]["review"][field] = value
                files = store.apply_writes(original, store.write_item(original, changed))
                with self.assertRaises(store.StoreError):
                    retention.prune_records(files, ["A"])
        self.files.pop("workitems/A/records/review.md")
        with self.assertRaises(store.StoreError):
            retention.prune_records(self.files, ["A"])

    def test_unsafe_history_paths_are_not_emitted_as_deletions(self):
        for name in ("workitems/A/records/../outside.md", "workitems/A/records//old.md",
                     "workitems/A/reviews/old.json"):
            with self.subTest(path=name), self.assertRaises(store.StoreError):
                retention.prune_records({**self.files, name: b"opaque"}, ["A"])


if __name__ == "__main__":
    unittest.main()
