"""Peer mTLS E2E for Manager and Gateway production send/receive paths."""

from __future__ import annotations

import json
import subprocess
import time

import pytest
import requests
from e2b_code_interpreter import Sandbox, SandboxState

import peer_mtls_utils as u
from utils import wait_sandbox_fully_paused

pytestmark = pytest.mark.peer_mtls


@pytest.fixture(scope="module")
def peer_mtls():
    u.require_peer_mtls_env()
    manager_pod = u.pod_name("app.kubernetes.io/name=sandbox-manager")
    gateway_pod = u.pod_name("app.kubernetes.io/name=sandbox-gateway")
    witness_pod = u.pod_name("app.kubernetes.io/name=peer-mtls-witness")
    echo_a_pod = u.pod_name("app.kubernetes.io/component=echo-a")
    echo_b_pod = u.pod_name("app.kubernetes.io/component=echo-b")
    ctx = {
        "manager_pod": manager_pod,
        "gateway_pod": gateway_pod,
        "witness_pod": witness_pod,
        "manager_ip": u.pod_ip(manager_pod),
        "gateway_ip": u.pod_ip(gateway_pod),
        "echo_a_ip": u.pod_ip(echo_a_pod),
        "echo_b_ip": u.pod_ip(echo_b_pod),
        "echo_a": u.echo_body("echo-a"),
        "echo_b": u.echo_body("echo-b"),
        "manager_fp": u.read_fingerprint("manager"),
        "gateway_fp": u.read_fingerprint("gateway"),
        "helper_fp": u.read_fingerprint("helper"),
        "wrong_ca_pod": u.pod_name("app.kubernetes.io/component=wrong-ca"),
        "wrong_san_pod": u.pod_name("app.kubernetes.io/component=wrong-san"),
        "wrong_eku_pod": u.pod_name("app.kubernetes.io/component=wrong-eku"),
        "plaintext_pod": u.pod_name("app.kubernetes.io/component=plaintext"),
    }
    pf = u.PortForward(f"pod/{witness_pod}", 18081)
    ctx["admin_port"] = pf.local_port
    try:
        yield ctx
    finally:
        pf.close()


def _apply(ctx, peer_ip: str, route: dict, identity: str = "helper") -> dict:
    result = u.send_route(ctx["admin_port"], [peer_ip], route, identity=identity)
    return result


def _delete(ctx, peer_ip: str, route: dict) -> None:
    dead = dict(route)
    dead["state"] = "dead"
    u.send_route(ctx["admin_port"], [peer_ip], dead)


@pytest.fixture(params=["manager", "gateway"])
def sentinel_target(request, peer_mtls):
    kind = request.param
    with u.port_forward(f"pod/{peer_mtls[f'{kind}_pod']}", 7788) as port:
        yield {
            "kind": kind,
            "peer_ip": peer_mtls[f"{kind}_ip"],
            "dataplane": port,
        }


@pytest.fixture
def manager_dataplane(peer_mtls):
    with u.port_forward(f"pod/{peer_mtls['manager_pod']}", 7788) as port:
        yield port


@pytest.fixture
def gateway_dataplane(peer_mtls):
    with u.port_forward(f"pod/{peer_mtls['gateway_pod']}", 7788) as port:
        yield port


def test_legal_peer_https_applies_sentinel(peer_mtls, sentinel_target):
    """M01/M02: production PeerOutbound applies a sentinel route on the receiver."""
    kind = sentinel_target["kind"]
    peer_ip = sentinel_target["peer_ip"]
    route = u.new_sentinel_route(peer_mtls["echo_a_ip"], "1", f"m01-{kind}")
    result = _apply(peer_mtls, peer_ip, route)
    assert result.get("ok") is True, result
    assert result.get("tlsConfigured") is True, result
    try:
        u.wait_dataplane_body(sentinel_target["dataplane"], route["id"], peer_mtls["echo_a"])
    finally:
        _delete(peer_mtls, peer_ip, route)


