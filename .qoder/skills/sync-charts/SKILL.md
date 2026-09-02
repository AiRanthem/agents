---
name: sync-charts
description: Use when syncing OpenKruise Agents controller or sandbox-manager manifests from config/ into the openkruise/charts next directories, or when investigating drift between those sources.
---

# Sync Agents Charts

Keep `config/` as the source of truth, but preserve Helm-only logic in the charts checkout. This skill updates only unreleased `next/` content; it never cuts a release.

## Boundaries

- Work in a clean agents checkout and a clean charts checkout. Modify only `versions/kruise-agents-sandbox-{controller,manager}/next/**` in charts.
- Do not edit `config/crd/`, `templates/agentio/crds.yaml`, a released version directory, `Chart.yaml`, `values.yaml`, or `charts/` pointer files.
- Copy CRDs byte-for-byte only. Splice RBAC and webhook entries into the existing Helm templates; preserve every `{{ ... }}`, conditional, chart-only resource, and extra permission unless the user approves its removal.
- Manager has no webhook template. Do not create one.

## Preflight and Source Refresh

Set `CHARTS_REPO` to the charts checkout, then verify the required tools and clean trees:

```bash
for tool in helm yq gh python3 yamllint; do command -v "$tool" >/dev/null || exit 1; done
python3 -c 'import yaml'
test -x ./bin/kustomize || make kustomize
test -z "$(git status --porcelain -- config)"

test -z "$(git -C "$CHARTS_REPO" status --porcelain)"
test -d "$CHARTS_REPO/versions/kruise-agents-sandbox-controller/next"
test -d "$CHARTS_REPO/versions/kruise-agents-sandbox-manager/next"
```

Stop if either tree is dirty. Refresh generated manifests without manually editing them:

```bash
make manifests
test -z "$(git status --porcelain -- config)"
```

If `config/` changed, stop and resolve or commit that source change in the agents repository before syncing charts.

Create a charts branch from its current `origin/master` only after preflight:

```bash
git -C "$CHARTS_REPO" fetch origin master
git -C "$CHARTS_REPO" switch -c "sync/agents-config-$(date +%F)" origin/master
```

## CRDs

Run the checker before changing charts:

```bash
python3 .qoder/skills/sync-charts/scripts/chart_drift.py \
  --charts-repo "$CHARTS_REPO" --aspect crd
```

The checker follows only `config/crd/kustomization.yaml`. In check mode, it reports every mapped drift even when an unmapped resource exists; with `--apply-crds`, an unmapped resource exits `3` before any copy or drift report. Exit `0` means every source CRD is mapped and byte-identical, `1` means mapped drift when no resource is unmapped, `2` means the source or charts-checkout configuration is invalid or incomplete, and `3` means at least one resource has no chart mapping.

| Source resource | Chart target |
| --- | --- |
| `checkpoints`, `commits`, `poolautoscalers`, `sandboxclaims`, `sandboxes`, `sandboxsets`, `sandboxtemplates`, `sandboxupdateops` | `versions/kruise-agents-sandbox-controller/next/crds/agents.kruise.io_<name>.yaml` |
| `trafficpolicies`, `globaltrafficpolicies`, `securityprofiles`, `globalsecurityprofiles` | `versions/kruise-agents-sandbox-manager/next/files/agentio/<singular>-crd.yaml` |

If a future resource in `config/crd/kustomization.yaml` has no chart mapping, the checker exits `3` and blocks every `--apply-crds` copy, including mapped resources. Never manually perform a partial copy while that block exists, and never treat it as a time-pressure fast path: ask the user whether the charts should ship the new resource. Add an explicit `CHART_SPEC` mapping and update its test coverage in a separate reviewed skill change before retrying; do not make that policy decision inside a chart-sync PR. `--component` does not bypass this safeguard.

Once every kustomization resource is mapped, copy and recheck with:

```bash
python3 .qoder/skills/sync-charts/scripts/chart_drift.py \
  --charts-repo "$CHARTS_REPO" --aspect crd --apply-crds
python3 .qoder/skills/sync-charts/scripts/chart_drift.py \
  --charts-repo "$CHARTS_REPO" --aspect crd
```

## Webhook and RBAC Splices

Render the complete source overlay; never copy `config/webhook/manifests.yaml` directly because `patch_manifests.yaml` changes service references:

```bash
./bin/kustomize build config/default > /tmp/agents-default.yaml
```

