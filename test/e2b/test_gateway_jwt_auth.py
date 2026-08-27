"""E2E tests for sandbox-gateway TrafficAccessToken JWT authentication."""

import base64
import json
import os
import shlex
import subprocess
import time

import pytest
from e2b import PtySize
from e2b_code_interpreter import Sandbox
from kruise_agents.patch_traffic_token import patch_traffic_access_token
from websocket import WebSocketBadStatusException, create_connection

from gateway_utils import (
    TRAFFIC_ACCESS_TOKEN_HEADER,
    WORKLOAD_PORT,
    assert_workload_reached,
    gateway_request,
    gateway_request_eventually,
    get_sandbox_access_token,
    get_sandbox_uid,
    start_workload_server,
)


TOKEN_COMMAND = os.environ.get("JWT_E2E_TOKEN_COMMAND", "")
JWT_AUTH_METADATA_KEY = "security.agents.kruise.io/enable-jwt-auth"
# The gateway's own local reply for a failed UUID check. agent-runtime also
# authenticates x-access-token on its own, so on the runtime port the body is the
# only way to tell which layer rejected a request. Assertions that need an
# unambiguous answer use WORKLOAD_PORT instead.
GATEWAY_UNAUTHORIZED_BODY = "unauthorized: invalid or missing access token"
WEBSOCKET_PORT = 8080
WEBSOCKET_SERVER = r'''
import base64
import hashlib
import socket
import time

guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 8080))
    server.listen(1)
    with open("/tmp/jwt-websocket-ready", "w"):
        pass

    connection, _ = server.accept()
    with connection:
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = connection.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket client closed before handshake")
            request += chunk

        headers = {}
        for line in request.decode("latin1").split("\r\n")[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.lower()] = value.strip()

        key = headers["sec-websocket-key"]
        accept = base64.b64encode(
            hashlib.sha1((key + guid).encode()).digest()
        ).decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        connection.sendall(response.encode())
        time.sleep(1)
'''
pytestmark = [
    pytest.mark.jwt_auth,
    pytest.mark.skipif(
        os.environ.get("TRAFFIC_ACCESS_TOKEN_JWT_E2E", "").lower() != "true"
        or not TOKEN_COMMAND,
        reason="requires a JWT-enabled gateway and a token issuer command",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def enable_traffic_token_refresh_patch():
    patch_traffic_access_token()


def issue_traffic_access_token(sandbox_id, sandbox_uid, expired=False):
    command = shlex.split(TOKEN_COMMAND) + [
        "--sandbox-id",
        sandbox_id,
        "--sandbox-uid",
        sandbox_uid,
    ]
    if expired:
        command.append("--expired")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )
    token = result.stdout.strip()
    assert token, "token issuer command returned an empty token"
    return token


def token_expiration(token: str) -> int:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])


def sandbox_client_with_traffic_jwt(
    sandbox: Sandbox, traffic_jwt: str
) -> Sandbox:
    # The E2E issuer is external to sandbox-manager. Rebuild the client as if
    # CreateSandbox had returned the issued JWT, exercising the standalone
    # traffic-token patch at init.
    return Sandbox(
        sandbox_id=sandbox.sandbox_id,
        sandbox_domain=sandbox.sandbox_domain,
        envd_version=sandbox._envd_version,
        envd_access_token=sandbox._envd_access_token,
        traffic_access_token=traffic_jwt,
        connection_config=sandbox.connection_config,
    )


def gateway_websocket_url(config) -> str:
    if config.gateway_url.startswith("https://"):
        return config.gateway_url.replace("https://", "wss://", 1)
    return config.gateway_url.replace("http://", "ws://", 1)


