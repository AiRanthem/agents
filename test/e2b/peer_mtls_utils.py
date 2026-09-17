"""Helpers for the latest-pipeline peer mTLS E2E tests."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests

NS = "sandbox-system"
RUNTIME_NAME = "agentruntime.sandbox.agents.kruise.io"
ECHO_PORT = 18080
FIXTURE_DIR = Path("/tmp/peer-mtls-e2e")
SENTINEL_STATE = "running"


class PeerMTLSFailure(AssertionError):
    """Test failure with a diagnostic class prefix."""


def require_peer_mtls_env() -> None:
    if os.environ.get("PEER_MTLS_E2E") != "true":
        raise PeerMTLSFailure(
            "deploy failure: PEER_MTLS_E2E is not true; peer mTLS tests must fail, not skip"
        )
    if not (FIXTURE_DIR / "ca-a.crt").is_file():
        raise PeerMTLSFailure("deploy failure: peer mTLS CA file is missing")
    for name in ("manager.fp", "gateway.fp", "helper.fp"):
        if not (FIXTURE_DIR / name).is_file():
            raise PeerMTLSFailure(f"deploy failure: fingerprint file {name} is missing")


def read_fingerprint(owner: str) -> str:
    return (FIXTURE_DIR / f"{owner}.fp").read_text().strip()


def ca_file() -> str:
    return str(FIXTURE_DIR / "ca-a.crt")


def kubectl_jsonpath(args: List[str]) -> str:
    result = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise PeerMTLSFailure(
            f"deploy failure: kubectl {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return (result.stdout or "").strip()


def pod_name(label: str) -> str:
    name = kubectl_jsonpath(
        [
            "get",
            "pod",
            "-n",
            NS,
            "-l",
            label,
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ]
    )
    if not name:
        raise PeerMTLSFailure(f"deploy failure: no pod matched {label}")
    return name


def pod_ip(name: str) -> str:
    ip = kubectl_jsonpath(
        ["get", "pod", name, "-n", NS, "-o", "jsonpath={.status.podIP}"]
    )
    if not ip:
        raise PeerMTLSFailure(f"deploy failure: pod {name} has no IP")
    return ip


def echo_body(key: str) -> str:
    path = FIXTURE_DIR / f"{key}-body"
    if not path.is_file():
        raise PeerMTLSFailure(f"deploy failure: fixture file {path} is missing")
    return path.read_text().strip()


def wait_port(host: str, port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise PeerMTLSFailure(f"deploy failure: port-forward {host}:{port} did not become ready")


class PortForward:
    def __init__(self, resource: str, remote_port: int, local_port: int = 0):
        if local_port == 0:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            local_port = sock.getsockname()[1]
            sock.close()
        self.local_port = local_port
        self.proc = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                "-n",
                NS,
                resource,
                f"{local_port}:{remote_port}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            wait_port("127.0.0.1", local_port)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@contextmanager
def port_forward(resource: str, remote_port: int) -> Iterator[int]:
    pf = PortForward(resource, remote_port)
    try:
        yield pf.local_port
    finally:
        pf.close()


def helper_request(method: str, path: str, port: int, json_body: Any = None, timeout: float = 10.0):
    url = f"http://127.0.0.1:{port}{path}"
    response = requests.request(method, url, json=json_body, timeout=timeout)
    return response


def send_route(admin_port: int, peer_ips: List[str], route: Dict[str, Any], identity: str = "helper") -> Dict[str, Any]:
    response = helper_request(
        "POST",
        "/send",
        admin_port,
        {"peerIPs": peer_ips, "identity": identity, "route": route},
        timeout=15.0,
    )
    if response.status_code != 200:
        raise PeerMTLSFailure(
            f"TLS identity failure: helper /send HTTP {response.status_code}: {response.text}"
        )
    return response.json()


def helper_events(admin_port: int) -> List[Dict[str, Any]]:
    response = helper_request("GET", "/events", admin_port)
    response.raise_for_status()
    return response.json()


def helper_stats(admin_port: int) -> Dict[str, Any]:
    response = helper_request("GET", "/stats", admin_port)
    response.raise_for_status()
    return response.json()


def reset_helper_events(admin_port: int) -> None:
    helper_request("POST", "/events/reset", admin_port).raise_for_status()


def reset_helper_stats(admin_port: int) -> None:
    helper_request("POST", "/stats/reset", admin_port).raise_for_status()


def new_sentinel_route(backend_ip: str, resource_version: str, suffix: str) -> Dict[str, Any]:
    token = uuid.uuid4().hex[:12]
    name = f"peer-mtls-{suffix}-{token}"
    return {
        "ip": backend_ip,
        "id": name,
        "namespace": "peer-mtls",
        "name": name,
        "uid": str(uuid.uuid4()),
        "owner": "peer-mtls-e2e",
        "state": SENTINEL_STATE,
        "resourceVersion": resource_version,
        "requireTrafficAuth": False,
        "wakeOnTraffic": False,
    }


def dataplane_get(local_port: int, sandbox_id: str, timeout: float = 5.0) -> requests.Response:
    return requests.get(
        f"http://127.0.0.1:{local_port}/",
        headers={
            "Host": "localhost",
            "e2b-sandbox-id": sandbox_id,
            "e2b-sandbox-port": str(ECHO_PORT),
        },
        timeout=timeout,
    )


def wait_dataplane_body(local_port: int, sandbox_id: str, expected: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last: Optional[requests.Response] = None
    while time.monotonic() < deadline:
        last = dataplane_get(local_port, sandbox_id)
        if last.status_code == 200 and last.text == expected:
            return
        time.sleep(0.4)
    body = last.text if last is not None else "no response"
    code = last.status_code if last is not None else "n/a"
    raise PeerMTLSFailure(
        f"route not applied: dataplane for {sandbox_id} got {code} {body!r}, want {expected!r}"
    )


def assert_dataplane_body(local_port: int, sandbox_id: str, expected: str) -> None:
    response = dataplane_get(local_port, sandbox_id)
    if response.status_code != 200 or response.text != expected:
        raise PeerMTLSFailure(
            f"route not applied: dataplane for {sandbox_id} got "
            f"{response.status_code} {response.text!r}, want {expected!r}"
        )


def curl_https(
    local_port: int,
    path: str,
    method: str = "GET",
    data: Optional[str] = None,
    client_cert: Optional[str] = None,
    client_key: Optional[str] = None,
    timeout: int = 10,
) -> subprocess.CompletedProcess:
    cmd = [
        "curl",
        "-sS",
        "-o",
        "-",
        "-w",
        "\n%{http_code}",
        "--max-time",
        str(timeout),
        "--cacert",
        ca_file(),
        "--resolve",
        f"{RUNTIME_NAME}:{local_port}:127.0.0.1",
        "-X",
        method,
        f"https://{RUNTIME_NAME}:{local_port}{path}",
    ]
    if data is not None:
        cmd.extend(["-H", "Content-Type: application/json", "--data", data])
    if client_cert and client_key:
        cmd.extend(["--cert", client_cert, "--key", client_key])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)


def split_curl_output(proc: subprocess.CompletedProcess) -> tuple[str, str]:
    out = proc.stdout or ""
    if "\n" not in out:
        return out, ""
    body, code = out.rsplit("\n", 1)
    return body, code.strip()


def is_tls_error(message: str) -> bool:
    low = (message or "").lower()
    needles = (
        "x509",
        "tls:",
        "ssl",
        "certificate",
        "handshake",
        "unknown authority",
        "not authenticated",
        "bad certificate",
        "certificate required",
        "remote error",
    )
    return any(n in low for n in needles)


def wait_for_event(
    admin_port: int,
    fingerprint: str,
    route_id: str,
    timeout: float = 90.0,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: List[Dict[str, Any]] = []
    while time.monotonic() < deadline:
        last = helper_events(admin_port)
        for event in last:
            if (
                event.get("clientCertFingerprint") == fingerprint
                and event.get("routeID") == route_id
            ):
                return event
        time.sleep(1)
    raise PeerMTLSFailure(
        f"TLS identity failure: no witness event for route {route_id} "
        f"with expected fingerprint; saw {len(last)} events"
    )
