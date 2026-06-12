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

    def preview_sample(self, sample_id: int) -> dict:
        resp = self._session.get(f"{_BASE_URL}/getsamplepopover/{sample_id}", timeout=_TIMEOUT)
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True) if resp.ok else ""
        return {"sample_id": sample_id, "accessible": resp.ok, "text": text}

    def start_export(
        self,
        project_id: int,
        ctd_vars: list[str] | None = None,
        gpr_vars: list[str] | None = None,
    ) -> list[str]:
        if ctd_vars is None:
            ctd_vars = ["depth", "datetime", "temperature", "practical_salinity"]
        if gpr_vars is None:
            gpr_vars = ["cl6", "cl7", "cl8", "bv6", "bv7", "bv8"]

        params: list[tuple[str, str]] = [("filt_uproj", str(project_id))]
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
        backurl = backurl_input.get("value", f"/?filt_uproj={project_id}") if backurl_input else f"/?filt_uproj={project_id}"

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
                raise RuntimeError(f"EcoPart export task failed: {page_text}")
            if attempt < _EXPORT_POLL_ATTEMPTS - 1:
                time.sleep(_EXPORT_POLL_INTERVAL)
        raise RuntimeError("EcoPart export task timed out before producing a file")

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
