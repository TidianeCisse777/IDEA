"""Regression tests for suppressing Open WebUI's duplicate file RAG."""
from __future__ import annotations

import asyncio

from openwebui.idea_file_bridge_filter import Filter


def test_idea_file_bridge_filter_removes_only_transient_file_metadata():
    body = {
        "model": "copepod-agent",
        "metadata": {"chat_id": "chat-1", "files": [{"id": "file-1"}]},
    }

    result = asyncio.run(Filter().inlet(body))

    assert result["metadata"] == {"chat_id": "chat-1"}
    assert body["metadata"]["files"] == [{"id": "file-1"}]


def test_idea_file_bridge_filter_leaves_other_models_untouched():
    body = {"model": "another-model", "metadata": {"files": [{"id": "file-1"}]}}

    assert asyncio.run(Filter().inlet(body)) == body
