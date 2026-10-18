"""Exercise real hook output without starting model sessions."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


HOOKS = Path(__file__).parent
PROMPTS = HOOKS.parent / "prompts"
SHARED = ("delegation-task.md", "delegation-evidence.md", "delegation-lifecycle.md")


def invoke(event, hook=None):
    if hook is None:
        hook = HOOKS / ("subagent-start.py" if event["hook_event_name"] == "SubagentStart" else "session-start.py")
    return subprocess.run(
        [sys.executable, str(hook)], input=json.dumps(event),
        text=True, capture_output=True, check=False,
    )


class DelegationHookTests(unittest.TestCase):
    def test_model_and_event_matrix(self):
        for model, family in [
            ("gpt-6-astra", "astra"), ("gpt-6.1-sol", "sol"),
            ("gpt-6-luna", "luna"), ("gpt-99-astra-preview", "astra"),
            ("gpt-99-sol-preview", "sol"), ("gpt-99-luna-preview", "luna"),
            ("gpt-7-astral", None), ("gpt-7-solstice", None),
            ("gpt-7-lunatic", None), ("other-6-astra", None),
            ("gpt-7-astra-sol", None), (None, None), (7, None),
        ]:
            for event_name in ("SessionStart", "SubagentStart"):
                with self.subTest(model=model, event=event_name):
                    event = {"hook_event_name": event_name}
                    if model is not None:
                        event["model"] = model
                    result = invoke(event)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if (event_name == "SessionStart" and family == "luna" or
                            event_name == "SubagentStart" and family != "astra"):
                        self.assertEqual(result.stdout, "")
                        continue
                    output = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(output["hookEventName"], event_name)
                    boundary = "delegation.md" if event_name == "SessionStart" else "delegation-subagent.md"
                    names = [boundary, *SHARED]
                    if family in {"astra", "sol"}:
                        names.append(f"delegation-{family}.md")
                    expected = "\n\n".join((PROMPTS / name).read_text().strip() for name in names) + "\n"
                    self.assertEqual(output["additionalContext"], expected)

    def test_event_and_role_isolation(self):
        for event, other in [("SessionStart", "SubagentStart"), ("SubagentStart", "SessionStart")]:
            hook = HOOKS / ("session-start.py" if event == "SessionStart" else "subagent-start.py")
            result = invoke({"hook_event_name": other, "model": "gpt-6-astra"}, hook)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
        result = invoke({"hook_event_name": "SubagentStart", "model": "gpt-6-astra"})
        policy = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Preserve the parent's scope", policy)
        self.assertNotIn("Retain ownership of the user's goal", policy)
        self.assertNotIn("During explicitly started `advance-project`", policy)

    def test_routing_profiles(self):
        for event, model, profiles in [
            ("SessionStart", "gpt-6-astra", {"gpt-6-luna / high", "gpt-6-luna / max",
                                           "gpt-6.1-sol / medium", "gpt-6.1-sol / high",
                                           "gpt-6.1-sol / xhigh"}),
            ("SubagentStart", "gpt-6-astra", {"gpt-6-luna / high", "gpt-6-luna / max",
                                            "gpt-6.1-sol / medium", "gpt-6.1-sol / high",
                                            "gpt-6.1-sol / xhigh"}),
            ("SessionStart", "gpt-6.1-sol", {"gpt-6-luna / high", "gpt-6-luna / max"}),
        ]:
            result = invoke({"hook_event_name": event, "model": model})
            self.assertEqual(result.returncode, 0, result.stderr)
            policy = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            listed = {line.split("**")[1] for line in policy.splitlines() if line.startswith("- **")}
            self.assertEqual(listed, profiles)

    def test_selected_fragments_are_required_and_unselected_fragments_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(HOOKS, root / "hooks")
            for event_name, model, boundary, card in [
                ("SessionStart", "unknown", "delegation.md", None),
                ("SessionStart", "gpt-6-astra", "delegation.md", "delegation-astra.md"),
                ("SessionStart", "gpt-6.1-sol", "delegation.md", "delegation-sol.md"),
                ("SubagentStart", "gpt-6-astra", "delegation-subagent.md", "delegation-astra.md"),
            ]:
                hook = root / "hooks" / ("session-start.py" if event_name == "SessionStart" else "subagent-start.py")
                event = {"hook_event_name": event_name, "model": model}
                names = [boundary, *SHARED, *([card] if card else [])]
                for name in names:
                    for content in [None, " \n\t"]:
                        with self.subTest(event=event_name, model=model, prompt=name, content=content):
                            shutil.copytree(PROMPTS, root / "prompts", dirs_exist_ok=True)
                            target = root / "prompts" / name
                            if content is None:
                                target.unlink()
                            else:
                                target.write_text(content)
                            result = invoke(event, hook)
                            self.assertNotEqual(result.returncode, 0)
                            self.assertEqual(result.stdout, "")
                            self.assertIn(name, result.stderr)
                shutil.rmtree(root / "prompts")
                (root / "prompts").mkdir()
                for name in names:
                    shutil.copyfile(PROMPTS / name, root / "prompts" / name)
                result = invoke(event, hook)
                self.assertEqual(result.returncode, 0, result.stderr)
            shutil.rmtree(root / "prompts")
            for event_name, model in [("SessionStart", "gpt-6-luna"),
                                      ("SubagentStart", "gpt-6.1-sol"),
                                      ("SubagentStart", "unknown")]:
                hook = root / "hooks" / ("session-start.py" if event_name == "SessionStart" else "subagent-start.py")
                result = invoke({"hook_event_name": event_name, "model": model}, hook)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_invalid_input_reports_failure(self):
        for hook in (HOOKS / "session-start.py", HOOKS / "subagent-start.py"):
            for payload in ["{", "{}", "[]", "null"]:
                with self.subTest(hook=hook.name, payload=payload):
                    result = subprocess.run([sys.executable, str(hook)], input=payload,
                                            text=True, capture_output=True, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("Unable to load", result.stderr)

    def test_persistent_astra_role_loader_uses_installed_entry_and_complete_policy(self):
        role = tomllib.loads((HOOKS.parent / "agents" / "astra-delegate.toml").read_text())
        command = next(line for line in role["developer_instructions"].splitlines()
                       if line.startswith("printf "))
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installed = home / ".codex" / "hooks" / "subagent-start.py"
            installed.parent.mkdir(parents=True)
            installed.symlink_to(HOOKS / "subagent-start.py")
            result = subprocess.run(["sh", "-c", command], env={**os.environ, "HOME": str(home),
                                    "CODEX_HOME": str(home / ".codex")},
                                    text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        names = ["delegation-subagent.md", *SHARED, "delegation-astra.md"]
        self.assertEqual(policy, "\n\n".join((PROMPTS / name).read_text().strip() for name in names) + "\n")


if __name__ == "__main__":
    unittest.main()
