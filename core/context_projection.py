"""Structured, budgeted projection of transient model context.

The checkpoint and session store remain the sources of truth.  This module
owns the smaller provider-facing view for one model call: named blocks, their
priority, deterministic degradation, and an auditable token ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class ContextBlock:
    """One independently budgetable piece of transient context."""

    name: str
    text: str
    priority: int
    required: bool = False


@dataclass(frozen=True)
class ProjectedBlock:
    """Final representation and accounting for one context block."""

    name: str
    text: str
    priority: int
    required: bool
    original_tokens: int
    projected_tokens: int
    status: str


@dataclass(frozen=True)
class ContextProjection:
    """Provider-facing context plus a structured token ledger."""

    text: str
    blocks: tuple[ProjectedBlock, ...]
    max_tokens: int
    original_tokens: int
    projected_tokens: int

    @property
    def ledger(self) -> list[dict[str, object]]:
        return [
            {
                "name": block.name,
                "priority": block.priority,
                "required": block.required,
                "original_tokens": block.original_tokens,
                "projected_tokens": block.projected_tokens,
                "status": block.status,
                "chars": len(block.text),
            }
            for block in self.blocks
        ]


def _truncate_to_tokens(text: str, max_tokens: int, count_tokens: TokenCounter) -> str:
    """Return the longest character prefix fitting the approximate token cap."""

    if not text or max_tokens <= 0:
        return ""
    if count_tokens(text) <= max_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = text[:middle].rstrip()
        if count_tokens(candidate) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    fitted = text[:low].rstrip()
    if not fitted:
        return ""
    marker = "\n[…context truncated by global budget]"
    marked = fitted
    while marked and count_tokens(marked + marker) > max_tokens:
        marked = marked[:-1].rstrip()
    return marked + marker if marked else fitted


def project_context_blocks(
    blocks: Iterable[ContextBlock],
    *,
    max_tokens: int,
    count_tokens: TokenCounter,
) -> ContextProjection:
    """Fit named blocks into one budget, preserving order and high priority.

    Optional blocks are removed from lowest to highest priority.  If required
    blocks still exceed the cap, their contents are truncated proportionally
    while retaining at least their leading facts whenever possible.
    """

    source = tuple(block for block in blocks if block.text.strip())
    cap = max(0, int(max_tokens))
    original = {block.name: count_tokens(block.text) for block in source}
    projected = {block.name: block.text.strip() for block in source}

    def rendered_text() -> str:
        return "\n\n".join(
            projected[block.name]
            for block in source
            if projected.get(block.name)
        )

    for block in sorted(
        (item for item in source if not item.required),
        key=lambda item: (item.priority, item.name),
    ):
        if count_tokens(rendered_text()) <= cap:
            break
        projected[block.name] = ""

    if count_tokens(rendered_text()) > cap:
        required = [item for item in source if projected.get(item.name)]
        remaining = cap
        for index, block in enumerate(required):
            later = required[index + 1 :]
            minimum_for_later = sum(min(24, original[item.name]) for item in later)
            allowance = max(0, remaining - minimum_for_later)
            fitted = _truncate_to_tokens(
                projected[block.name], allowance, count_tokens
            )
            projected[block.name] = fitted
            remaining = max(0, remaining - count_tokens(fitted))

    final_text = rendered_text()
    # Separators can add a handful of tokens. Tighten the least important
    # surviving block until the assembled projection itself fits.
    while final_text and count_tokens(final_text) > cap:
        survivor = min(
            (item for item in source if projected.get(item.name)),
            key=lambda item: (item.required, item.priority, item.name),
        )
        current_tokens = count_tokens(projected[survivor.name])
        projected[survivor.name] = _truncate_to_tokens(
            projected[survivor.name], current_tokens - 1, count_tokens
        )
        final_text = rendered_text()

    results: list[ProjectedBlock] = []
    for block in source:
        text = projected.get(block.name, "")
        tokens = count_tokens(text) if text else 0
        status = (
            "kept"
            if text == block.text.strip()
            else "truncated"
            if text
            else "dropped"
        )
        results.append(
            ProjectedBlock(
                name=block.name,
                text=text,
                priority=block.priority,
                required=block.required,
                original_tokens=original[block.name],
                projected_tokens=tokens,
                status=status,
            )
        )
    return ContextProjection(
        text=final_text,
        blocks=tuple(results),
        max_tokens=cap,
        original_tokens=sum(original.values()),
        projected_tokens=count_tokens(final_text) if final_text else 0,
    )
