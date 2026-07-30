"""Persistent state for the last successful graph render."""
from __future__ import annotations

from tools.session_store import SessionStore


_LAST_GRAPH_STATE_SUFFIX = "last_graph_state"
_MAX_EDITABLE_CODE_CHARS = 24_000


def graph_edit_reference(store: SessionStore, thread_id: str) -> str:
    """Return the last executable script for a safe graph follow-up."""
    entry = store.get(f"{thread_id}:{_LAST_GRAPH_STATE_SUFFIX}") or {}
    meta = entry.get("meta") or {}
    code = meta.get("code")
    if not isinstance(code, str) or not code.strip() or len(code) > _MAX_EDITABLE_CODE_CHARS:
        return ""
    plot_data_ref = str(meta.get("plot_data_ref") or "df actif")
    graph_id = str(meta.get("graph_id") or "inconnu")
    return (
        "\n\nLAST GRAPH AVAILABLE\n"
        "- Purpose: this script reproduces the last validated render.\n"
        "- Use: use it only when the user's message is an iteration of that graph. "
        "Reuse it exactly, modify this script only for the requested change, then "
        "call run_graph. Do not use run_pandas or a new planning step.\n"
        "- Do not use it when the user explicitly requests a new graph or new data; "
        "follow the normal workflow instead.\n"
        "- Data: to preserve exactly the same rows, use `df_graph_plot` / `plot_df` "
        "as the render table if the script starts from the active DataFrame.\n"
        "- Replacement: every successful new render replaces this saved state; a "
        "failed render keeps it unchanged.\n"
        f"- previous image: {graph_id}\n"
        f"- render table to reuse: {plot_data_ref}\n"
        "```python\n"
        f"{code.rstrip()}\n"
        "```"
    )
