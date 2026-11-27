"""Exercise real hook output without starting model sessions."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


HOOKS = Path(__file__).parent
SESSION_START = HOOKS / "session-start.py"
PROMPTS = HOOKS.parent / "prompts"
SHARED = ("delegation-task.md", "delegation-evidence.md", "delegation-lifecycle.md")
CARD = "delegation-routing.md"


def invoke(event, hook=SESSION_START):
    return subprocess.run(
        [sys.executable, str(hook)], input=json.dumps(event),
        text=True, capture_output=True, check=False,
    )


class DelegationHookTests(unittest.TestCase):
    def test_model_matrix(self):
        for model, family in [
            ("gpt-6-astra", "astra"), ("gpt-6.1-sol", "sol"),
            ("gpt-6.2-astra", "astra"), ("gpt-6.2-sol", "sol"),
            ("gpt-6-luna", "luna"), ("gpt-99-astra-preview", "astra"),
            ("gpt-99-sol-preview", "sol"), ("gpt-99-luna-preview", "luna"),
            ("gpt-7-astral", None), ("gpt-7-solstice", None),
            ("gpt-7-lunatic", None), ("other-6-astra", None), ("gpt-6.1-terra", None),
            ("gpt-7-astra-sol", None), (None, None), (7, None),
        ]:
            with self.subTest(model=model):
                event = {"hook_event_name": "SessionStart"}
                if model is not None:
                    event["model"] = model
                result = invoke(event)
                self.assertEqual(result.returncode, 0, result.stderr)
                if family == "luna":
                    self.assertEqual(result.stdout, "")
                    continue
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "SessionStart")
                paths = [PROMPTS.resolve() / name for name in SHARED]
                if family in {"astra", "sol"}:
                    paths.append(PROMPTS.resolve() / CARD)
                for path in paths:
                    self.assertTrue(path.read_text().strip())
                index = "\n".join(f"- {path}" for path in paths)
                expected = (PROMPTS / "delegation.md").read_text().strip() + "\n\n" + index + "\n"
                self.assertEqual(output["additionalContext"], expected)

    def test_routing_profiles(self):
        profiles = set(re.findall(r"\b(gpt-[\w.-]+ / \w+)\b", (PROMPTS / CARD).read_text()))
        self.assertEqual(profiles, {
            "gpt-6-luna / high", "gpt-6-luna / max",
            "gpt-6.2-sol / medium", "gpt-6.2-sol / xhigh",
            "gpt-6.2-astra / high", "gpt-6.2-astra / xhigh", "gpt-6.1-sol / max",
        })

    def test_unrelated_event_produces_no_output(self):
        result = invoke({"hook_event_name": "SubagentStart", "model": "gpt-6-astra"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_only_the_entry_prompt_is_required_at_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hook = root / "hooks" / SESSION_START.name
            hook.parent.mkdir()
            shutil.copyfile(SESSION_START, hook)
            entry = root / "prompts" / "delegation.md"
            entry.parent.mkdir()
            for model in ["unknown", "gpt-6.2-astra", "gpt-6.2-sol"]:
                event = {"hook_event_name": "SessionStart", "model": model}
                for content in [None, " \n\t"]:
                    with self.subTest(model=model, content=content):
                        if content is not None:
                            entry.write_text(content)
                        result = invoke(event, hook)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, "")
                        self.assertIn(entry.name, result.stderr)
                shutil.copyfile(PROMPTS / entry.name, entry)
                result = invoke(event, hook)
                self.assertEqual(result.returncode, 0, result.stderr)
                entry.unlink()

            result = invoke({"hook_event_name": "SessionStart", "model": "gpt-6-luna"}, hook)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")

    def test_invalid_input_reports_failure(self):
        for payload in ["{", "{}", "[]", "null"]:
            with self.subTest(payload=payload):
                result = subprocess.run([sys.executable, str(SESSION_START)], input=payload,
                                        text=True, capture_output=True, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("Unable to load", result.stderr)

    def test_installed_entry_resolves_prompts_from_its_source(self):
        event = {"hook_event_name": "SessionStart", "model": "gpt-6.2-astra"}
        startup = invoke(event)
        self.assertEqual(startup.returncode, 0, startup.stderr)
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / ".codex" / "hooks" / SESSION_START.name
            installed.parent.mkdir(parents=True)
            installed.symlink_to(SESSION_START.resolve())
            result = invoke(event, installed)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(startup.stdout))


if __name__ == "__main__":
    unittest.main()