def test_gateway_traffic_access_token_jwt(sandbox_context, config):
    """Verify route-selective JWT authentication and token validation."""
    first: Sandbox = sandbox_context.add(
        Sandbox.create(
            template=config.templates.code_interpreter,
            timeout=120,
            metadata={JWT_AUTH_METADATA_KEY: "true"},
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    second: Sandbox = sandbox_context.add(
        Sandbox.create(
            template=config.templates.code_interpreter,
            timeout=120,
            metadata={JWT_AUTH_METADATA_KEY: "true"},
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    public: Sandbox = sandbox_context.add(
        Sandbox.create(
            template=config.templates.code_interpreter,
            timeout=120,
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    first_token = issue_traffic_access_token(
        first.sandbox_id, get_sandbox_uid(first.sandbox_id)
    )
    first_runtime_token = get_sandbox_access_token(first.sandbox_id)
    second_runtime_token = get_sandbox_access_token(second.sandbox_id)
    public_runtime_token = get_sandbox_access_token(public.sandbox_id)
    assert first_runtime_token, "first Sandbox is missing its runtime access token"
    assert second_runtime_token, "second Sandbox is missing its runtime access token"
    assert public_runtime_token, "public Sandbox is missing its runtime access token"

    public_response = gateway_request_eventually(
        config, public.sandbox_id, public_runtime_token, None
    )
    assert public_response.status_code in (200, 404), public_response.text

    # A Sandbox that has not opted into JWT keeps the UUID baseline, so enabling
    # JWT mode must not leave it unprotected.
    public_wrong_token = gateway_request(
        config, public.sandbox_id, "wrong-runtime-token", None
    )
    assert public_wrong_token.status_code == 401, public_wrong_token.text
    assert GATEWAY_UNAUTHORIZED_BODY in public_wrong_token.text, (
        public_wrong_token.text
    )

    # Repeat the baseline column on a port served by the workload instead of
    # agent-runtime. Nothing there authenticates, so the rejections below are
    # unambiguously the gateway's and the acceptance proves end-to-end reach.
    start_workload_server(public)
    assert_workload_reached(
        gateway_request_eventually(
            config,
            public.sandbox_id,
            public_runtime_token,
            None,
            port=WORKLOAD_PORT,
        )
    )
    public_workload_wrong = gateway_request(
        config, public.sandbox_id, "wrong-runtime-token", None, port=WORKLOAD_PORT
    )
    assert public_workload_wrong.status_code == 401, public_workload_wrong.text
    public_workload_absent = gateway_request(
        config, public.sandbox_id, None, None, port=WORKLOAD_PORT
    )
    assert public_workload_absent.status_code == 401, public_workload_absent.text

    valid = gateway_request_eventually(
        config, first.sandbox_id, first_runtime_token, first_token
    )
    assert valid.status_code in (200, 404), valid.text

    missing = gateway_request(config, first.sandbox_id, first_runtime_token)
    assert missing.status_code == 403, missing.text

    malformed = gateway_request(
        config, first.sandbox_id, first_runtime_token, "not-a-jwt"
    )
    assert malformed.status_code == 403, malformed.text

    # The opted-in column on the workload port. Reaching the sandbox to start the
    # listener already requires a valid traffic token, so rebuild the client with
    # one first.
    start_workload_server(sandbox_client_with_traffic_jwt(first, first_token))
    assert_workload_reached(
        gateway_request_eventually(
            config,
            first.sandbox_id,
            first_runtime_token,
            first_token,
            port=WORKLOAD_PORT,
        )
    )
    first_workload_missing = gateway_request(
        config, first.sandbox_id, first_runtime_token, None, port=WORKLOAD_PORT
    )
    assert first_workload_missing.status_code == 403, first_workload_missing.text
    first_workload_malformed = gateway_request(
        config, first.sandbox_id, first_runtime_token, "not-a-jwt", port=WORKLOAD_PORT
    )
    assert first_workload_malformed.status_code == 403, (
        first_workload_malformed.text
    )

    expired_token = issue_traffic_access_token(
        first.sandbox_id, get_sandbox_uid(first.sandbox_id), expired=True
    )
    expired = gateway_request(
        config, first.sandbox_id, first_runtime_token, expired_token
    )
    assert expired.status_code == 403, expired.text

    second_ready = gateway_request_eventually(
        config, second.sandbox_id, second_runtime_token, "not-a-jwt"
    )
    assert second_ready.status_code == 403, second_ready.text

    replayed = gateway_request(
        config, second.sandbox_id, second_runtime_token, first_token
    )
    assert replayed.status_code == 403, replayed.text


@pytest.mark.jwt_auth_no_baseline
def test_gateway_traffic_access_token_jwt_without_uuid_baseline(
    sandbox_context, config
):
    """Verify JWT enforcement while the UUID baseline stays disabled.

    Covers upgrading a gateway that never had authentication enabled straight to
    JWT mode. Routes without the opt-in annotation must keep admitting the
    traffic they admitted before, while annotated routes stay fail closed.
    """
    protected: Sandbox = sandbox_context.add(
        Sandbox.create(
            template=config.templates.code_interpreter,
            timeout=120,
            metadata={JWT_AUTH_METADATA_KEY: "true"},
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    public: Sandbox = sandbox_context.add(
        Sandbox.create(
            template=config.templates.code_interpreter,
            timeout=120,
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    protected_token = issue_traffic_access_token(
        protected.sandbox_id, get_sandbox_uid(protected.sandbox_id)
    )
    protected_runtime_token = get_sandbox_access_token(protected.sandbox_id)
    public_runtime_token = get_sandbox_access_token(public.sandbox_id)
    assert protected_runtime_token, (
        "protected Sandbox is missing its runtime access token"
    )
    assert public_runtime_token, "public Sandbox is missing its runtime access token"

    public_response = gateway_request_eventually(
        config, public.sandbox_id, public_runtime_token, None
    )
    assert public_response.status_code in (200, 404), public_response.text

    # Every Sandbox carries a generated runtime access token, so a gateway that
    # started validating it here would break clients that never sent one. Prove
    # the request reaches the workload rather than merely missing one rejection
    # body: on WORKLOAD_PORT nothing authenticates, so a 200 carrying the fixed
    # body rules out both a revived UUID check (401) and JWT enforcement leaking
    # onto a route that never opted in (403).
    start_workload_server(public)
    assert_workload_reached(
        gateway_request_eventually(
            config,
            public.sandbox_id,
            "wrong-runtime-token",
            None,
            port=WORKLOAD_PORT,
        )
    )
    assert_workload_reached(
        gateway_request(config, public.sandbox_id, None, None, port=WORKLOAD_PORT)
    )

    # The runtime port cannot distinguish the two layers, so it only gets the
    # weaker check that the gateway's own rejection body is absent.
    wrong_runtime_token = gateway_request(
        config, public.sandbox_id, "wrong-runtime-token", None
    )
    assert GATEWAY_UNAUTHORIZED_BODY not in wrong_runtime_token.text, (
        wrong_runtime_token.text
    )

    absent_runtime_token = gateway_request(config, public.sandbox_id, None, None)
    assert GATEWAY_UNAUTHORIZED_BODY not in absent_runtime_token.text, (
        absent_runtime_token.text
    )

    # The opted-in column is unaffected by the disabled baseline.
    valid = gateway_request_eventually(
        config, protected.sandbox_id, protected_runtime_token, protected_token
    )
    assert valid.status_code in (200, 404), valid.text

    missing = gateway_request(config, protected.sandbox_id, protected_runtime_token)
    assert missing.status_code == 403, missing.text

    malformed = gateway_request(
        config, protected.sandbox_id, protected_runtime_token, "not-a-jwt"
    )
    assert malformed.status_code == 403, malformed.text

    start_workload_server(
        sandbox_client_with_traffic_jwt(protected, protected_token)
    )
    assert_workload_reached(
        gateway_request_eventually(
            config,
            protected.sandbox_id,
            protected_runtime_token,
            protected_token,
            port=WORKLOAD_PORT,
        )
    )
    protected_workload_missing = gateway_request(
        config,
        protected.sandbox_id,
        protected_runtime_token,
        None,
        port=WORKLOAD_PORT,
    )
    assert protected_workload_missing.status_code == 403, (
        protected_workload_missing.text
    )
    protected_workload_malformed = gateway_request(
        config,
        protected.sandbox_id,
        protected_runtime_token,
        "not-a-jwt",
        port=WORKLOAD_PORT,
    )
    assert protected_workload_malformed.status_code == 403, (
        protected_workload_malformed.text
    )


def test_gateway_traffic_access_token_jwt_with_e2b_sdk(sandbox_context, config):
    """Verify JWT authentication across E2B SDK data-plane transports."""
    sandbox: Sandbox = sandbox_context.add(
        Sandbox.create(
            template=config.templates.code_interpreter,
            timeout=120,
            metadata={JWT_AUTH_METADATA_KEY: "true"},
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    traffic_token = issue_traffic_access_token(
        sandbox.sandbox_id, get_sandbox_uid(sandbox.sandbox_id)
    )
    runtime_token = get_sandbox_access_token(sandbox.sandbox_id)
    assert runtime_token, "Sandbox is missing its runtime access token"

    ready = gateway_request_eventually(
        config, sandbox.sandbox_id, runtime_token, traffic_token
    )
    assert ready.status_code in (200, 404), ready.text

    missing = gateway_request(config, sandbox.sandbox_id, runtime_token)
    assert missing.status_code == 403, missing.text

    sandbox = sandbox_client_with_traffic_jwt(sandbox, traffic_token)
    assert sandbox.traffic_access_token == traffic_token

    assert sandbox.is_running()

    sandbox.files.write("/tmp/sdk-jwt-ok.txt", "files-jwt-ok")
    assert sandbox.files.read("/tmp/sdk-jwt-ok.txt") == "files-jwt-ok"

    result = sandbox.commands.run("echo commands-jwt-ok")
    assert result.exit_code == 0
    assert result.stdout.strip() == "commands-jwt-ok"

    pty = sandbox.pty.create(PtySize(rows=24, cols=80), timeout=10)
    assert pty.pid > 0
    sandbox.pty.resize(pty.pid, PtySize(rows=40, cols=120))
    assert sandbox.pty.kill(pty.pid)

    execution = sandbox.run_code(
        "print('code-interpreter-jwt-ok')",
        request_timeout=120,
    )
    assert execution.error is None
    assert execution.logs.stdout == ["code-interpreter-jwt-ok\n"]

    sandbox.files.write("/tmp/jwt_websocket_server.py", WEBSOCKET_SERVER)
    sandbox.commands.run(
        "python3 /tmp/jwt_websocket_server.py",
        background=True,
    )
    sandbox.commands.run(
        "for i in $(seq 1 100); do "
        "test -f /tmp/jwt-websocket-ready && exit 0; "
        "sleep 0.1; done; exit 1"
    )

    websocket_headers = [
        f"e2b-sandbox-id: {sandbox.sandbox_id}",
        f"e2b-sandbox-port: {WEBSOCKET_PORT}",
    ]
    with pytest.raises(WebSocketBadStatusException) as exc_info:
        create_connection(
            gateway_websocket_url(config),
            header=websocket_headers,
            timeout=10,
            http_proxy_host=None,
        )
    assert exc_info.value.status_code == 403

    websocket = create_connection(
        gateway_websocket_url(config),
        header=[
            *websocket_headers,
            f"{TRAFFIC_ACCESS_TOKEN_HEADER}: {traffic_token}",
        ],
        timeout=10,
        http_proxy_host=None,
    )
    try:
        assert websocket.connected
    finally:
        websocket.close()


@pytest.mark.skip(
    reason=(
        "requires a production-configurable signed JWT issuer in the "
        "open-source sandbox-manager"
    )
)
def test_gateway_traffic_access_token_rotation(sandbox_context, config):
    """Verify automatic refresh keeps SDK traffic working across rotation."""
    validity = int(os.environ.get("JWT_E2E_TOKEN_VALIDITY_SECONDS", "65"))
    sandbox: Sandbox = sandbox_context.add(
        Sandbox.create(
            template=config.templates.code_interpreter,
            timeout=180,
            metadata={JWT_AUTH_METADATA_KEY: "true"},
            headers={"x-request-id": sandbox_context.request_id},
        )
    )
    initial_token = sandbox.traffic_access_token
    runtime_token = get_sandbox_access_token(sandbox.sandbox_id)
    assert initial_token and initial_token.count(".") == 2
    assert runtime_token

    initial = gateway_request_eventually(
        config, sandbox.sandbox_id, runtime_token, initial_token
    )
    assert initial.status_code in (200, 404), initial.text

    deadline = time.monotonic() + max(20, validity / 2)
    while time.monotonic() < deadline:
        probe = sandbox.commands.run("true")
        assert probe.exit_code == 0
        if sandbox.traffic_access_token != initial_token:
            break
        time.sleep(0.5)
    rotated_token = sandbox.traffic_access_token
    assert rotated_token != initial_token, "SDK did not refresh the Traffic JWT"

    result = sandbox.commands.run("echo traffic-token-rotation-ok")
    assert result.exit_code == 0
    assert result.stdout.strip() == "traffic-token-rotation-ok"
    rotated = gateway_request(
        config, sandbox.sandbox_id, runtime_token, rotated_token
    )
    assert rotated.status_code in (200, 404), rotated.text

    sleep_seconds = max(0, token_expiration(initial_token) - time.time() + 2)
    time.sleep(sleep_seconds)
    expired = gateway_request(
        config, sandbox.sandbox_id, runtime_token, initial_token
    )
    assert expired.status_code == 403, expired.text