Hand-merge the rendered `MutatingWebhookConfiguration` and `ValidatingWebhookConfiguration` into `versions/kruise-agents-sandbox-controller/next/templates/webhook.yaml`. Keep the chart's service name and replace the rendered fixed namespace with `{{ include "sandbox-controller.namespace" . }}`. Preserve template syntax and chart-specific names.

Hand-splice the `v-pa.kb.io` validating webhook into `versions/kruise-agents-sandbox-controller/next/templates/webhook.yaml` as well, keeping the chart service name and the templated namespace. Its entry must stay source-equivalent: `path: /validate-poolautoscaler`, `failurePolicy: Fail`, operations `CREATE` and `UPDATE`, `apiGroups: agents.kruise.io`, `apiVersions: v1alpha1`, resource `poolautoscalers`, `admissionReviewVersions` `v1` and `v1beta1`, and `sideEffects: None`.

After rendering the controller chart, compare the allowed webhook entries (`md-sbs.kb.io`, `md-sbt.kb.io`, `v-sbs.kb.io`, `v-sbt.kb.io`, `v-pa.kb.io`, `v-pod-delete.kb.io`, `v-pod-eviction.kb.io`, and `v-suo.kb.io`) in both outputs. For every entry, rules, paths, policies, selectors, admission-review versions, and side effects must match. For every chart entry, `{{ include "sandbox-controller.namespace" . }}` resolves to `sandbox-system` and is equivalent to the source fixed namespace. All eight source-patched entries must also retain their patched service names.

```bash
helm template sandbox-controller \
  "$CHARTS_REPO/versions/kruise-agents-sandbox-controller/next" \
  --namespace sandbox-system > /tmp/controller-chart.yaml
yq 'select(.kind == "MutatingWebhookConfiguration" or .kind == "ValidatingWebhookConfiguration")' /tmp/agents-default.yaml
yq 'select(.kind == "MutatingWebhookConfiguration" or .kind == "ValidatingWebhookConfiguration")' /tmp/controller-chart.yaml
```

Compare source `rules:` blocks and add missing rules only:

| Source | Helm target | Rules to splice |
| --- | --- | --- |
| `config/rbac/role.yaml` | controller `templates/rbac.yaml` | `controller-role` ClusterRole and namespaced Role |
| `config/rbac/leader_election_role.yaml` | controller `templates/rbac.yaml` | leader-election Role |
| `config/sandbox-manager/rbac.yaml` | manager `templates/rbac.yaml` | manager ClusterRole and secret Role |
| `config/sandbox-gateway/rbac.yaml` | manager `templates/rbac.yaml` | gateway ClusterRole |

## Identity Resources

Synchronize ServiceAccounts and RoleBinding/ClusterRoleBinding resources by hand-splicing source-defined behavior into the existing Helm templates. Do not byte-copy these resources: preserve `{{ ... }}`, chart names, the chart's existing namespace helper, chart-only labels and annotations, conditional blocks, and source-independent resources. Do not compare literal chart names: Helm generates chart names for every target. For controller sources, `config/default/kustomization.yaml` also applies `namePrefix: sandbox-` and `namespace: sandbox-system`; raw `subjects[].namespace: system` is a pre-render input, so inspect subjects only in the rendered default overlay.

| Source | Helm target | Fields to synchronize |
| --- | --- | --- |
| `config/rbac/service_account.yaml` | controller `templates/rbac.yaml` | controller ServiceAccount presence and source-defined labels |
| `config/rbac/role_binding.yaml` | controller `templates/rbac.yaml` | controller ClusterRoleBinding and RoleBinding `roleRef` and `subjects` |
| `config/rbac/leader_election_role_binding.yaml` | controller `templates/rbac.yaml` | leader-election RoleBinding `roleRef` and `subjects` |
| `config/sandbox-manager/serviceaccount.yaml` | manager `templates/rbac.yaml` | manager ServiceAccount presence, source-defined labels, and `automountServiceAccountToken` |
| `config/sandbox-manager/rbac.yaml` | manager `templates/rbac.yaml` | manager ClusterRoleBinding and secrets RoleBinding `roleRef` and `subjects` |
| `config/sandbox-gateway/serviceaccount.yaml` | manager `templates/rbac.yaml` | gateway ServiceAccount presence and source-defined labels |
| `config/sandbox-gateway/rbac.yaml` | manager `templates/rbac.yaml` | gateway ClusterRoleBinding `roleRef` and `subjects` |

