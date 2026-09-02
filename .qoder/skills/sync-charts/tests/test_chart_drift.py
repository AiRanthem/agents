#!/usr/bin/env python3
"""Black-box tests for the sync-charts drift checker."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CHECKER = SKILL_DIR / "scripts" / "chart_drift.py"
SKILL = SKILL_DIR / "SKILL.md"


class ChartDriftTest(unittest.TestCase):
    def test_reports_kustomization_crd_without_chart_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            charts_repo = root / "charts"
            (agents_repo / "config" / "crd" / "bases").mkdir(parents=True)
            (charts_repo / "versions").mkdir(parents=True)
            (agents_repo / "config" / "crd" / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_unmappedfixtures.yaml\n",
                encoding="utf-8",
            )
            (
                agents_repo / "config" / "crd" / "bases" / "agents.kruise.io_unmappedfixtures.yaml"
            ).write_text(
                "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(charts_repo),
                    "--aspect",
                    "crd",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn(
            "UNMAPPED crd agents.kruise.io_unmappedfixtures.yaml",
            result.stdout,
        )

    def test_reports_missing_charts_checkout_as_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            source = (
                agents_repo
                / "config"
                / "crd"
                / "bases"
                / "agents.kruise.io_checkpoints.yaml"
            )
            source.parent.mkdir(parents=True)
            (agents_repo / "config" / "crd" / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_checkpoints.yaml\n",
                encoding="utf-8",
            )
            source.write_text(
                "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(root / "missing-charts"),
                    "--aspect",
                    "crd",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("ERROR missing charts checkout", result.stderr)

    def test_reports_mapped_drift_alongside_unmapped_crd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            charts_repo = root / "charts"
            crd_dir = agents_repo / "config" / "crd"
            bases_dir = crd_dir / "bases"
            bases_dir.mkdir(parents=True)
            (charts_repo / "versions").mkdir(parents=True)
            (crd_dir / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_unmappedfixtures.yaml\n"
                "- bases/agents.kruise.io_checkpoints.yaml\n",
                encoding="utf-8",
            )
            (bases_dir / "agents.kruise.io_unmappedfixtures.yaml").write_text(
                "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n",
                encoding="utf-8",
            )
            (bases_dir / "agents.kruise.io_checkpoints.yaml").write_text(
                "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(charts_repo),
                    "--aspect",
                    "crd",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("UNMAPPED crd agents.kruise.io_unmappedfixtures.yaml", result.stdout)
        self.assertIn(
            "DRIFT crd controller "
            "versions/kruise-agents-sandbox-controller/next/crds/"
            "agents.kruise.io_checkpoints.yaml missing",
            result.stdout,
        )

    def test_does_not_copy_mapped_crd_when_another_crd_is_unmapped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            charts_repo = root / "charts"
            crd_dir = agents_repo / "config" / "crd"
            bases_dir = crd_dir / "bases"
            destination = (
                charts_repo
                / "versions"
                / "kruise-agents-sandbox-controller"
                / "next"
                / "crds"
                / "agents.kruise.io_checkpoints.yaml"
            )
            bases_dir.mkdir(parents=True)
            (charts_repo / "versions").mkdir(parents=True)
            (crd_dir / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_unmappedfixtures.yaml\n"
                "- bases/agents.kruise.io_checkpoints.yaml\n",
                encoding="utf-8",
            )
            (bases_dir / "agents.kruise.io_unmappedfixtures.yaml").write_text(
                "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n",
                encoding="utf-8",
            )
            (bases_dir / "agents.kruise.io_checkpoints.yaml").write_text(
                "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(charts_repo),
                    "--aspect",
                    "crd",
                    "--apply-crds",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse(destination.exists())
        self.assertNotIn("SYNCED crd", result.stdout)

    def test_copies_mapped_crd_when_apply_is_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            charts_repo = root / "charts"
            source = (
                agents_repo
                / "config"
                / "crd"
                / "bases"
                / "agents.kruise.io_checkpoints.yaml"
            )
            destination = (
                charts_repo
                / "versions"
                / "kruise-agents-sandbox-controller"
                / "next"
                / "crds"
                / "agents.kruise.io_checkpoints.yaml"
            )
            source.parent.mkdir(parents=True)
            destination.parent.mkdir(parents=True)
            (agents_repo / "config" / "crd" / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_checkpoints.yaml\n",
                encoding="utf-8",
            )
            source.write_bytes(b"apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(charts_repo),
                    "--aspect",
                    "crd",
                    "--apply-crds",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertIn("SYNCED crd controller", result.stdout)

    def test_copies_commits_crd_to_controller_chart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            charts_repo = root / "charts"
            source = (
                agents_repo
                / "config"
                / "crd"
                / "bases"
                / "agents.kruise.io_commits.yaml"
            )
            destination = (
                charts_repo
                / "versions"
                / "kruise-agents-sandbox-controller"
                / "next"
                / "crds"
                / "agents.kruise.io_commits.yaml"
            )
            source.parent.mkdir(parents=True)
            (charts_repo / "versions").mkdir(parents=True)
            (agents_repo / "config" / "crd" / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_commits.yaml\n",
                encoding="utf-8",
            )
            source.write_bytes(
                b"apiVersion: apiextensions.k8s.io/v1\n"
                b"kind: CustomResourceDefinition\n"
                b"metadata:\n"
                b"  name: commits.agents.kruise.io\n"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(charts_repo),
                    "--aspect",
                    "crd",
                    "--apply-crds",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertIn(
                "SYNCED crd controller "
                "versions/kruise-agents-sandbox-controller/next/crds/"
                "agents.kruise.io_commits.yaml",
                result.stdout,
            )

    def test_copies_poolautoscalers_crd_to_controller_chart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            charts_repo = root / "charts"
            source = (
                agents_repo
                / "config"
                / "crd"
                / "bases"
                / "agents.kruise.io_poolautoscalers.yaml"
            )
            destination = (
                charts_repo
                / "versions"
                / "kruise-agents-sandbox-controller"
                / "next"
                / "crds"
                / "agents.kruise.io_poolautoscalers.yaml"
            )
            source.parent.mkdir(parents=True)
            (charts_repo / "versions").mkdir(parents=True)
            (agents_repo / "config" / "crd" / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_poolautoscalers.yaml\n",
                encoding="utf-8",
            )
            source.write_bytes(
                b"apiVersion: apiextensions.k8s.io/v1\n"
                b"kind: CustomResourceDefinition\n"
                b"metadata:\n"
                b"  name: poolautoscalers.agents.kruise.io\n"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(charts_repo),
                    "--aspect",
                    "crd",
                    "--apply-crds",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertIn(
                "SYNCED crd controller "
                "versions/kruise-agents-sandbox-controller/next/crds/"
                "agents.kruise.io_poolautoscalers.yaml",
                result.stdout,
            )

    def test_copies_securityprofiles_crd_to_manager_chart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_repo = root / "agents"
            charts_repo = root / "charts"
            source = (
                agents_repo
                / "config"
                / "crd"
                / "bases"
                / "agents.kruise.io_securityprofiles.yaml"
            )
            destination = (
                charts_repo
                / "versions"
                / "kruise-agents-sandbox-manager"
                / "next"
                / "files"
                / "agentio"
                / "securityprofile-crd.yaml"
            )
            source.parent.mkdir(parents=True)
            (charts_repo / "versions").mkdir(parents=True)
            (agents_repo / "config" / "crd" / "kustomization.yaml").write_text(
                "resources:\n"
                "- bases/agents.kruise.io_securityprofiles.yaml\n",
                encoding="utf-8",
            )
            source.write_bytes(
                b"apiVersion: apiextensions.k8s.io/v1\n"
                b"kind: CustomResourceDefinition\n"
                b"metadata:\n"
                b"  name: securityprofiles.agents.kruise.io\n"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--agents-repo",
                    str(agents_repo),
                    "--charts-repo",
                    str(charts_repo),
                    "--aspect",
                    "crd",
                    "--apply-crds",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertIn(
                "SYNCED crd manager "
                "versions/kruise-agents-sandbox-manager/next/files/agentio/"
                "securityprofile-crd.yaml",
                result.stdout,
            )

    def test_documents_identity_resource_synchronization(self) -> None:
        content = SKILL.read_text(encoding="utf-8")

        self.assertIn("## Identity Resources", content)
        self.assertIn("> /tmp/manager-chart.yaml", content)
        for requirement in (
            "controller `templates/rbac.yaml`",
            "manager `templates/rbac.yaml`",
            "preserve `{{ ... }}`",
            "excluding `app.kubernetes.io/managed-by: kustomize`",
            "chart-managed standard `app.kubernetes.io/*` keys win",
            "roleRef `apiGroup` and `kind`",
            "chart's existing namespace helper",
            "source role counterpart",
            "source-rendered binding in the table",
            "exactly one chart counterpart of the same kind",
            "roleRef targets by kind",
            "namePrefix: sandbox-",
            "namespace: sandbox-system",
            "pair bindings by kind",
            "config/sandbox-gateway/jwt-auth-rbac.yaml",
            "config/sandbox-gateway-runtime-mtls/rbac.yaml",
            "Identity resources require manual source-to-rendered review.",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, content)
        for source in (
            "config/rbac/service_account.yaml",
            "config/rbac/role_binding.yaml",
            "config/rbac/leader_election_role_binding.yaml",
            "config/sandbox-manager/serviceaccount.yaml",
            "config/sandbox-manager/rbac.yaml",
            "config/sandbox-gateway/serviceaccount.yaml",
            "config/sandbox-gateway/rbac.yaml",
        ):
            with self.subTest(source=source):
                self.assertIn(source, content)


if __name__ == "__main__":
    unittest.main()
