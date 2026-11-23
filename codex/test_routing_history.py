"""Regression cases where partial or inherited usage would change a routing comparison."""

import json
from pathlib import Path
import runpy
import unittest


replay = runpy.run_path(str(Path(__file__).parent / "skills/adapt-agent-routing/scripts/replay_history.py"))


def row(kind, **data):
    return json.dumps({"type": kind, "payload": data})


def usage(response, used, cumulative, thread="child"):
    def tokens(n):
        return dict(input_tokens=n, cached_input_tokens=n // 2, cache_write_input_tokens=0,
                    output_tokens=n // 10, reasoning_output_tokens=n // 20)
    return row("token_usage_record", thread_id=thread, turn_id="first", response_id=response,
               usage=tokens(used), turn_token_usage=tokens(cumulative))


class RoutingHistoryTest(unittest.TestCase):
    def setUp(self):
        self.records = [
            row("session_meta", id="child"),
            row("event_msg", type="task_started", turn_id="first"),
            row("turn_context", turn_id="first", model="candidate", effort="medium"),
            usage("inherited", 400, 400, thread="parent"),
            usage("a", 100, 100), usage("a", 100, 100), usage("b", 40, 140),
            row("event_msg", type="task_complete", turn_id="first"),
        ]
        self.end = len(self.records) - 1

    def read(self):
        return replay["first_turn_usage"](iter(self.records), "child", "first", 1, self.end, "completed")

    def test_price_uses_unique_owned_responses_and_request_tier(self):
        self.records.append(usage("later", 600, 600))
        case = self.read()
        self.assertEqual(case["tokens"], dict(input_tokens=140, cached_input_tokens=70,
                                              cache_write_input_tokens=0, output_tokens=14))
        self.assertAlmostEqual(replay["price"](case, (2, 1, 10, 100)), 0.00035)
        self.assertIsNone(replay["price"](case, (2, 1, 10, 99)))
        case["tokens"]["cache_write_input_tokens"] = 1
        self.assertIsNone(replay["price"](case, (2, 1, 10, 100)))

    def test_truncated_turn_cannot_be_priced_as_complete(self):
        self.records.pop()
        with self.assertRaisesRegex(replay["Gap"], "incomplete rollout"):
            self.read()

    def test_missing_response_is_detected_by_cumulative_snapshot(self):
        self.records[6] = usage("b", 40, 160)
        with self.assertRaisesRegex(replay["Gap"], "differs from turn snapshot"):
            self.read()


class DelegationFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.rows = [row("session_meta", id="parent")]
        self.activity("started", "spawn")

    def item(self, item_type, thread="parent", **fields):
        self.rows.append(row("event_msg", type="item_completed", thread_id=thread, turn_id="p-turn",
                             item=dict(type=item_type, **fields)))

    def activity(self, kind, call):
        self.item("SubAgentActivity", kind=kind, id=call, agent_thread_id="child", agent_path="/root/sample")

    def message(self, text, thread="parent"):
        self.item("AgentMessage", thread, content=[dict(type="Text", text=text)])

    def deliver(self, message, tool="followup_task", delivered=True):
        call = f"call_{len(self.rows)}"
        self.rows.append(row("response_item", type="function_call", namespace="collaboration",
                             name=tool, call_id=call, arguments=json.dumps(dict(message=message))))
        if delivered:
            self.activity("interacted", call)
        self.rows.append(row("response_item", type="function_call_output", call_id=call))

    def read(self):
        rows, gaps = replay["parent_feedback"](iter(self.rows), "parent", {"child"})
        return rows["child"], gaps

    def test_correction_and_distinct_work_on_same_child(self):
        self.deliver("Please include failures. [sample 补正]")
        records, gaps = self.read()
        self.assertFalse(gaps)
        self.assertTrue(records[0]["correction_requested"])
        self.assertEqual(records[0]["outcome"], "unknown")
        self.message("Check another source. [sample#schema 新任务]")
        self.deliver("opaque")
        self.message("Used both results. [sample 直接采用] [sample#schema 直接采用]")
        records, gaps = self.read()
        self.assertFalse(gaps)
        self.assertEqual([(r["key"], r["outcome"]) for r in records],
                         [("sample", "used_after_correction"), ("sample#schema", "used")])

    def test_no_disposition_from_completion_quotes_or_undelivered_work(self):
        self.activity("completed", "done")
        self.message("Child self-report. [sample 直接采用]", thread="child")
        self.message("Example `[sample 直接采用]`\n> [sample 未采用]\n```\n[sample 直接采用]\n```")
        self.deliver("See also. [sample#other 新任务]", delivered=False)
        self.deliver("Unclassified historical follow-up.")
        records, gaps = self.read()
        self.assertEqual(gaps, {"unclassified follow-up": 1})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outcome"], "unknown")
        self.assertNotIn("feedback_ordinal", records[0])


if __name__ == "__main__":
    unittest.main()
