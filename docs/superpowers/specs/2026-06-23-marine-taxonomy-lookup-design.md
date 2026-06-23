# Marine Taxonomy Lookup Design

## Goal

Improve the agent's taxonomic knowledge for marine organisms and taxon terms by
adding a single deterministic tool that combines local project knowledge,
authoritative WoRMS validation, and a Wikipedia fallback for plain-language
definitions.

The feature must help the agent understand scientific terms and definitions on
any taxon mention, not only EcoTaxa annotations. It must not weaken existing
EcoTaxa data routing: data questions still use EcoTaxa tools; knowledge
questions use the taxonomy lookup.

## Current State

The active agent already has:

- `query_copepod_knowledge_base` for local copepod/domain knowledge.
- `search_ecotaxa_taxa` for EcoTaxa taxonomy autocomplete.
- `count_ecotaxa_taxa` for project-level V/P/D/U counts by taxon.
- `find_ecotaxa_observations` for cached EcoTaxa samples whose projects attest
  a taxon.

The repository also contains a legacy WoRMS lookup in
`core/tool_registry/tools/copepod_taxonomy.py`, but that legacy registry is not
loaded by `agent.py`. The active tool surface is assembled from `tools/*`.

## Selected Approach

Implement one active LangChain tool:

```python
lookup_marine_taxonomy(term: str, include_children: bool = False) -> str
```

The tool performs:

1. Local RAG lookup using `query_copepod_rag`.
2. WoRMS REST lookup for authoritative taxonomy.
3. French Wikipedia lookup through the MediaWiki Action API only when the RAG
   does not provide a useful definition.

WoRMS is the source of truth for scientific validation. Wikipedia is only a
fallback for vulgarized definitions.

## Source Rules

- RAG local is preferred for definitions when it has a relevant result.
- WoRMS is always used for scientific name validation when the term can be
  resolved.
- Wikipedia is never used as the official taxonomy source.
- If WoRMS cannot resolve the term, the tool must say so explicitly and keep
  any available definition separate from official validation.
- The tool must not invent AphiaID, rank, status, synonymy, or classification.

## Routing Rules

Update `agents/copepod_system_prompt.py` so the agent calls
`lookup_marine_taxonomy` for knowledge questions such as:

- "qu'est-ce que X"
- "définis X"
- "explique X"
- "c'est quoi un copépode gélatineux"
- "classification de X"
- "AphiaID de X"
- "X est-il un nom accepté"

Do not use this tool for EcoTaxa data requests:

- "combien de X dans le projet Y"
- "où trouve-t-on X"
- "quels samples avec X"
- "liste les projets avec X"

Those remain routed to `count_ecotaxa_taxa`, `find_ecotaxa_observations`, or
other EcoTaxa read-only tools after loading `ecotaxa_navigation`.

## Tool Output

Return concise markdown with these sections when available:

- `Définition`
- `Validation WoRMS`
- `Classification`
- `Synonymie`
- `Enfants directs` when `include_children=True`
- `Limites`

Include the definition source as `RAG local` or `Wikipédia fallback`.
Include WoRMS source details such as AphiaID and accepted status when present.

## Implementation Boundaries

- Add a new core package, e.g. `core/taxonomy_lookup/`.
- Add a new active tool module, e.g. `tools/taxonomy_tool.py`.
- Register the tool in `agent.py`.
- Keep EcoTaxa taxonomy tools unchanged unless tests expose a routing conflict.
- Do not add new heavy-operation confirmation gates; this is a light read-only
  lookup.
- Use `requests` with timeouts and controlled error handling.

## Tests

Add tests for:

- RAG definition preferred over Wikipedia when RAG returns content.
- Wikipedia fallback used when RAG returns no useful definition.
- WoRMS accepted name, AphiaID, rank, status, and classification rendering.
- Synonym result follows `valid_AphiaID` for accepted classification when
  available.
- EcoTaxa data routing rules remain present in the system prompt.
- `make_agent` includes `lookup_marine_taxonomy`.
- Failure cases: unknown Wikipedia page, WoRMS not found, API timeout.

Run targeted tests for the new tool, agent factory, and existing EcoTaxa
taxonomy tests.

## Acceptance Criteria

- The agent can answer a definition/classification question for a marine taxon
  using local knowledge plus WoRMS validation.
- If local knowledge is missing, it can use a Wikipedia fallback definition
  while still treating WoRMS as the official taxonomy authority.
- EcoTaxa count/location questions continue routing to existing EcoTaxa tools.
- Tests cover the fallback order and prompt routing constraints.
