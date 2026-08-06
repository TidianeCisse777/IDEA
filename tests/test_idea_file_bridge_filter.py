"""Regression tests for suppressing Open WebUI's duplicate file RAG."""
from __future__ import annotations

import asyncio

from openwebui.idea_file_bridge_filter import Filter


def test_idea_file_bridge_filter_removes_transient_files_in_both_owui_shapes():
    body = {
        "model": "copepod-agent",
        "metadata": {"chat_id": "chat-1", "files": [{"id": "file-1"}]},
        "files": [{"id": "file-1"}],
    }

    result = asyncio.run(Filter().inlet(body))

    assert result["metadata"] == {"chat_id": "chat-1"}
    assert "files" not in result
    assert body["metadata"]["files"] == [{"id": "file-1"}]
    assert body["files"] == [{"id": "file-1"}]


def test_idea_file_bridge_filter_leaves_other_models_untouched():
    body = {"model": "another-model", "metadata": {"files": [{"id": "file-1"}]}}

    assert asyncio.run(Filter().inlet(body)) == body
