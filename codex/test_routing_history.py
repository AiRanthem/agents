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


if __name__ == "__main__":
    unittest.main()
