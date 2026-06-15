"""Structured business errors raised by the EcoTaxa browser core.

Infrastructure failures (timeouts, 5xx, network) stay as plain exceptions
from the underlying HTTP client. Business errors that an LLM caller can
recover from (ambiguous column, missing taxon, unsupported endpoint) are
exposed as ``EcoTaxaBrowserError`` with a stable ``code`` and optional
``candidates`` list so the agent can rephrase the call.
"""

from __future__ import annotations


class EcoTaxaBrowserError(Exception):
    """Recoverable business error from the EcoTaxa browser core."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        candidates: list | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.candidates = candidates or []

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": str(self),
            "candidates": self.candidates,
        }
