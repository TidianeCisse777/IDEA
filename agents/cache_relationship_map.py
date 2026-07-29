"""Compact, permanent map of linked source metadata available to the agent."""


CACHE_RELATIONSHIP_MAP = """## Persistent linked-data map
- EcoTaxa sample -> project: `samples_cache.project_id` ->
  `projects_cache.project_id` (title, instrument, description, status, contact).
- Sample -> cast/station: `profile_id` = cast; `station_id` = station.
- Missing active attribute but declared link -> retrieve it before deriving or
  rendering; never synthesize a label from an identifier/literal.
"""
