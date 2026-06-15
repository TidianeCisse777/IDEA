"""tools/ecotaxa_client.py — Client HTTP EcoTaxa REST API."""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import requests
from dotenv import load_dotenv

if TYPE_CHECKING:
    import pandas as pd

load_dotenv()

_BASE_URL = "https://ecotaxa.obs-vlfr.fr/api"
_TIMEOUT = 60


class EcotaxaClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json, text/tab-separated-values, application/zip, */*"})

    def login(self) -> None:
        token = os.getenv("ECOTAXA_TOKEN")
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
            return
        username = os.getenv("ECOTAXA_USERNAME")
        password = os.getenv("ECOTAXA_PASSWORD")
        if not username or not password:
            raise RuntimeError("EcoTaxa credentials missing — set ECOTAXA_TOKEN or ECOTAXA_USERNAME+ECOTAXA_PASSWORD")
        resp = self._session.post(f"{_BASE_URL}/login", json={"username": username, "password": password}, timeout=_TIMEOUT)
        resp.raise_for_status()
        jwt = resp.json()
        self._session.headers["Authorization"] = f"Bearer {jwt}"

    def list_projects(self) -> list[dict[str, int | str]]:
        resp = self._session.get(
            f"{_BASE_URL}/projects/search",
            params={"title_filter": "", "instrument_filter": ""},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return [
            {"project_id": int(project["projid"]), "name": str(project["title"])}
            for project in resp.json()
        ]

    def search_projects(
        self,
        title: str | None = None,
        instrument: str | None = None,
        window_start: int = 0,
        window_size: int = 50,
    ) -> list[dict]:
        resp = self._session.get(
            f"{_BASE_URL}/projects/search",
            params={
                "title_filter": title or "",
                "instrument_filter": instrument or "",
                "window_start": window_start,
                "window_size": window_size,
                "order_field": "projid",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def preview_project(self, project_id: int, limit: int = 10) -> dict:
        metadata_response = self._session.get(
            f"{_BASE_URL}/projects/{project_id}",
            timeout=_TIMEOUT,
        )
        metadata_response.raise_for_status()
        raw_metadata = metadata_response.json()

        summary_response = self._session.post(
            f"{_BASE_URL}/object_set/{project_id}/summary",
            params={"only_total": False},
            json={},
            timeout=_TIMEOUT,
        )
        summary_response.raise_for_status()

        query_response = self._session.post(
            f"{_BASE_URL}/object_set/{project_id}/query",
            params={
                "fields": "obj.orig_id,obj.objdate,obj.depth_min,txo.display_name",
                "order_field": "obj.objid",
                "window_start": 0,
                "window_size": limit,
            },
            json={},
            timeout=_TIMEOUT,
        )
        query_response.raise_for_status()
        raw_query = query_response.json()

        objects = [
            {
                "orig_id": row[0],
                "date": row[1],
                "depth_min": row[2],
                "taxon": row[3],
            }
            for row in raw_query.get("details", [])
        ]
        return {
            "metadata": {
                "project_id": int(raw_metadata["projid"]),
                "name": str(raw_metadata["title"]),
                "instrument": raw_metadata.get("instrument"),
                "status": raw_metadata.get("status"),
                "access": raw_metadata.get("highest_right"),
                "object_count": raw_metadata.get("objcount"),
                "percent_validated": raw_metadata.get("pctvalidated"),
                "percent_classified": raw_metadata.get("pctclassified"),
            },
            "summary": summary_response.json(),
            "objects": objects,
        }

    def start_export(self, project_id: int, filters: dict) -> int:
        payload = {
            "filters": filters,
            "request": {
                "project_id": project_id,
                "split_by": "none",
                "with_images": "none",
                "with_internal_ids": True,
                "with_types_row": False,
                "only_annotations": False,
                "out_to_ftp": False,
            },
        }
        resp = self._session.post(f"{_BASE_URL}/object_set/export/general", json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["job_id"]

    def wait_for_job(self, job_id: int, poll_seconds: int = 5, max_polls: int = 60) -> dict:
        for _ in range(max_polls):
            try:
                resp = self._session.get(f"{_BASE_URL}/jobs/{job_id}/", timeout=_TIMEOUT)
            except requests.ConnectionError:
                time.sleep(poll_seconds)
                continue
            resp.raise_for_status()
            job = resp.json()
            state = job.get("state")
            if state == "F":
                return job
            if state in {"E", "A"}:
                raise RuntimeError(f"EcoTaxa job {job_id} failed with state={state}")
            time.sleep(poll_seconds)
        raise RuntimeError(f"EcoTaxa job {job_id} did not finish after {max_polls} polls")

    def download_tsv(self, job_id: int) -> "pd.DataFrame":
        import pandas as pd

        resp = self._session.get(f"{_BASE_URL}/jobs/{job_id}/file", timeout=_TIMEOUT)
        resp.raise_for_status()
        import io, zipfile
        if resp.content[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                tsv_name = next(n for n in z.namelist() if n.endswith(".tsv") or n.endswith(".csv"))
                with z.open(tsv_name) as f:
                    return pd.read_csv(f, sep="\t", low_memory=False)
        return pd.read_csv(io.BytesIO(resp.content), sep="\t", low_memory=False)
