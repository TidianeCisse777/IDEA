# Tool Registry

Composition de "tools" Python injectés dans le sandbox OpenInterpreter selon les tags du profil d'agent. **Ce ne sont pas des function-calls LLM** — c'est du code Python que le LLM invoque en écrivant du code dans le sandbox.

Voir [`ADR 003`](../../docs/adr/003-tool-injection-via-computer-run.md) pour le rationale.

---

## Architecture

```
registry.py              ← Tool dataclass + Registry singleton + render(tags)
tools/
  __init__.py            ← import side-effect : enregistre tous les tools
  core_tools.py          ← _imports + helpers communs
  station_tools.py       ← API tide gauges UHSLC
  climate_tools.py       ← indices climatiques (ENSO, etc.)
  web_tools.py           ← recherche web
  rag_tools.py           ← query knowledge base (PaperQA)
  mcp_tools.py           ← invocation d'outils MCP
  copepod_columns.py     ← describe / validate colonnes EcoTaxa/EcoPart
  copepod_data.py        ← inspection + roles + résumés de datasets
  copepod_rag.py         ← query du Chroma copépode
  copepod_remote_sources.py ← fetch Bio-Oracle + OGSL ERDDAP
  copepod_sources_meta.py ← métadonnées des sources distantes
  copepod_taxonomy.py    ← lookup WoRMS taxonomy
```

### Le contrat `Tool`

```python
@dataclass(frozen=True)
class Tool:
    name: str                # identifiant unique
    tags: frozenset[str]     # tags d'inclusion (ex: {"core", "copepod"})
    code: str                # code Python brut concaténé par render()
```

### `registry.render(tags: set[str]) -> str`

Concatène le `code` de tous les `Tool` dont au moins un tag matche. Le résultat est une grande chaîne Python injectée via `interpreter.computer.run("python", code)`.

---

## Tools enregistrés (par tag)

### Tag `core` — toujours présent

| Tool | Fonctions exposées au LLM |
|---|---|
| `_imports` | `import os, json, pd, np, plt, matplotlib, folium, requests, ...` (libs partagées) |
| `core_tools` | `get_datetime()`, `fractional_year_to_datetime(year)` |
| `station_tools` | `get_station_info(station_query)`, `extract_text_from_station_response(...)` |

### Tag `station` — géoscience marégraphique

Inclut `station_tools` (voir ci-dessus).

### Tag `climate`

| Tool | Fonctions |
|---|---|
| `climate_tools` | `get_climate_index(climate_index_name: str) -> pd.DataFrame` — ONI, PDO, etc. |

### Tag `web`

| Tool | Fonctions |
|---|---|
| `web_tools` | `web_search(query)`, `extract_web_query_response(response)` |

### Tag `rag` — PaperQA knowledge base

| Tool | Fonctions |
|---|---|
| `rag_tools` | `query_knowledge_base(query, user_id, session_id=None)` |

### Tag `mcp` — Model Context Protocol

| Tool | Fonctions |
|---|---|
| `mcp_tools` | Wrappers de `core/mcp/tools.py` pour appeler des outils MCP enregistrés |

### Tags copépode

Ces tags sont activés par `agents/copepod_profile.py` uniquement.

| Tag | Tool | Fonctions principales |
|---|---|---|
| `copepod_columns` | `copepod_columns` | `describe_column(name, source_hint, session_id)`, `check_column_for_calc(roles, calc, session_id)` |
| `copepod_data` | `copepod_data` | `inspect_file(path, sample_rows=500)`, `inspect_and_report(file_paths, session_id)`, `infer_column_roles(...)`, `summarize_understanding(...)`, `profile_join_keys(left, right, lk, rk)` |
| `copepod_rag` | `copepod_rag` | `query_copepod_knowledge_base(question, session_id, top_k=3)` |
| `copepod_remote_sources` | `copepod_remote_sources` | `fetch_remote_source_dataset(session_key, source_id, params, output_filename=None)` |
| `copepod_sources_meta` | `copepod_sources_meta` | `list_available_sources(...)`, `describe_source(id, ...)`, `plan_remote_source_request(text, ...)` |
| `copepod_taxonomy` | `copepod_taxonomy` | `lookup_worms_taxonomy(query, include_children=False, marine_only=True)` |

---

## Profils d'agent → tags activés

| Profil | Tags actifs |
|---|---|
| `generic` | `core`, `station`, `climate`, `web`, `rag`, `mcp` |
| `copepod` | `core`, `web`, `rag`, `mcp`, `copepod_columns`, `copepod_data`, `copepod_rag`, `copepod_remote_sources`, `copepod_sources_meta`, `copepod_taxonomy` |

Source : `tool_tags` dans la classe `AssistantProfile` de chaque profil (`agents/generic_profile.py`, `agents/copepod_profile.py`).

---

## Observabilité runtime

`registry.py` injecte automatiquement un wrapper `COPEPOD_OBSERVABILITY_CODE` autour de chaque tool quand le profil copépode est actif. Ce wrapper :

- Mesure la durée d'exécution
- Capture les arguments (redaction des clés sensibles : `auth_token`, `token`, `password`, `secret`, `api_key`, `key`)
- Compacte les retours (`max_length=4000`)
- Pousse l'info à `core/copepod_observability.py` qui crée une span Langfuse

Best-effort : ne modifie jamais la valeur de retour, n'élève jamais d'exception.

---

## Ajouter un tool

```python
# core/tool_registry/tools/mon_tool.py
from core.tool_registry.registry import Tool, registry

_code = '''
def mon_tool(param: str) -> dict:
    """Description visible par le LLM via la docstring."""
    return {"result": param}
'''

registry.register(Tool(name="mon_tool", tags=frozenset({"mon_domaine"}), code=_code))
```

Puis ajouter l'import dans `core/tool_registry/tools/__init__.py` et déclarer `"mon_domaine"` dans `tool_tags` du profil concerné.

---

## Voir aussi

- [`CLAUDE.md`](../../CLAUDE.md) — patron complet + où aller pour modifier
- [`ADR 003`](../../docs/adr/003-tool-injection-via-computer-run.md) — pourquoi cette approche
- `core/instruction_renderer/blocks/tool_signatures.py` — signatures exposées au LLM dans le system prompt