def test_real_manager_publish_reaches_witness(peer_mtls, sandbox_context):
    """M03: a real SDK create is witnessed with the Manager client certificate."""
    u.reset_helper_events(peer_mtls["admin_port"])
    sbx = sandbox_context.add(
        Sandbox.create(
            template="code-interpreter",
            timeout=120,
            metadata={"test_case": "test_real_manager_publish_reaches_witness"},
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    event = u.wait_for_event(
        peer_mtls["admin_port"],
        fingerprint=peer_mtls["manager_fp"],
        route_id=sbx.sandbox_id,
    )
    assert event["clientCertFingerprint"] == peer_mtls["manager_fp"]
    assert event["tlsVersion"] in ("TLS1.2", "TLS1.3")


def test_real_gateway_wake_publish_reaches_witness(peer_mtls, sandbox_context):
    """M04: a single traffic wake is witnessed with the Gateway client certificate."""
    sbx = sandbox_context.add(
        Sandbox.create(
            template="code-interpreter",
            timeout=120,
            lifecycle={"on_timeout": "pause", "auto_resume": True},
            metadata={"test_case": "test_real_gateway_wake_publish_reaches_witness"},
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    assert sbx.get_info().state == SandboxState.RUNNING
    deadline = time.time() + 240
    while time.time() < deadline:
        if sbx.get_info().state == SandboxState.PAUSED:
            break
        time.sleep(2)
    else:
        raise u.PeerMTLSFailure("route not applied: sandbox did not pause")
    wait_sandbox_fully_paused(sbx)

    u.reset_helper_events(peer_mtls["admin_port"])

    headers = {
        "e2b-sandbox-id": sbx.sandbox_id,
        "e2b-sandbox-port": "49983",
    }
    token = getattr(sbx, "_envd_access_token", None)
    if token:
        headers["x-access-token"] = token
    # Single business request; retries belong to witness observation only.
    requests.get("http://localhost:80/", headers=headers, timeout=180)

    event = u.wait_for_event(
        peer_mtls["admin_port"],
        fingerprint=peer_mtls["gateway_fp"],
        route_id=sbx.sandbox_id,
    )
    assert event["clientCertFingerprint"] == peer_mtls["gateway_fp"]
    assert event["tlsVersion"] in ("TLS1.2", "TLS1.3")


def _baseline(peer_mtls, dataplane, peer_ip: str, suffix: str):
    route = u.new_sentinel_route(peer_mtls["echo_a_ip"], "1", suffix)
    result = _apply(peer_mtls, peer_ip, route)
    assert result.get("ok") is True, result
    u.wait_dataplane_body(dataplane, route["id"], peer_mtls["echo_a"])
    return route


def _redirect(route: dict, ip: str) -> dict:
    """Attacker variant: redirect the route to the echo-b backend at a newer resourceVersion."""
    attack = dict(route)
    attack["ip"] = ip
    attack["resourceVersion"] = "2"
    return attack


def test_manager_refresh_without_client_cert_fails_tls(
    peer_mtls, manager_dataplane
):
    """M05: Manager /refresh without a client certificate fails at TLS."""
    baseline = _baseline(peer_mtls, manager_dataplane, peer_mtls["manager_ip"], "m05")
    attacker = _redirect(baseline, peer_mtls["echo_b_ip"])
    try:
        with u.port_forward(f"pod/{peer_mtls['manager_pod']}", 7789) as port:
            proc = u.curl_https(
                port, "/refresh", method="POST", data=json.dumps(attacker)
            )
            body, code = u.split_curl_output(proc)
            combined = f"{proc.stderr} {body} {code}"
            assert proc.returncode != 0 or code not in ("200", "204"), combined
            assert "204" != code
            assert u.is_tls_error(combined) or code in ("", "000")
        u.assert_dataplane_body(manager_dataplane, baseline["id"], peer_mtls["echo_a"])
    finally:
        _delete(peer_mtls, peer_mtls["manager_ip"], baseline)


def test_gateway_refresh_without_client_cert_http_403(
    peer_mtls, gateway_dataplane
):
    """M06: Gateway /refresh without a client certificate is HTTP 403 after TLS."""
    baseline = _baseline(peer_mtls, gateway_dataplane, peer_mtls["gateway_ip"], "m06")
    attacker = _redirect(baseline, peer_mtls["echo_b_ip"])
    try:
        with u.port_forward(f"pod/{peer_mtls['gateway_pod']}", 7789) as port:
            proc = u.curl_https(
                port, "/refresh", method="POST", data=json.dumps(attacker)
            )
            body, code = u.split_curl_output(proc)
            combined = f"{proc.stderr} {body} {code}"
            assert proc.returncode == 0, combined
            assert code == "403", combined
        u.assert_dataplane_body(gateway_dataplane, baseline["id"], peer_mtls["echo_a"])
        legal = _apply(peer_mtls, peer_mtls["gateway_ip"], attacker)
        assert legal.get("ok") is True, legal
        u.wait_dataplane_body(gateway_dataplane, attacker["id"], peer_mtls["echo_b"])
    finally:
        _delete(peer_mtls, peer_mtls["gateway_ip"], attacker)


def test_gateway_https_health_without_client_cert(peer_mtls):
    """M07: Gateway HTTPS /healthz and /readyz succeed without a client certificate."""
    with u.port_forward(f"pod/{peer_mtls['gateway_pod']}", 7789) as port:
        health = u.curl_https(port, "/healthz")
        health_body, health_code = u.split_curl_output(health)
        assert health.returncode == 0, health.stderr
        assert health_code == "200", health_body
        ready = u.curl_https(port, "/readyz")
        ready_body, ready_code = u.split_curl_output(ready)
        assert ready.returncode == 0, ready.stderr
        assert ready_code == "200", ready_body


def test_untrusted_and_wrong_eku_client_rejected(
    peer_mtls, manager_dataplane, gateway_dataplane
):
    """M08: untrusted and wrong-EKU clients are rejected and cannot change routes."""
    mgr = _baseline(peer_mtls, manager_dataplane, peer_mtls["manager_ip"], "m08m")
    gw = _baseline(peer_mtls, gateway_dataplane, peer_mtls["gateway_ip"], "m08g")
    mgr_attack = _redirect(mgr, peer_mtls["echo_b_ip"])
    gw_attack = _redirect(gw, peer_mtls["echo_b_ip"])
    try:
        for identity in ("untrusted", "server-as-client"):
            for peer_ip, attack in (
                (peer_mtls["manager_ip"], mgr_attack),
                (peer_mtls["gateway_ip"], gw_attack),
            ):
                result = _apply(peer_mtls, peer_ip, attack, identity=identity)
                assert result.get("ok") is not True, result
                assert result.get("tlsConfigured") is True, result
                assert u.is_tls_error(result.get("error", "")), result
        u.assert_dataplane_body(manager_dataplane, mgr["id"], peer_mtls["echo_a"])
        u.assert_dataplane_body(gateway_dataplane, gw["id"], peer_mtls["echo_a"])
        assert _apply(peer_mtls, peer_mtls["manager_ip"], mgr_attack).get("ok") is True
        assert _apply(peer_mtls, peer_mtls["gateway_ip"], gw_attack).get("ok") is True
        u.wait_dataplane_body(manager_dataplane, mgr_attack["id"], peer_mtls["echo_b"])
        u.wait_dataplane_body(gateway_dataplane, gw_attack["id"], peer_mtls["echo_b"])
    finally:
        _delete(peer_mtls, peer_mtls["manager_ip"], mgr_attack)
        _delete(peer_mtls, peer_mtls["gateway_ip"], gw_attack)


def test_peer_outbound_rejects_bad_remote_identity(peer_mtls, manager_dataplane):
    """M09: production PeerOutbound rejects wrong CA, SAN, and EKU remotes."""
    legal = u.new_sentinel_route(peer_mtls["echo_a_ip"], "1", "m09ok")
    result = _apply(peer_mtls, peer_mtls["manager_ip"], legal)
    assert result.get("ok") is True, result
    assert result.get("tlsConfigured") is True, result
    try:
        u.wait_dataplane_body(manager_dataplane, legal["id"], peer_mtls["echo_a"])
        for label, component in (
            ("wrong CA", "wrong-ca"),
            ("wrong SAN", "wrong-san"),
            ("wrong EKU", "wrong-eku"),
        ):
            ip = u.pod_ip(u.pod_name(f"app.kubernetes.io/component={component}"))
            failed = _apply(peer_mtls, ip, legal)
            assert failed.get("ok") is not True, (label, failed)
            assert failed.get("tlsConfigured") is True, (label, failed)
            assert u.is_tls_error(failed.get("error", "")), (label, failed)
            assert "http://" not in (failed.get("error") or "")
        u.assert_dataplane_body(manager_dataplane, legal["id"], peer_mtls["echo_a"])
    finally:
        _delete(peer_mtls, peer_mtls["manager_ip"], legal)


def test_peer_outbound_does_not_fallback_to_plaintext(peer_mtls):
    """M10: TLS PeerOutbound does not send HTTP /refresh to a plaintext 7789."""
    plaintext_pod = peer_mtls["plaintext_pod"]
    plaintext_ip = u.pod_ip(plaintext_pod)
    assert_plaintext_probe_reachable(plaintext_pod)
    with u.port_forward(f"pod/{plaintext_pod}", 18081) as admin:
        u.reset_helper_stats(admin)
        before = u.helper_stats(admin)
        route = u.new_sentinel_route(peer_mtls["echo_a_ip"], "1", "m10")
        failed = _apply(peer_mtls, plaintext_ip, route)
        after = u.helper_stats(admin)
        assert failed.get("ok") is not True, failed
        assert failed.get("tlsConfigured") is True, failed
        assert after["refreshHits"] == before["refreshHits"] == 0
        assert after["accepts"] > before["accepts"]


def assert_plaintext_probe_reachable(pod: str) -> None:
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "--raw",
            f"/api/v1/namespaces/{u.NS}/pods/{pod}:18082/proxy/healthz",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise u.PeerMTLSFailure(
            f"deploy failure: plaintext probe endpoint is not reachable: {result.stderr}"
        )
