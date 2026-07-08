"""Shared EcoPart helpers — cookie-session client."""
from __future__ import annotations

import io
import os
import re
import time
import zipfile
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://ecopart.obs-vlfr.fr"
_TIMEOUT = 60
_EXPORT_POLL_ATTEMPTS = 60
_EXPORT_POLL_INTERVAL = 2


class EcopartExportError(RuntimeError):
    """Raised when the EcoPart export task fails server-side.

    Attributes:
        kind: short tag — "empty_sample_set", "db_error", "no_rights", "unknown".
        message: short user-facing reason in French.
        task_id: EcoPart task id when available.
        raw: full server error text (kept for debugging).
    """

    def __init__(self, kind: str, message: str, task_id: int | None = None, raw: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.task_id = task_id
        self.raw = raw


def _parse_ecopart_task_error(page_text: str) -> tuple[str, str, int | None]:
    """Classify an EcoPart task error page; return (kind, short_message, task_id)."""
    task_id = None
    m = re.search(r"Task ID\s+(\d+)", page_text)
    if m:
        task_id = int(m.group(1))

    if re.search(r"psampleid\s+in\s*\(\s*\)", page_text, re.IGNORECASE):
        return (
            "empty_sample_set",
            "Le serveur EcoPart a refusé l'export : aucun sample exportable pour ce projet "
            "(typiquement un projet récent dont les particules ne sont pas encore validées, "
            "statut « VN »). Réessaie sur un projet validé ou attends la validation.",
            task_id,
        )
    if "psycopg2" in page_text or "SyntaxError" in page_text:
        return (
            "db_error",
            "Le serveur EcoPart a rencontré une erreur interne (SQL) lors de l'export. "
            "Réessaie plus tard ou tente un autre projet.",
            task_id,
        )
    if re.search(r"not\s+visible|no\s+rights|permission", page_text, re.IGNORECASE):
        return (
            "no_rights",
            "Le projet EcoPart est inaccessible avec ce compte — droits insuffisants.",
            task_id,
        )
    short = re.sub(r"\s+", " ", page_text).strip()[:200]
    return ("unknown", f"L'export EcoPart a échoué côté serveur : {short}", task_id)


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

    def search_samples(
        self, project_id: int | None = None, ecotaxa_project_id: int | None = None
    ) -> list[dict]:
        """Search accessible EcoPart samples.

        `project_id` restricts to one EcoPart project (`filt_uproj`).
        `ecotaxa_project_id` restricts to the EcoPart samples linked to an EcoTaxa
        project (`filt_proj`) — the server-authoritative EcoTaxa↔EcoPart link, the
        same one `start_export` uses.
        """
        params = {}
        if project_id is not None:
            params["filt_uproj"] = str(project_id)
        if ecotaxa_project_id is not None:
            params["filt_proj"] = str(ecotaxa_project_id)
        resp = self._session.get(f"{_BASE_URL}/searchsample", params=params or None, timeout=_TIMEOUT)
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

    def preview_sample(self, sample_id: int) -> dict:
        resp = self._session.get(f"{_BASE_URL}/getsamplepopover/{sample_id}", timeout=_TIMEOUT)
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True) if resp.ok else ""
        return {"sample_id": sample_id, "accessible": resp.ok, "text": text}

    def search_samples_by_bbox(
        self, north: float, south: float, west: float, east: float
    ) -> list[dict]:
        """Return EcoPart samples whose coordinates fall in the bbox (degrees)."""
        resp = self._session.get(
            f"{_BASE_URL}/searchsample",
            params={
                "MapN": str(north),
                "MapS": str(south),
                "MapW": str(west),
                "MapE": str(east),
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return [
            {
                "id": int(s["id"]),
                "lat": float(s.get("lat", 0)),
                "lon": float(s.get("long", 0)),
                "visibility": str(s.get("visibility") or ""),
            }
            for s in (resp.json() or [])
            if "id" in s
        ]

    def get_sample_metadata(self, psampleid: int) -> dict:
        """Parse /getsamplepopover/<id> for the EcoPart and EcoTaxa project ids."""
        resp = self._session.get(f"{_BASE_URL}/getsamplepopover/{psampleid}", timeout=_TIMEOUT)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)
        out: dict = {"psampleid": psampleid, "raw": text}
        m = re.search(r"Profile ID\s*:\s*([^\s]+)", text)
        if m:
            out["profile_id"] = m.group(1)
        m = re.search(r"Project\s*:\s*(.+?)\((\d+)\)", text)
        if m:
            out["ecopart_project_name"] = m.group(1).strip()
            out["ecopart_project_id"] = int(m.group(2))
        m = re.search(r"Ecotaxa Project\s*:\s*[^()]*\((\d+)\)", text)
        if m:
            out["ecotaxa_project_id"] = int(m.group(1))
        return out

    def start_export(
        self,
        project_id: int | None = None,
        ctd_vars: list[str] | None = None,
        gpr_vars: list[str] | None = None,
        ecotaxa_project_id: int | None = None,
    ) -> list[str]:
        if project_id is None and ecotaxa_project_id is None:
            raise ValueError("EcoPart export requires either project_id (EcoPart) or ecotaxa_project_id")
        if ctd_vars is None:
            ctd_vars = ["depth", "datetime", "temperature", "practical_salinity"]
        if gpr_vars is None:
            gpr_vars = ["cl6", "cl7", "cl8", "bv6", "bv7", "bv8"]

        params: list[tuple[str, str]] = []
        if project_id is not None:
            params.append(("filt_uproj", str(project_id)))
        if ecotaxa_project_id is not None:
            params.append(("filt_proj", str(ecotaxa_project_id)))
        params += [("ctd", v) for v in ctd_vars]
        params += [("gpr", v) for v in gpr_vars]

        resp = self._session.get(
            f"{_BASE_URL}/Task/Create/TaskPartExport",
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        backurl_input = soup.find("input", {"name": "backurl"})
        backurl_default = "/?" + "&".join(f"{k}={v}" for k, v in params if k in {"filt_uproj", "filt_proj"})
        backurl = backurl_input.get("value", backurl_default) if backurl_input else backurl_default

        task_resp = self._session.post(
            f"{_BASE_URL}/Task/Create/TaskPartExport",
            params=params,
            data={
                "backurl": backurl,
                "what": "RED",
                "fileformat": "TSV",
                "starttask": "Y",
            },
            timeout=_TIMEOUT,
        )
        task_resp.raise_for_status()
        task_links = re.findall(r"""href=['"](/Task/Show/(\d+))['"]""", task_resp.text)
        if not task_links:
            task_list_resp = self._session.get(f"{_BASE_URL}/Task/listall", timeout=_TIMEOUT)
            task_list_resp.raise_for_status()
            task_links = re.findall(r"""href=['"](/Task/Show/(\d+))['"]""", task_list_resp.text)
        if not task_links:
            raise RuntimeError("EcoPart export task was not created")
        newest_task = max(task_links, key=lambda item: int(item[1]))
        return [newest_task[0]]

    def download_tsv(self, links: list[str]) -> pd.DataFrame:
        if not links:
            raise RuntimeError("No download links provided")
        for link in links:
            if "/Task/Show/" in link:
                link = self._wait_for_export(link)
            url = urljoin(f"{_BASE_URL}/", link)
            resp = self._session.get(url, timeout=_TIMEOUT)
            if not resp.ok:
                continue
            ctype = resp.headers.get("content-type", "").lower()
            if "html" in ctype or resp.content.lstrip().lower().startswith(b"<!doctype html"):
                raise RuntimeError(f"EcoPart returned HTML instead of an export file: {url}")
            if resp.content[:4] == b"PK\x03\x04" or "zip" in ctype:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    names = [
                        name
                        for name in zf.namelist()
                        if name.lower().endswith((".tsv", ".csv")) and "summary" not in name.lower()
                    ]
                    if not names:
                        raise RuntimeError("EcoPart ZIP contains no tabular export file")
                    frames = [self._read_delimited(zf.read(name)) for name in names]
                    return pd.concat(frames, ignore_index=True, sort=False)
            if "tab" in ctype or "tsv" in ctype or "csv" in ctype or "text" in ctype:
                return self._read_delimited(resp.content)
        raise RuntimeError("No downloadable file found in provided links")

    def _wait_for_export(self, task_link: str) -> str:
        task_url = urljoin(f"{_BASE_URL}/", task_link)
        for attempt in range(_EXPORT_POLL_ATTEMPTS):
            resp = self._session.get(task_url, timeout=_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            file_link = next(
                (
                    anchor.get("href")
                    for anchor in soup.find_all("a")
                    if anchor.get("href") and "/Task/GetFile/" in anchor.get("href")
                ),
                None,
            )
            if file_link:
                return file_link
            page_text = soup.get_text(" ", strip=True)
            if re.search(r"\bState\s+Error\b", page_text, re.IGNORECASE):
                kind, message, task_id = _parse_ecopart_task_error(page_text)
                raise EcopartExportError(kind, message, task_id=task_id, raw=page_text)
            if attempt < _EXPORT_POLL_ATTEMPTS - 1:
                time.sleep(_EXPORT_POLL_INTERVAL)
        raise EcopartExportError(
            "timeout",
            "L'export EcoPart n'a pas produit de fichier dans le temps imparti — réessaie plus tard.",
        )

    @staticmethod
    def _read_delimited(content: bytes) -> pd.DataFrame:
        first_line = next((line for line in content.splitlines() if line.strip()), b"")
        separator = b"\t" if first_line.count(b"\t") > first_line.count(b",") else b","
        if separator not in first_line:
            raise RuntimeError("EcoPart export is not a recognized TSV or CSV file")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        return pd.read_csv(io.StringIO(text), sep=separator.decode(), low_memory=False)

    def get_stats(self, project_id: int) -> dict:
        resp = self._session.get(
            f"{_BASE_URL}/statsample",
            params={"filt_uproj": str(project_id)},
            timeout=_TIMEOUT,
        )
        return {"accessible": resp.ok}
