"""Compact, permanent map of linked source metadata available to the agent."""


CACHE_RELATIONSHIP_MAP = """## Persistent linked-data map
- EcoTaxa sample -> project: `samples_cache.project_id` ->
  `projects_cache.project_id` (title, instrument, description, status, contact).
- EcoTaxa identifiers are typed by their observed field, never by the user's
  label or by string resemblance: `project_id` is the project key;
  `projects_cache.title` is a project title; `samples_cache.sample_id` is the
  exportable sample key; `original_id` is the source sample label; `profile_id`
  is the cast/profile and `station_id` is the station. A value already observed
  as a project title must be resolved through its `project_id`, never retried as
  a `sample_id` or `original_id`.
- Preserve the requested grain during recovery. A sample-scoped request requires
  an explicit, non-empty `sample_id` selection before object export. Never widen
  it to the whole project with `sample_ids=None`; if the sample remains missing
  or ambiguous after the narrow cache lookup, ask one short question or report
  the unresolved scope instead of exporting a substitute scope.
- Missing active attribute but declared link -> retrieve it before deriving or
  rendering; never synthesize a label from an identifier/literal.
"""
