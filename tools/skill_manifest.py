"""Validated, budgeted skill documents used by the runtime loader."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml


_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_MAX_ALLOWED_SKILL_TOKENS = 12_000


class SkillManifestError(ValueError):
    """Raised when a skill is not a valid, reviewable runtime document."""


class SkillManifest(BaseModel):
    """Executable metadata contract shared by every local skill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    version: str
    triggers: tuple[str, ...] = Field(min_length=1)
    forbidden_when: tuple[str, ...] = Field(min_length=1)
    requires: tuple[str, ...]
    next_tool: str | None
    max_tokens: int = Field(gt=0, le=_MAX_ALLOWED_SKILL_TOKENS)
    description: str | None = None
    size_exemption: str | None = None

    @field_validator("version")
    @classmethod
    def _valid_semver(cls, value: str) -> str:
        if not _SEMVER.fullmatch(value):
            raise ValueError("version must use semantic versioning")
        return value

    @field_validator("triggers", "forbidden_when", "requires")
    @classmethod
    def _non_blank_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in values):
            raise ValueError("manifest list items must not be blank")
        return values

    @field_validator("size_exemption")
    @classmethod
    def _non_blank_exemption(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("size_exemption must not be blank")
        return value


@dataclass(frozen=True)
class SkillDocument:
    """A validated manifest, its model-facing body, and immutable identity."""

    manifest: SkillManifest
    content: str
    sha256: str
    estimated_tokens: int
    path: Path | None = None


def estimate_skill_tokens(content: str) -> int:
    """Match the runtime's deterministic approximate-token accounting."""

    return max(1, len(content) // 4)


def parse_skill_document(raw: str, *, expected_name: str, path: Path | None = None) -> SkillDocument:
    """Parse and validate one complete Markdown skill document."""

    if not raw.startswith("---\n"):
        raise SkillManifestError(f"{expected_name}: missing YAML frontmatter")
    try:
        header, body = raw[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise SkillManifestError(f"{expected_name}: unterminated YAML frontmatter") from exc

    try:
        payload: Any = yaml.safe_load(header)
        manifest = SkillManifest.model_validate(payload)
    except Exception as exc:
        raise SkillManifestError(f"{expected_name}: invalid skill manifest: {exc}") from exc

    if manifest.name != expected_name:
        raise SkillManifestError(
            f"{expected_name}: manifest name is {manifest.name!r}"
        )

    content = body.lstrip("\n")
    estimated_tokens = estimate_skill_tokens(content)
    if estimated_tokens > manifest.max_tokens:
        raise SkillManifestError(
            f"{expected_name}: body is ~{estimated_tokens} tokens, "
            f"above max_tokens={manifest.max_tokens}"
        )
    if estimated_tokens > 3_000 and not manifest.size_exemption:
        raise SkillManifestError(
            f"{expected_name}: skills above 3000 tokens require size_exemption"
        )

    return SkillDocument(
        manifest=manifest,
        content=content,
        sha256=sha256(raw.encode("utf-8")).hexdigest(),
        estimated_tokens=estimated_tokens,
        path=path,
    )


def load_skill_document(path: Path) -> SkillDocument:
    """Load a local skill and validate its filename-bound manifest."""

    return parse_skill_document(
        path.read_text(encoding="utf-8"),
        expected_name=path.stem,
        path=path,
    )
