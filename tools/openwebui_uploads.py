"""Adapter pour les pièces jointes injectées par Open WebUI."""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Doit correspondre à `container_name:` dans docker-compose.yml (underscore, pas tiret).
# Override possible via OPENWEBUI_CONTAINER dans .env.
DEFAULT_WEBUI_CONTAINER = os.getenv("OPENWEBUI_CONTAINER", "open_webui")


def _copy_from_webui_container(
    container_path: str,
    local_path: Path,
    *,
    webui_container: str,
) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "wb") as out_f:
        result = subprocess.run(
            ["docker", "exec", webui_container, "cat", container_path],
            stdout=out_f,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker exec {webui_container} cat {container_path} failed: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )


def resolve_attached_files(
    text: str,
    *,
    uploads_dir: Path | None = None,
    webui_container: str = DEFAULT_WEBUI_CONTAINER,
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
    image_paths: list[str] = []
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
            content_type = (file_el.get("content_type", "") or "").strip().lower()
            if not file_id or not name:
                continue

            local_path = uploads_root / name
            container_path = f"{webui_uploads_path}/{file_id}_{name}"

            try:
                copier(container_path, local_path)
                resolved_paths.append(str(local_path))
                if content_type.startswith("image/"):
                    image_paths.append(str(local_path))
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
    if image_paths and len(image_paths) == len(resolved_paths):
        instruction = (
            f"Image(s) chargée(s) depuis Open WebUI :\n{paths_str}\n"
            "Analyse l'image directement si le modèle le permet."
        )
    elif image_paths:
        instruction = (
            f"Pièce(s) jointe(s) depuis Open WebUI :\n{paths_str}\n"
            "Charge les fichiers tabulaires avec `load_file`. Les images doivent être analysées directement via le contexte multimodal."
        )
    else:
        instruction = (
            f"Fichier(s) chargé(s) depuis Open WebUI :\n{paths_str}\n"
            "Charge le fichier avec l'outil load_file avant de répondre."
        )
    return f"{cleaned}\n\n{instruction}".strip()


def _image_data_url(local_path: Path, content_type: str) -> str:
    """Encode l'image locale en data URL base64 pour l'API multimodale."""
    mime = content_type or mimetypes.guess_type(str(local_path))[0] or "image/png"
    b64 = base64.b64encode(local_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def resolve_request_files(
    files: list | None,
    *,
    uploads_dir: Path | None = None,
    webui_container: str = DEFAULT_WEBUI_CONTAINER,
    webui_uploads_path: str = "/app/backend/data/uploads",
    copy_from_container: Callable[[str, Path], None] | None = None,
) -> tuple[str, list[dict]]:
    """Résout les fichiers du champ `files` du body OpenWebUI 0.9.x.

    Retourne `(text_instruction, image_parts)` :
      - `text_instruction` : consigne pour les fichiers tabulaires (chemin + `load_file`).
        Vide si seules des images sont uploadées.
      - `image_parts` : liste de blocs `{"type": "image_url", "image_url": {"url": "data:..."}}`
        à concaténer au content multimodal du message utilisateur. Les bytes sont encodés
        en base64 — l'agent n'a pas besoin de relire le disque.
    """
    if not files:
        return "", []

    uploads_root = uploads_dir or Path("/tmp/webui_uploads")
    copier = copy_from_container or (
        lambda container_path, local_path: _copy_from_webui_container(
            container_path, local_path, webui_container=webui_container
        )
    )

    tabular_paths: list[str] = []
    image_parts: list[dict] = []
    image_names: list[str] = []

    for entry in files:
        if not isinstance(entry, dict):
            continue
        file_obj = entry.get("file") or {}
        if not isinstance(file_obj, dict):
            continue

        file_id = file_obj.get("id", "").strip()
        filename = file_obj.get("filename", "").strip()
        meta = file_obj.get("meta") or {}
        content_type = (meta.get("content_type", "") or "").strip().lower()

        if not file_id or not filename:
            continue

        local_path = uploads_root / filename
        container_path = f"{webui_uploads_path}/{file_id}_{filename}"

        try:
            copier(container_path, local_path)
            if content_type.startswith("image/"):
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_url(local_path, content_type)},
                    }
                )
                image_names.append(filename)
            else:
                tabular_paths.append(str(local_path))
            logger.info(
                "request_file_resolved name=%s type=%s → %s",
                filename, content_type or "?", local_path,
            )
        except Exception as exc:
            logger.warning("request_file_resolve_failed name=%s err=%s", filename, exc)

    text_parts: list[str] = []
    if tabular_paths:
        paths_str = "\n".join(f"- {p}" for p in tabular_paths)
        text_parts.append(
            f"Fichier(s) chargé(s) depuis Open WebUI :\n{paths_str}\n"
            "Charge le fichier avec l'outil load_file avant de répondre."
        )
    if image_names:
        names_str = ", ".join(image_names)
        text_parts.append(
            f"Image(s) jointe(s) (déjà visible(s) dans le contexte multimodal) : {names_str}."
        )

    return "\n\n".join(text_parts), image_parts


