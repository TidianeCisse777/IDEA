"""Shared EcoPart helpers — cookie-session client."""
from __future__ import annotations

import io
import os
import re
import zipfile

import pandas as pd
import requests
from bs4 import BeautifulSoup
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
        hrefs = [a.get("href", "") for a in soup.find_all("a")]
        regex_hrefs = re.findall(r"""(?:href|url|window\.location)\s*[:=]\s*['"]([^'"]+)""", resp.text)
        all_links = list(dict.fromkeys(hrefs + regex_hrefs))
        keywords = {"download", "file", "task", "zip", "csv", "tsv", "export"}
        return [lnk for lnk in all_links if lnk and any(k in lnk.lower() for k in keywords)]

    def download_tsv(self, links: list[str]) -> pd.DataFrame:
        if not links:
            raise RuntimeError("No download links provided")
        for link in links:
            url = link if link.startswith("http") else f"{_BASE_URL}{link}"
            resp = self._session.get(url, timeout=_TIMEOUT)
            if not resp.ok:
                continue
            ctype = resp.headers.get("content-type", "").lower()
            if resp.content[:4] == b"PK\x03\x04" or "zip" in ctype:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    name = next(
                        (n for n in zf.namelist() if n.endswith((".tsv", ".csv"))),
                        zf.namelist()[0],
                    )
                    with zf.open(name) as f:
                        sep = "\t" if name.endswith(".tsv") else ","
                        return pd.read_csv(f, sep=sep, low_memory=False)
            if "tab" in ctype or "tsv" in ctype or "csv" in ctype or "text" in ctype:
                sep = "\t" if "tab" in ctype or "tsv" in ctype else ","
                return pd.read_csv(io.BytesIO(resp.content), sep=sep, low_memory=False)
        raise RuntimeError("No downloadable file found in provided links")

    def get_stats(self, project_id: int) -> dict:
        resp = self._session.get(
            f"{_BASE_URL}/statsample",
            params={"filt_uproj": str(project_id)},
            timeout=_TIMEOUT,
        )
        return {"accessible": resp.ok}
