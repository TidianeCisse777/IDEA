"""Helpers for public-facing URLs used in tool outputs."""
from __future__ import annotations

import os


def serve_base_url() -> str:
    """Return the public base URL for the local serve.py API."""
    return (os.getenv("SERVE_BASE_URL") or "http://localhost:8000").rstrip("/")


def download_url(filename: str) -> str:
    """Return the public download URL for a generated file."""
    return f"{serve_base_url()}/downloads/{filename.lstrip('/')}"


def graph_url(filename: str) -> str:
    """Return the public graph URL for a generated image."""
    return f"{serve_base_url()}/graphs/{filename.lstrip('/')}"