# ---------------------------------------------------------------------------
# Chat-DB-based file resolution (OpenWebUI 0.9.x — files never in req body)
# ---------------------------------------------------------------------------

_CHAT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Fichiers déjà injectés par thread — évite de répéter load_file à chaque tour.
_injected_by_thread: dict[str, set[str]] = {}


def _get_chat_files_from_db(
    chat_id: str,
    *,
    webui_container: str = DEFAULT_WEBUI_CONTAINER,
    limit: int = 10,
) -> list[dict]:
    """Retourne les fichiers attachés à un chat depuis le SQLite d'OpenWebUI.

    Requiert uniquement le chat_id (dispo dans x-openwebui-chat-id).
    Résultat : [{"id", "filename", "path", "content_type"}, ...]
    """
    if not _CHAT_ID_RE.match(chat_id):
        logger.warning("chat_files_db: chat_id format invalide %s", chat_id[:40])
        return []

    script = (
        "import sqlite3,json,sys;"
        "c=sqlite3.connect('/app/backend/data/webui.db');"
        "rows=list(c.execute("
        "\"SELECT f.id,f.filename,f.path,f.meta FROM chat_file cf "
        "JOIN file f ON cf.file_id=f.id WHERE cf.chat_id=? "
        f"ORDER BY cf.created_at DESC LIMIT {limit}\","
        f"['{chat_id}']));"
        "[(print(json.dumps({'id':r[0],'filename':r[1],'path':r[2],"
        "'content_type':(json.loads(r[3] or '{}').get('content_type',''))}))) for r in rows]"
    )
    result = subprocess.run(
        ["docker", "exec", webui_container, "python3", "-c", script],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        logger.warning("chat_files_db_error: %s", result.stderr.strip()[:200])
        return []

    files = []
    for line in result.stdout.strip().splitlines():
        try:
            files.append(__import__("json").loads(line))
        except Exception:
            pass
    return files


def resolve_chat_files(
    chat_id: str | None,
    thread_id: str | None = None,
    *,
    uploads_dir: Path | None = None,
    webui_container: str = DEFAULT_WEBUI_CONTAINER,
) -> tuple[str, list[dict]]:
    """Résout les fichiers d'un chat OpenWebUI via le SQLite (x-openwebui-chat-id).

    OpenWebUI ne forward pas les fichiers dans le body — cette fonction lit
    directement `chat_file JOIN file` pour obtenir le path container.

    Retourne `(text_instruction, image_parts)`.
    Chaque fichier n'est injecté qu'une fois par thread (évite les doublons).
    """
    if not chat_id:
        return "", []

    db_files = _get_chat_files_from_db(chat_id, webui_container=webui_container)
    if not db_files:
        return "", []

    uploads_root = uploads_dir or Path("/tmp/webui_uploads")
    already_injected = _injected_by_thread.setdefault(thread_id or chat_id, set())

    tabular_paths: list[str] = []
    image_parts: list[dict] = []
    image_names: list[str] = []

    for f in db_files:
        file_id = f["id"]
        if file_id in already_injected:
            continue

        filename = f["filename"]
        container_path = f["path"]
        content_type = (f.get("content_type") or "").lower()
        local_path = uploads_root / filename

        try:
            _copy_from_webui_container(container_path, local_path, webui_container=webui_container)
        except Exception as exc:
            logger.warning("chat_file_copy_failed name=%s err=%s", filename, exc)
            continue

        already_injected.add(file_id)

        if content_type.startswith("image/"):
            try:
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(local_path, content_type)},
                })
                image_names.append(filename)
            except Exception as exc:
                logger.warning("chat_file_image_encode name=%s err=%s", filename, exc)
        else:
            tabular_paths.append(str(local_path))

        logger.info("chat_file_resolved name=%s type=%s → %s", filename, content_type or "?", local_path)

    text_parts: list[str] = []
    if tabular_paths:
        paths_str = "\n".join(f"- {p}" for p in tabular_paths)
        text_parts.append(
            f"Fichier(s) chargé(s) depuis Open WebUI :\n{paths_str}\n"
            "Charge le fichier avec l'outil load_file avant de répondre."
        )
    if image_names:
        text_parts.append(
            f"Image(s) jointe(s) (déjà visible(s) dans le contexte multimodal) : {', '.join(image_names)}."
        )

    return "\n\n".join(text_parts), image_parts
