"""
title: IDEA file bridge
author: IDEA
version: 1.0.0
required_open_webui_version: 0.9.6
"""


class Filter:
    """Leave Open WebUI uploads to the IDEA file bridge, not native RAG."""

    async def inlet(self, body: dict, __user__=None) -> dict:
        """Prevent duplicate document retrieval for the IDEA model only.

        The agent receives ``X-OpenWebUI-Chat-Id`` and reads the attachments
        from the persisted chat itself.  Removing this transient metadata
        therefore stops Open WebUI from injecting file contents and emitting
        ``queries_generated`` / ``sources_retrieved`` on every turn, without
        making the files unavailable to IDEA.
        """
        if body.get("model") != "copepod-agent":
            return body

        metadata = body.get("metadata")
        has_metadata_files = isinstance(metadata, dict) and bool(metadata.get("files"))
        has_top_level_files = bool(body.get("files"))
        if not has_metadata_files and not has_top_level_files:
            return body

        clean_body = dict(body)
        if isinstance(metadata, dict):
            clean_metadata = dict(metadata)
            clean_metadata.pop("files", None)
            clean_body["metadata"] = clean_metadata
        # Open WebUI 0.9 keeps the same transient attachments in either shape
        # depending on the chat path.  Strip both before its file-RAG handler;
        # IDEA resolves the durable chat attachments itself from the chat id.
        clean_body.pop("files", None)
        return clean_body