Merge source labels additively, excluding `app.kubernetes.io/managed-by: kustomize`; that Kustomize bookkeeping label must not enter a Helm template. Retain chart-managed labels and annotations, so do not require literal equality of complete label sets. On conflict, chart-managed standard `app.kubernetes.io/*` keys win; add only source labels that the chart does not already manage. Keep the chart's name and namespace helpers in ServiceAccount references.

After rendering with `--namespace sandbox-system`, verify that each synchronized ServiceAccount exists and that every synchronized non-templated field, including `automountServiceAccountToken`, is source-equivalent. Each source-rendered binding in the table must have exactly one chart counterpart of the same kind; a missing or duplicate counterpart is drift. For every matched binding, compare roleRef `apiGroup` and `kind`, then verify that its rendered role name identifies the rendered source role counterpart. The controller ClusterRoleBinding and RoleBinding share names, so pair bindings by kind before comparing; a name match alone does not identify the counterpart. Pair roleRef targets by kind as well, because the source ClusterRole and Role share their rendered name. Each `subjects` entry for a ServiceAccount must retain `kind: ServiceAccount`, name the rendered chart ServiceAccount, and resolve through the chart's existing namespace helper to `sandbox-system`. Do not remove source-independent chart permissions, commented metrics/sample RBAC, or resources from optional overlays that are not included by `config/sandbox-gateway/kustomization.yaml`: `config/sandbox-gateway/jwt-auth-rbac.yaml` and `config/sandbox-gateway-runtime-mtls/rbac.yaml` are not drift when absent from the base rendered source.

Render the source resources and compare them against their chart output:

```bash
./bin/kustomize build config/default > /tmp/agents-default.yaml
./bin/kustomize build config/sandbox-manager > /tmp/agents-manager.yaml
./bin/kustomize build config/sandbox-gateway > /tmp/agents-gateway.yaml
helm template sandbox-controller \
  "$CHARTS_REPO/versions/kruise-agents-sandbox-controller/next" \
  --namespace sandbox-system > /tmp/controller-chart.yaml
helm template sandbox-manager \
  "$CHARTS_REPO/versions/kruise-agents-sandbox-manager/next" \
  --namespace sandbox-system \
  --set ingress.className=nginx --set e2b.adminApiKey=x > /tmp/manager-chart.yaml
```

Before accepting `/tmp/manager-chart.yaml`, inspect the manager templates for gateway conditionals. If a chart value gates gateway identity resources, render again with that value enabled and use that output for the gateway comparison; never treat a value-gated absence as parity.

```bash
yq 'select(.kind == "ServiceAccount" or .kind == "RoleBinding" or .kind == "ClusterRoleBinding")' /tmp/agents-default.yaml
yq 'select(.kind == "ServiceAccount" or .kind == "RoleBinding" or .kind == "ClusterRoleBinding")' /tmp/agents-manager.yaml
yq 'select(.kind == "ServiceAccount" or .kind == "RoleBinding" or .kind == "ClusterRoleBinding")' /tmp/agents-gateway.yaml
yq 'select(.kind == "ServiceAccount" or .kind == "RoleBinding" or .kind == "ClusterRoleBinding")' /tmp/controller-chart.yaml
yq 'select(.kind == "ServiceAccount" or .kind == "RoleBinding" or .kind == "ClusterRoleBinding")' /tmp/manager-chart.yaml
```

## Verification and PR

Render both charts before committing:

```bash
helm template sandbox-controller \
  "$CHARTS_REPO/versions/kruise-agents-sandbox-controller/next" \
  --namespace sandbox-system
helm template sandbox-manager \
  "$CHARTS_REPO/versions/kruise-agents-sandbox-manager/next" \
  --namespace sandbox-system \
  --set ingress.className=nginx --set e2b.adminApiKey=x
yamllint -c "$CHARTS_REPO/.github/configs/lintconf.yaml" \
  "$CHARTS_REPO/versions/kruise-agents-sandbox-controller/next" \
  "$CHARTS_REPO/versions/kruise-agents-sandbox-manager/next"
git -C "$CHARTS_REPO" status --short
```

The checker verifies CRDs only; webhook parity requires the rendered comparison above and RBAC splices require manual source-to-template review. Identity resources require manual source-to-rendered review. The final checker run must report no `DRIFT` and exit `0`, which requires every source CRD to be mapped and byte-identical; any `UNMAPPED` exit `3` marks a blocking unmapped resource, not a successful sync.

Commit with sign-off and create a charts PR that states the agents source SHA, the initial/final drift output, and CRD-upgrade impact. Do not change chart versions or release pointers in this PR.
