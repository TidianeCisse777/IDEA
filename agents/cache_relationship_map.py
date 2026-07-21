"""Compact, permanent map of linked source metadata available to the agent."""


CACHE_RELATIONSHIP_MAP = """## Persistent linked-data map

- EcoTaxa sample → project: `samples_cache.project_id` → `projects_cache.project_id`; canonical project metadata: `projects_cache.title`, `instrument`, `description`, `status`, `contact_name`.
- EcoTaxa sample → cast/station: `samples_cache.profile_id` is the cast and `samples_cache.station_id` is the station.

When a requested attribute is absent from the active dataset but present through a declared relationship, retrieve the linked value before deriving or rendering. Never synthesize a substitute label from an identifier or a literal table.
"""
