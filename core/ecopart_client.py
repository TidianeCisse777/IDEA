"""Shared EcoPart helpers — cookie-session client."""
from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://ecopart.obs-vlfr.fr"
_TIMEOUT = 60


class EcopartClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "idea-ecopart-client/1.0"})

    def login(self) -> None:
        token = os.getenv("ECOPART_TOKEN")
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
            return
        username = os.getenv("ECOTAXA_USERNAME")
        password = os.getenv("ECOTAXA_PASSWORD")
        if not username or not password:
            raise RuntimeError("EcoPart credentials missing — set ECOPART_TOKEN or ECOTAXA_USERNAME+ECOTAXA_PASSWORD")
        resp = self._session.post(
            f"{_BASE_URL}/login",
            data={"email": username, "password": password},
            timeout=_TIMEOUT,
            allow_redirects=False,
        )
        if resp.status_code not in {200, 302} or not (resp.cookies or resp.headers.get("set-cookie")):
            raise RuntimeError(f"EcoPart login failed — HTTP {resp.status_code}")

    def list_samples(self, project_id: int) -> list[dict]:
        resp = self._session.get(
            f"{_BASE_URL}/searchsample",
            params={"filt_uproj": str(project_id)},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json() or []
        return [
            {
                "id": int(s["id"]),
                "name": str(s.get("name") or s.get("samplename") or ""),
                "visibility": str(s.get("visibility") or ""),
            }
            for s in raw
            if "id" in s
        ]

    def get_stats(self, project_id: int) -> dict:
        resp = self._session.get(
            f"{_BASE_URL}/statsample",
            params={"filt_uproj": str(project_id)},
            timeout=_TIMEOUT,
        )
        return {"accessible": resp.ok}
