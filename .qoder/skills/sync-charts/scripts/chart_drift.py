#!/usr/bin/env python3
"""Check and optionally copy CRDs listed in config/crd/kustomization.yaml."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    component: str
    path: Path


CHART_SPEC = {
    "agents.kruise.io_checkpoints.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_checkpoints.yaml"),
    ),
    "agents.kruise.io_commits.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_commits.yaml"),
    ),
    "agents.kruise.io_poolautoscalers.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_poolautoscalers.yaml"),
    ),
    "agents.kruise.io_sandboxclaims.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_sandboxclaims.yaml"),
    ),
    "agents.kruise.io_sandboxes.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_sandboxes.yaml"),
    ),
    "agents.kruise.io_sandboxsets.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_sandboxsets.yaml"),
    ),
    "agents.kruise.io_sandboxtemplates.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_sandboxtemplates.yaml"),
    ),
    "agents.kruise.io_sandboxupdateops.yaml": Target(
        "controller",
        Path("versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_sandboxupdateops.yaml"),
    ),
    "agents.kruise.io_trafficpolicies.yaml": Target(
        "manager",
        Path("versions/kruise-agents-sandbox-manager/next/files/agentio/trafficpolicy-crd.yaml"),
    ),
    "agents.kruise.io_globaltrafficpolicies.yaml": Target(
        "manager",
        Path("versions/kruise-agents-sandbox-manager/next/files/agentio/globaltrafficpolicy-crd.yaml"),
    ),
    "agents.kruise.io_securityprofiles.yaml": Target(
        "manager",
        Path("versions/kruise-agents-sandbox-manager/next/files/agentio/securityprofile-crd.yaml"),
    ),
    "agents.kruise.io_globalsecurityprofiles.yaml": Target(
        "manager",
        Path("versions/kruise-agents-sandbox-manager/next/files/agentio/globalsecurityprofile-crd.yaml"),
    ),
}


class ConfigurationError(Exception):
    pass


def resources(kustomization: Path) -> list[Path]:
    if not kustomization.is_file():
        raise ConfigurationError(f"missing kustomization: {kustomization}")

    result: list[Path] = []
    active = False
    for line in kustomization.read_text(encoding="utf-8").splitlines():
        if not active:
            active = line.strip() == "resources:"
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9_-]*:\s*", line):
            break
        match = re.match(r"^\s*-\s+([^#]+?)(?:\s+#.*)?$", line)
        if match:
            result.append(Path(match.group(1).strip().strip("'\"")))

    if not active:
        raise ConfigurationError(f"resources key not found: {kustomization}")
    return result


def synchronize(args: argparse.Namespace) -> int:
    if not args.charts_repo.is_dir():
        raise ConfigurationError(f"missing charts checkout: {args.charts_repo}")
    if not (args.charts_repo / "versions").is_dir():
        raise ConfigurationError(f"missing charts versions directory: {args.charts_repo / 'versions'}")

    crd_dir = args.agents_repo / "config" / "crd"
    entries: list[tuple[Path, Target]] = []
    has_unmapped = False

    for resource in resources(crd_dir / "kustomization.yaml"):
        target = CHART_SPEC.get(resource.name)
        if target is None:
            print(f"UNMAPPED crd {resource.name}")
            has_unmapped = True
            continue
        if args.component != "all" and args.component != target.component:
            continue
        source = crd_dir / resource
        if not source.is_file():
            raise ConfigurationError(f"missing CRD source: {source}")
        entries.append((source, target))

    if args.apply_crds and has_unmapped:
        return 3

    if args.apply_crds:
        for source, target in entries:
            destination = args.charts_repo / target.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            print(f"SYNCED crd {target.component} {target.path}")

    has_drift = False
    for source, target in entries:
        destination = args.charts_repo / target.path
        if not destination.is_file():
            print(f"DRIFT crd {target.component} {target.path} missing")
            has_drift = True
        elif source.read_bytes() != destination.read_bytes():
            print(f"DRIFT crd {target.component} {target.path} content")
            has_drift = True
        else:
            print(f"OK crd {target.component} {target.path}")
    if has_unmapped:
        return 3
    return 1 if has_drift else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents-repo", type=Path, default=Path.cwd())
    parser.add_argument("--charts-repo", type=Path, required=True)
    parser.add_argument("--component", choices=("all", "controller", "manager"), default="all")
    parser.add_argument("--aspect", choices=("crd",), default="crd")
    parser.add_argument("--target", choices=("next",), default="next")
    parser.add_argument("--apply-crds", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        return synchronize(parse_args())
    except ConfigurationError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
