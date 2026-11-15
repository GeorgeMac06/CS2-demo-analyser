"""Drive the real app through its HTTP API (the boundary the tests protect)."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

from fastapi.testclient import TestClient

from cs2scout.settings import Settings
from cs2scout.web.app import create_app

PORT = 8765
TOKEN = "test-token"
HOST = f"127.0.0.1:{PORT}"
SYNTH = "support.synth:SynthAdapter"


class Api:
    def __init__(self, client: TestClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.headers = {"x-cs2scout": TOKEN, "origin": f"http://{HOST}"}

    @property
    def library(self):
        return self.client.app.state.library

    def get(self, path: str, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path: str, json: dict | None = None, **kw):
        return self.client.post(path, json=json, headers=self.headers, **kw)

    def put(self, path: str, json: dict | None = None, **kw):
        return self.client.put(path, json=json, headers=self.headers, **kw)

    def patch(self, path: str, json: dict | None = None, **kw):
        return self.client.patch(path, json=json, headers=self.headers, **kw)

    def delete(self, path: str, **kw):
        return self.client.delete(path, headers=self.headers, **kw)

    def wait(self, job_id: str, timeout: float = 120) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            job = self.get(f"/api/jobs/{job_id}").json()
            if job["state"] in ("done", "failed", "cancelled"):
                return job
            if time.monotonic() > deadline:
                raise TimeoutError(f"job {job_id} still {job['state']}: {job.get('progress')}")
            time.sleep(0.1)

    def run_import(self, paths: list[Path | str], entry_id: int | None = None,
                   timeout: float = 120) -> dict:  # fmt: skip
        body = {"paths": [str(p) for p in paths], "entry_id": entry_id}
        response = self.post("/api/imports", body)
        assert response.status_code == 202, response.text
        return self.wait(response.json()["job_id"], timeout=timeout)

    def confirm(self, import_job: dict, team_name: str = "Scouted", timeout: float = 120,
                **body) -> int:  # fmt: skip
        """J1 step 5: accept the proposed roster (or the given one) and compute the entry."""
        proposal = import_job["result"]["roster_proposal"]
        core = body.pop("core", [p["steamid"] for p in proposal["players"] if p["role"] == "core"])
        standins = body.pop("standins", [p["steamid"] for p in proposal["players"]
                                         if p["role"] == "standin"])  # fmt: skip
        response = self.post("/api/entries", {"import_job_id": import_job["job_id"],
                                              "team_name": team_name, "core": core,
                                              "standins": standins, **body})  # fmt: skip
        assert response.status_code == 202, response.text
        job = self.wait(response.json()["job_id"], timeout=timeout)
        assert job["state"] == "done", job
        return response.json()["entry_id"]

    def findings(self, entry_id: int, **params) -> dict:
        response = self.get(f"/api/entries/{entry_id}/findings", params=params)
        assert response.status_code == 200, response.text
        return response.json()


def finding(snapshot: dict, fid: str) -> dict:
    return next(f for f in snapshot["findings"] if f["id"] == fid)


def make_api(home: Path, **overrides) -> tuple[TestClient, Settings]:
    settings = dataclasses.replace(Settings(home=home, port=PORT, adapter=SYNTH), **overrides)
    app = create_app(settings, token=TOKEN)
    return TestClient(app, base_url=f"http://{HOST}"), settings
