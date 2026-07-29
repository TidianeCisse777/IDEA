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
        if not isinstance(metadata, dict) or not metadata.get("files"):
            return body

        clean_body = dict(body)
        clean_metadata = dict(metadata)
        clean_metadata.pop("files", None)
        clean_body["metadata"] = clean_metadata
        return clean_body
