#!/usr/bin/env bash
# Copyright 2026 The Kruise Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

# Do not enable xtrace: this script handles certificate material.

NS="${PEER_MTLS_NAMESPACE:-sandbox-system}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ASSETS_DIR="$PROJECT_ROOT/test/e2b/assets/peer-mtls"
RUNTIME_NAME="agentruntime.sandbox.agents.kruise.io"

usage() {
    echo "Usage: $0 secrets|workloads|junit [junit.xml]" >&2
    exit 1
}

fingerprint() {
    openssl x509 -in "$1" -outform DER | openssl dgst -sha256 -hex | awk '{print $2}'
}

issue_leaf() {
    local dir="$1" name="$2" ca_crt="$3" ca_key="$4" ext="$5"
    openssl req -newkey rsa:2048 -nodes \
        -keyout "$dir/${name}.key" -out "$dir/${name}.csr" \
        -subj "/CN=${name}" >/dev/null 2>&1
    openssl x509 -req -days 2 -sha256 \
        -in "$dir/${name}.csr" -CA "$ca_crt" -CAkey "$ca_key" -CAcreateserial \
        -out "$dir/${name}.crt" -extfile "$ext" >/dev/null 2>&1
}

create_tls_secret() {
    local name="$1" crt="$2" key="$3" ca="$4"
    kubectl create secret generic "$name" -n "$NS" \
        --from-file=tls.crt="$crt" \
        --from-file=tls.key="$key" \
        --from-file=ca.crt="$ca" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

create_client_secret() {
    local name="$1" crt="$2" key="$3" ca="$4"
    kubectl create secret generic "$name" -n "$NS" \
        --from-file=client.crt="$crt" \
        --from-file=client.key="$key" \
        --from-file=ca.crt="$ca" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

cmd_secrets() {
    local cert_dir
    cert_dir="$(mktemp -d)"
    chmod 700 "$cert_dir"
    trap 'rm -rf "$cert_dir"' EXIT
    umask 077

    openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
        -keyout "$cert_dir/ca-a.key" -out "$cert_dir/ca-a.crt" \
        -subj "/CN=peer-mtls-e2e-ca-a" >/dev/null 2>&1
    openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
        -keyout "$cert_dir/ca-b.key" -out "$cert_dir/ca-b.crt" \
        -subj "/CN=peer-mtls-e2e-ca-b" >/dev/null 2>&1

    printf 'subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\n' "$RUNTIME_NAME" >"$cert_dir/server.ext"
    printf 'extendedKeyUsage=clientAuth\n' >"$cert_dir/client.ext"
    printf 'subjectAltName=DNS:wrong.example\nextendedKeyUsage=serverAuth\n' >"$cert_dir/wrong-san.ext"
    # M09 EKU leg: the expected SAN but clientAuth only, so rejection must come
    # from key usage, not from hostname verification.
    printf 'subjectAltName=DNS:%s\nextendedKeyUsage=clientAuth\n' "$RUNTIME_NAME" >"$cert_dir/wrong-eku.ext"

    issue_leaf "$cert_dir" server "$cert_dir/ca-a.crt" "$cert_dir/ca-a.key" "$cert_dir/server.ext"
    issue_leaf "$cert_dir" manager-client "$cert_dir/ca-a.crt" "$cert_dir/ca-a.key" "$cert_dir/client.ext"
    issue_leaf "$cert_dir" gateway-client "$cert_dir/ca-a.crt" "$cert_dir/ca-a.key" "$cert_dir/client.ext"
    issue_leaf "$cert_dir" helper-client "$cert_dir/ca-a.crt" "$cert_dir/ca-a.key" "$cert_dir/client.ext"
    issue_leaf "$cert_dir" wrong-san "$cert_dir/ca-a.crt" "$cert_dir/ca-a.key" "$cert_dir/wrong-san.ext"
    issue_leaf "$cert_dir" untrusted-server "$cert_dir/ca-b.crt" "$cert_dir/ca-b.key" "$cert_dir/server.ext"
    issue_leaf "$cert_dir" untrusted-client "$cert_dir/ca-b.crt" "$cert_dir/ca-b.key" "$cert_dir/client.ext"
    # clientAuth-only leaf reused as a remote server certificate for M09 EKU.
    issue_leaf "$cert_dir" wrong-eku "$cert_dir/ca-a.crt" "$cert_dir/ca-a.key" "$cert_dir/wrong-eku.ext"

    create_tls_secret peer-mtls-server "$cert_dir/server.crt" "$cert_dir/server.key" "$cert_dir/ca-a.crt"
    create_client_secret peer-mtls-manager-client "$cert_dir/manager-client.crt" "$cert_dir/manager-client.key" "$cert_dir/ca-a.crt"
    create_client_secret peer-mtls-gateway-client "$cert_dir/gateway-client.crt" "$cert_dir/gateway-client.key" "$cert_dir/ca-a.crt"
    create_client_secret peer-mtls-helper-client "$cert_dir/helper-client.crt" "$cert_dir/helper-client.key" "$cert_dir/ca-a.crt"
    create_client_secret peer-mtls-untrusted-client "$cert_dir/untrusted-client.crt" "$cert_dir/untrusted-client.key" "$cert_dir/ca-b.crt"
    create_tls_secret peer-mtls-untrusted-server "$cert_dir/untrusted-server.crt" "$cert_dir/untrusted-server.key" "$cert_dir/ca-b.crt"
    create_tls_secret peer-mtls-wrong-san-server "$cert_dir/wrong-san.crt" "$cert_dir/wrong-san.key" "$cert_dir/ca-a.crt"
    create_tls_secret peer-mtls-wrong-eku-server "$cert_dir/wrong-eku.crt" "$cert_dir/wrong-eku.key" "$cert_dir/ca-a.crt"

    kubectl apply -f "$ASSETS_DIR/rbac.yaml" >/dev/null

    mkdir -p /tmp/peer-mtls-e2e
    chmod 700 /tmp/peer-mtls-e2e
    cp "$cert_dir/ca-a.crt" /tmp/peer-mtls-e2e/ca-a.crt
    printf '%s\n' "$(fingerprint "$cert_dir/manager-client.crt")" >/tmp/peer-mtls-e2e/manager.fp
    printf '%s\n' "$(fingerprint "$cert_dir/gateway-client.crt")" >/tmp/peer-mtls-e2e/gateway.fp
    printf '%s\n' "$(fingerprint "$cert_dir/helper-client.crt")" >/tmp/peer-mtls-e2e/helper.fp
    echo "peer-mtls secrets created"
}

wait_rollout() {
    local deploy="$1"
    kubectl rollout status "deployment/${deploy}" -n "$NS" --timeout=180s
}

wait_membership() {
    local pod i members
    pod="$(kubectl get pod -n "$NS" -l app.kubernetes.io/name=peer-mtls-witness -o jsonpath='{.items[0].metadata.name}')"
    kubectl port-forward -n "$NS" "pod/${pod}" 18081:18081 >/tmp/peer-mtls-e2e/witness-pf.log 2>&1 &
    local pf_pid=$!
    trap 'kill "$pf_pid" 2>/dev/null || true' RETURN
    for i in $(seq 1 90); do
        if members="$(curl -sf http://127.0.0.1:18081/members 2>/dev/null)"; then
            if echo "$members" | grep -q '"name":"sm-' && echo "$members" | grep -q '"name":"sg-'; then
                echo "peer-mtls membership includes manager and gateway"
                kill "$pf_pid" 2>/dev/null || true
                wait "$pf_pid" 2>/dev/null || true
                trap - RETURN
                return 0
            fi
        fi
        sleep 2
    done
    echo "membership not found: witness did not observe sm- and sg- members" >&2
    echo "$members" >&2
    return 1
}

cmd_workloads() {
    local nonce echo_a echo_b rendered
    nonce="$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')"
    echo_a="peer-route-A-${nonce}"
    echo_b="peer-route-B-${nonce}"
    mkdir -p /tmp/peer-mtls-e2e
    printf '%s\n' "$nonce" >/tmp/peer-mtls-e2e/nonce
    printf '%s\n' "$echo_a" >/tmp/peer-mtls-e2e/echo-a-body
    printf '%s\n' "$echo_b" >/tmp/peer-mtls-e2e/echo-b-body

    rendered="$(mktemp)"
    sed \
        -e "s/PLACEHOLDER_NONCE/${nonce}/g" \
        -e "s/PLACEHOLDER_ECHO_A/${echo_a}/g" \
        -e "s/PLACEHOLDER_ECHO_B/${echo_b}/g" \
        "$ASSETS_DIR/workloads.yaml.tmpl" >"$rendered"
    kubectl apply -f "$rendered"
    rm -f "$rendered"

    wait_rollout peer-mtls-echo-a
    wait_rollout peer-mtls-echo-b
    wait_rollout peer-mtls-witness
    wait_rollout peer-mtls-wrong-ca
    wait_rollout peer-mtls-wrong-san
    wait_rollout peer-mtls-wrong-eku
    wait_rollout peer-mtls-plaintext
    wait_membership
}

cmd_junit() {
    local xml="${1:-test/e2b/reports/junit.xml}"
    python3 - "$xml" <<'PY'
import sys
import xml.etree.ElementTree as ET

tree = ET.parse(sys.argv[1])
for suite in tree.iter("testsuite"):
    print(
        "tests=%s failures=%s errors=%s skipped=%s"
        % (
            suite.attrib.get("tests"),
            suite.attrib.get("failures"),
            suite.attrib.get("errors"),
            suite.attrib.get("skipped"),
        )
    )
    for case in suite.iter("testcase"):
        status = "passed"
        if case.find("skipped") is not None:
            status = "skipped"
        elif case.find("failure") is not None:
            status = "failure"
        elif case.find("error") is not None:
            status = "error"
        print("%s %s::%s" % (status, case.attrib.get("classname", ""), case.attrib.get("name", "")))
PY
}

case "${1:-}" in
    secrets) cmd_secrets ;;
    workloads) cmd_workloads ;;
    junit) shift; cmd_junit "$@" ;;
    *) usage ;;
esac
