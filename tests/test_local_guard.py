"""T-18 (AT-8, QS-8): the local API cannot be reached or driven from anywhere but this PC."""

from __future__ import annotations

import http.client
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from cs2scout.settings import Settings
from cs2scout.web.app import create_app

PORT = 8765
TOKEN = "test-token"
GOOD_HOST = f"127.0.0.1:{PORT}"
GOOD_ORIGIN = f"http://{GOOD_HOST}"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(Settings(home=tmp_path, port=PORT), token=TOKEN)

    # Probe routes stand in for future /api endpoints; the guard is what is under test.
    @app.get("/api/probe")
    def probe_get() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/probe")
    def probe_post() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app, base_url=f"http://{GOOD_HOST}")


@pytest.mark.parametrize("host", [GOOD_HOST, f"localhost:{PORT}"])
def test_health_is_served_to_local_hosts(client: TestClient, host: str) -> None:
    response = client.get("/api/health", headers={"host": host})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize(
    "host",
    ["evil.example", f"evil.example:{PORT}", "127.0.0.1:9999", f"192.168.1.5:{PORT}", ""],
)
def test_foreign_host_is_refused(client: TestClient, host: str) -> None:
    # DNS rebinding: a hostile domain resolving to 127.0.0.1 still sends its own Host.
    response = client.get("/api/health", headers={"host": host})
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 403),
        ({"x-cs2scout": "wrong"}, 403),
        ({"x-cs2scout": TOKEN}, 200),
    ],
)
def test_api_requires_session_token(client: TestClient, headers: dict, expected: int) -> None:
    assert client.get("/api/probe", headers=headers).status_code == expected


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (None, 403),
        ("http://evil.example", 403),
        (f"http://127.0.0.1:{PORT + 1}", 403),
        ("null", 403),
        (GOOD_ORIGIN, 200),
        (f"http://localhost:{PORT}", 200),
    ],
)
def test_state_change_requires_same_origin(
    client: TestClient, origin: str | None, expected: int
) -> None:
    headers = {"x-cs2scout": TOKEN}
    if origin is not None:
        headers["origin"] = origin
    assert client.post("/api/probe", headers=headers).status_code == expected


def test_no_unauthenticated_schema_or_docs(client: TestClient) -> None:
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, host_header: str) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("GET", "/api/health", headers={"Host": host_header})
        return conn.getresponse().status
    finally:
        conn.close()


def test_real_server_listens_on_loopback_only(tmp_path: Path) -> None:
    port = _free_port()
    env = {**os.environ, "CS2SCOUT_HOME": str(tmp_path / "ws"), "CS2SCOUT_PORT": str(port)}
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, test-owned process
        [sys.executable, "-m", "cs2scout", "serve", "--no-browser"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                status = _get(port, f"127.0.0.1:{port}")
                break
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    pytest.fail(f"server did not start (exit code {proc.poll()})")
                time.sleep(0.2)
        assert status == 200

        # The venv launcher on Windows may run the interpreter as a child process.
        server = psutil.Process(proc.pid)
        listening = [
            conn.laddr
            for p in [server, *server.children(recursive=True)]
            for conn in p.net_connections(kind="inet")
            if conn.status == psutil.CONN_LISTEN
        ]
        assert listening, "no listening socket found"
        assert {addr.ip for addr in listening} == {"127.0.0.1"}
        assert {addr.port for addr in listening} == {port}

        assert _get(port, f"evil.example:{port}") == 403
        assert (tmp_path / "ws" / "extracts").is_dir()
    finally:
        for p in psutil.Process(proc.pid).children(recursive=True):
            p.kill()
        proc.kill()
        proc.wait(timeout=10)
