#!/usr/bin/env python3
"""Patch Open WebUI so uploaded files are stored without RAG processing."""

from __future__ import annotations

import sys
from pathlib import Path


MARKER = "NeoLab disables Open WebUI RAG processing for every file upload."
BACKEND_MARKER = "NeoLab server policy: store uploads without RAG processing."
NEEDLE = """\tif (metadata) {
\t\tdata.append('metadata', JSON.stringify(metadata));
\t}
"""
REPLACEMENT = f"""{NEEDLE}
\t// {MARKER}
\t// IDEA reads the stored original through its own sandbox and tools.
\tprocess = false;
\tstream = false;
"""


def patch_upload_api(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return
    if source.count(NEEDLE) != 1:
        raise RuntimeError(
            f"Expected exactly one upload insertion point in {path}; "
            "review the Open WebUI upgrade before rebuilding"
        )
    path.write_text(source.replace(NEEDLE, REPLACEMENT), encoding="utf-8")


def patch_upload_backend(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if BACKEND_MARKER in source:
        return
    needle = "    log.info('file.content_type: %s %s', file.content_type, process)\n"
    replacement = (
        f"    # {BACKEND_MARKER}\n"
        "    process = False\n"
        "    process_in_background = False\n"
        + needle
    )
    if source.count(needle) != 1:
        raise RuntimeError(
            f"Expected exactly one upload handler insertion point in {path}; "
            "review the Open WebUI upgrade before rebuilding"
        )
    path.write_text(source.replace(needle, replacement), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"frontend", "backend"}:
        raise SystemExit(
            "usage: disable_rag_uploads.py {frontend|backend} PATH"
        )
    patcher = patch_upload_api if sys.argv[1] == "frontend" else patch_upload_backend
    patcher(Path(sys.argv[2]))
