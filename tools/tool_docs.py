"""Deterministic Markdown inventory generated from the tool policy registry."""

from __future__ import annotations

from collections.abc import Collection, Mapping

from tools.tool_catalog import ToolPolicy

START_MARKER = "<!-- TOOL-INVENTORY:START -->"
END_MARKER = "<!-- TOOL-INVENTORY:END -->"


def _yes_no(value: bool) -> str:
    return "oui" if value else "non"


def render_tool_inventory(
    policies: Mapping[str, ToolPolicy],
    optional_names: Collection[str],
) -> str:
    """Render the stable policy inventory included in TOOLS.md."""
    optional = set(optional_names)
    mandatory_count = len(set(policies) - optional)
    total_count = len(policies)
    lines = [
        f"Inventaire généré : **{mandatory_count} tools obligatoires**, "
        f"**{total_count} avec SQL**.",
        "",
        "| Tool | Famille | Source | Risque | Confirmation | Optionnel | I/O distant | État de session |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in sorted(policies):
        policy = policies[name]
        lines.append(
            f"| `{name}` | {policy.family} | {policy.source} | {policy.risk} | "
            f"{_yes_no(policy.requires_confirmation)} | {_yes_no(name in optional)} | "
            f"{_yes_no(policy.remote_io)} | {_yes_no(policy.mutates_session)} |"
        )
    return "\n".join(lines)


def replace_generated_inventory(document: str, inventory: str) -> str:
    """Replace only the marked inventory block and preserve all narrative."""
    start = document.find(START_MARKER)
    end = document.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        raise ValueError("TOOLS.md is missing valid TOOL-INVENTORY markers")
    end += len(END_MARKER)
    replacement = f"{START_MARKER}\n{inventory.rstrip()}\n{END_MARKER}"
    return document[:start] + replacement + document[end:]
