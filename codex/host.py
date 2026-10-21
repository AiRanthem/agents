#!/usr/bin/env python3
"""Codex project-stage configuration and session identity."""

import os
from pathlib import Path
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import host_agents_common as common


def role_config(name):
    source = common.ROOT / "codex" / "agents" / f"{name}.toml"
    content = source.read_text()
    config = tomllib.loads(content)
    common.validate_role(source, name, config)
    if not config.get("model_reasoning_effort"):
        raise ValueError(f"{source}: missing model_reasoning_effort")
    return source, content, config


def check(home):
    return common.check_files("codex", home, role_config,
                              profile_fields=("model_reasoning_effort",))


def session():
    return os.environ.get("CODEX_THREAD_ID") or os.environ.get("PROJECT_SESSION_ID")


if __name__ == "__main__":
    raise SystemExit(common.main(host="codex"))
