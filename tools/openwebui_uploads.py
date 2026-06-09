"""Adapter pour les pièces jointes injectées par Open WebUI."""
from __future__ import annotations

import logging
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


def _copy_from_webui_container(
    container_path: str,
    local_path: Path,
    *,
    webui_container: str,
) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "wb") as out_f:
        subprocess.run(
            ["docker", "exec", webui_container, "cat", container_path],
            stdout=out_f,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=10,
        )


def resolve_attached_files(
    text: str,
    *,
    uploads_dir: Path | None = None,
    webui_container: str = "open-webui",
    webui_uploads_path: str = "/app/backend/data/uploads",
    copy_from_container: Callable[[str, Path], None] | None = None,
) -> str:
    """Remplace le bloc `<attached_files>` Open WebUI par une consigne `load_file`.

    Le texte retourné reste compatible avec l'agent: il contient les chemins
    locaux disponibles pour `load_file`, sans exposer le XML brut.
    """
    uploads_root = uploads_dir or Path("/tmp/webui_uploads")
    pattern = r"<attached_files>.*?</attached_files>"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text

    xml_block = match.group(0)
    resolved_paths: list[str] = []
    copier = copy_from_container or (
        lambda container_path, local_path: _copy_from_webui_container(
            container_path,
            local_path,
            webui_container=webui_container,
        )
    )

    try:
        root = ET.fromstring(xml_block)
        for file_el in root.findall("file"):
            file_id = file_el.get("url", "").strip()
            name = file_el.get("name", "").strip()
            if not file_id or not name:
                continue

            local_path = uploads_root / name
            container_path = f"{webui_uploads_path}/{file_id}_{name}"

            try:
                copier(container_path, local_path)
                resolved_paths.append(str(local_path))
                logger.info("file_resolved name=%s → %s", name, local_path)
            except Exception as exc:
                logger.warning(
                    "file_resolve_failed name=%s container=%s err=%s",
                    name,
                    container_path,
                    exc,
                )

    except ET.ParseError as exc:
        logger.warning("attached_files_parse_error: %s", exc)

    cleaned = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    if not resolved_paths:
        return cleaned

    paths_str = "\n".join(f"- {p}" for p in resolved_paths)
    instruction = (
        f"Fichier(s) chargé(s) depuis Open WebUI :\n{paths_str}\n"
        "Charge le fichier avec l'outil load_file avant de répondre."
    )
    return f"{cleaned}\n\n{instruction}".strip()
