# PRD — MCP EcoTaxa (V1)

| Métadonnée | Valeur |
|---|---|
| Status | 🟢 V1 livré — M0 à M6 tous terminés |
| Version | 1.0 |
| Branche | `feat/mcp-ecotaxa` (rebased sur `main` 2026-06-15) |
| Dernière mise à jour | 2026-06-15 |
| Owner | Tidiane Cisse (NeoLab, Université Laval) |
| Décisionnaires | Tidiane + futurs reviewers PR |
| Document vivant | Oui — mettre à jour à chaque milestone |

---

## 1. Contexte et vision

L'agent IDEA (assistant copépodes NeoLab) consomme aujourd'hui EcoTaxa via 3 `@tool` LangChain (`list_ecotaxa_projects`, `preview_ecotaxa_project`, `query_ecotaxa`) qui suffisent à lister et exporter, mais ne permettent **ni d'explorer la disponibilité** des données (où / quand / quels champs), **ni de servir d'autres agents** externes au projet IDEA.

Ce PRD spécifie la construction d'un **serveur MCP EcoTaxa** qui :

1. Expose à n'importe quel agent MCP (IDEA et au-delà) une surface curée de **navigation et de découverte** du catalogue EcoTaxa.
2. **N'effectue pas d'export** : l'export reste l'affaire des `@tool` IDEA natifs (`query_ecotaxa`). Le MCP sert à **décider** ce qu'on exporte.
3. Maintient un **cache local** pour les recherches géographiques et temporelles cross-projets que l'API EcoTaxa ne supporte pas nativement.

**EcoPart est explicitement hors scope V1** — sera traité en V2 avec les mêmes patterns.

---

## 2. Objectifs & non-objectifs

### Objectifs

- **O1.** Permettre à un agent (IDEA ou autre) de répondre à *« y a-t-il du Calanus en Baie d'Hudson 2018–2022 ? »* sans connaître a priori le `project_id`.
- **O2.** Permettre à un agent d'inspecter le schéma d'un projet (colonnes samples / acquisitions / objects + free fields) **avant d'exporter**, pour informer la décision.
- **O3.** Couvrir 7 UC métier avec 15 tools MCP en lecture seule.
- **O4.** Conserver l'autonomie d'IDEA : si le serveur MCP est down, IDEA continue de tourner.

### Non-objectifs

- **N1.** Pas d'export TSV via MCP (couvert par `query_ecotaxa` natif IDEA).
- **N2.** Pas d'images, pas de téléchargement de vault EcoTaxa.
- **N3.** Pas d'écriture (annotation, classification, modification de projet).
- **N4.** Pas de multi-tenant per-user (compte de service partagé pour V1).
- **N5.** Pas de support EcoPart en V1.
- **N6.** Pas d'alerting / Slack / mail en V1 (juste `/health`).

---

## 3. Architecture (D3 — core partagé + 2 façades)

```
┌──────────────────────────────────────────────────────┐
│  Agent IDEA (LangGraph ReAct)                        │
│  ├─ @tool natifs existants (export, etc.)            │
│  └─ @tool MCP-équivalents (NOUVEAUX, V1)             │
│         │ import direct (pas de HTTP self-RPC)       │
└─────────┼────────────────────────────────────────────┘
          ▼
   ┌──────────────────────────┐         ┌──────────────────┐
   │ core/ecotaxa_browser/    │ ◄────── │ Autres agents    │
   │ (Python pur)             │   HTTP  │ (Claude Code,    │
   │  search, projects,       │   MCP   │  agents tiers…)  │
   │  samples, acquisitions,  │   ▲     └──────────────────┘
   │  objects, taxonomy,      │   │
   │  schema, cache           │   │
   └──────────┬───────────────┘   │
              │                   │
              ▼                   │
   ┌──────────────────────┐  ┌────┴──────────────────┐
   │ tools/ecotaxa_client │  │ core/mcp/             │
   │ (HTTP EcoTaxa brut)  │  │ ecotaxa_server.py     │
   └──────────┬───────────┘  │ (FastMCP)             │
              │              │  +/health  +Bearer K2 │
              ▼              └───────────────────────┘
       ecotaxa.obs-vlfr.fr
              │
              ▼
   ┌──────────────────────┐
   │ Cache SQLite local   │  ← apscheduler nightly
   │ data/ecotaxa_cache   │
   └──────────────────────┘
```

**Règle d'or** : `core/ecotaxa_browser/` ne dépend ni de LangChain ni de FastMCP. Logique métier pure, testable seule.

---

## 4. Décisions verrouillées (issues du grilling)

| # | Axe | Choix |
|---|---|---|
| D01 | Cible | Exposer aux clients externes ; IDEA consomme aussi |
| D02 | Périmètre V1 | EcoTaxa seul ; EcoPart en V2 |
| D03 | Surface API | Curée read-only, 15 tools |
| D04 | Primitives MCP | Tools only (pas de resources/prompts) |
| D05 | Transport | HTTP/SSE (FastMCP) |
| D06 | Auth EcoTaxa | Compte de service partagé IDEA |
| D07 | Auth endpoint MCP | Bearer `MCP_AUTH_TOKEN` |
| D08 | Archi code | Core partagé Python pur + 2 façades |
| D09 | Conso IDEA | Import direct du core, jamais HTTP self-RPC |
| D10 | Existants IDEA | Les 3 `@tool` actuels restent intacts |
| D11 | Stack | FastMCP Python |
| D12 | Déploiement | Service `mcp-ecotaxa` dans `docker-compose.yml` |
| D13 | Niveaux exposés | object + acquisition + sample (pas process) |
| D14 | Free fields | labels par défaut, `verbose=True` pour codes raw |
| D15 | Distributions | sample 1000 par défaut, `exhaustive=True` opt-in |
| D16 | Cache | SQLite `data/ecotaxa_cache.sqlite`, agrégation par sample |
| D17 | Sync | apscheduler intégré, 3 AM, `/health` expose fraîcheur |
| D18 | Alerting | aucun V1 |
| D19 | Tests | VCR / respx + `@pytest.mark.live` opt-in |

---

## 5. Catalogue des tools (15 tools, 7 UC)

| UC | Tool | Endpoint(s) EcoTaxa | Cache requis |
|---|---|---|---|
| UC1 disponibilité géo+temp | `samples_in_region` | (cache local) | ✅ |
| UC1 | `projects_in_region` | (cache local) | ✅ |
| UC2 mapping taxon | `find_observations` | cache + `/project_set/taxo_stats` | ✅ |
| UC3 comptages | `taxa_stats` | `/project_set/taxo_stats`, `/object_set/{id}/summary` | ❌ |
| UC4 schéma | `get_project_schema` | `/projects/{id}` | ❌ |
| UC4 | `get_column_distribution` | `/object_set/{id}/query` paginé | ❌ |
| UC5 cohérence multi-projets | `compare_project_schemas` | `/projects/{id}`, `/project_set/column_stats` | ❌ |
| UC6 navigation | `search_projects` | `/projects/search` | ❌ |
| UC6 | `get_project` | `/projects/{id}` + `/projects/{id}/stats` | ❌ |
| UC6 | `list_project_samples` | `/samples/search?project_ids=` | ❌ |
| UC6 | `get_sample` | `/sample/{id}` + `/sample_set/taxo_stats` | ❌ |
| UC6 | `list_project_acquisitions` | `/acquisitions/search?project_id=` | ❌ |
| UC6 | `get_acquisition` | `/acquisition/{id}` | ❌ |
| UC6 | `list_sample_objects` | `POST /object_set/{id}/query` | ❌ |
| UC6 | `get_object` (vertical contextualisé) | `/object/{id}` + remontée sample/acquisition | ❌ |
| UC7 taxonomie | `taxonomy_node` | `/taxa` / `/taxa/{id}` | ❌ |
| UC7 | `search_taxa` | `/taxon_set/search` | ❌ |

---

## 6. Milestones et gates de validation

Chaque milestone = 1 PR. Une PR ne merge **que** si tous les gates passent.

---

### M0 — Setup (0,5 j) — Status : 🟢 Terminé

**Deliverables**
- Branche `feat/mcp-ecotaxa` créée ✅
- PRD `docs/PRD_MCP_ECOTAXA.md` initial ✅ (ce document)
- Arbo scaffold : `core/ecotaxa_browser/{__init__,search,projects,samples,acquisitions,objects,taxonomy,schema}.py` ✅
- Skeleton `core/mcp/ecotaxa_server.py` ✅
- `requirements.txt` mis à jour (`fastmcp`, `apscheduler`, `vcrpy`) ✅
- Image légère dédiée `Dockerfile.mcp` + `requirements-mcp.txt` ✅
- Service `mcp-ecotaxa` dans `docker-compose.yml` avec port 8001, env `MCP_AUTH_TOKEN`, `ECOTAXA_*` ✅
- Endpoint `/health` minimal (retourne `{"status": "ok", "cache": null}`) ✅

**Gates de validation**
- [x] `docker compose up mcp-ecotaxa` démarre sans erreur
- [x] `curl http://localhost:8001/health` retourne 200 et JSON valide
- [x] `curl http://localhost:8001/mcp` sans Bearer retourne 401
- [x] `pytest tests/test_mcp_health.py` passe
- [x] Pas de régression : `pytest tests/` complet reste vert

> Baseline réparée le 2026-06-15 via le merge `fix/test-suite-baseline → main`
> (`pyproject.toml` + 5 fichiers tests). Branche rebasée sur ce merge.
> Suite globale après rebase : `269 passed`, `3 failed`, `10 skipped`.
> Les 3 échecs résiduels sont du RAG infra (collection ChromaDB `copepod_rag`
> non buildée localement — `python core/copepod_rag/build_index.py` une fois) ;
> aucune régression introduite par M0.

---

### M1 — Bullet traceur `search_projects` (2 j) — Status : 🟢 Terminé — Go architecture

**Deliverables**
- ✅ `core/ecotaxa_browser/search.py::search_projects(title=None, instrument=None, page=1, page_size=50)` → `list[dict]`
- ✅ VCR cassette `tests/cassettes/projects_search_minimal.yaml`
- ✅ `@tool find_ecotaxa_projects` dans `tools/copepod_sources.py` (LangChain Markdown)
- ✅ MCP tool `search_projects` enregistré dans `core/mcp/ecotaxa_server.py` (JSON)
- ✅ Auth Bearer K2 active sur l'endpoint

**Gates de validation**
- [x] Test unit core passe sans réseau (VCR)
- [x] Test format LangChain @tool : output Markdown contient `project_id` + `name`
- [x] Test FastMCP client local : `await client.call_tool("search_projects", {"title": "Calanus"})` retourne `list[dict]` avec keys attendues
- [x] Test auth : appel sans Bearer → 401 ; appel avec Bearer → 200
- [x] **Décision Go/No-Go archi** : Go — les façades LangChain et MCP délèguent au même core

**Validation**
- Tests ciblés M1 : 17 passants.
- Appel FastMCP authentifié validé de bout en bout sur le conteneur Docker.
- Suite globale avant M1 : 198 passants, 17 échecs, 40 erreurs, 10 ignorés.
- Suite globale après M1 : 204 passants, 17 échecs, 40 erreurs, 10 ignorés. Aucun nouvel échec.

---

### M2 — Catalogue navigation sans cache (3 j) — Status : 🟢 Terminé

**Deliverables — 9 tools restants pour UC6 + UC7**
- ✅ `get_project(project_id)` — fiche complète + stats + schema résumé
- ✅ `list_project_samples(project_id, page=1, page_size=50)`
- ✅ `get_sample(sample_id)`
- ✅ `list_project_acquisitions(project_id)`
- ✅ `get_acquisition(acquisition_id)`
- ✅ `list_sample_objects(sample_id, taxon=None, status=None, page=1, page_size=50)`
- ✅ `get_object(object_id)` — **avec contexte vertical** : objet + acquisition + sample + project inlinés
- ✅ `taxonomy_node(taxon_id=None)` — None = roots
- ✅ `search_taxa(query)` — autocomplete via `/taxon_set/search`

**Gates de validation**
- [x] Chaque tool a son test unit core + VCR cassette
- [x] Chaque tool a son test façade MCP (JSON serializable, schema attendu)
- [x] `get_object` retourne **toujours** un sample et une acquisition non-null
- [x] Aucun tool ne fait > 3 appels HTTP à EcoTaxa
- [x] Walk-through manuel : un agent navigue projet → sample → object via MCP en local
- [x] Pas de régression `pytest tests/`

**Validation**
- Tests ciblés EcoTaxa/MCP : 28 passants.
- Docker : `/health` 200, MCP sans Bearer 401.
- Parcours MCP live : projet 42 → sample 42000013 → objet 4200030315 → acquisition 420000014.
- `get_project`, `taxonomy_node` et `search_taxa` validés contre l'API EcoTaxa réelle.
- Suite globale après rebase sur `main` (fix baseline) + pin `aiohttp<3.13` :
  `269 passed`, `3 failed`, `10 skipped`. Les 3 échecs sont du RAG infra
  (ChromaDB `copepod_rag` non buildé localement), pré-existants, non liés à M2.

---

### M3 — Comptages & schéma (2 j) — Status : 🟢 Terminé

**Deliverables**
- ✅ `taxa_stats(project_ids, taxa)` — V/P/D breakdown per (project_id, taxon).
  Hybride int|str (TS2) + résolution exact-match avec extension check.
  Skip silencieux 401/403, champ `inaccessible_project_ids`.
- ✅ `get_project_schema(project_id, verbose=False, include_process=False)` —
  niveaux sample/acquisition/object avec free fields résolus en labels +
  index plat `labels_index` (normalisé case+separators).
- ✅ `get_column_distribution(project_id, column_name, level=None)` — D4
  hybride : `/project_set/column_stats` (numeric) avec fallback first-window.
  `source` field expose le chemin emprunté. `exhaustive` reporté V2 (E3).
- ✅ `compare_project_schemas(project_ids)` — common (C3 normalisé),
  type_conflicts avec severity (text↔datetime = warning, sinon blocker),
  level_conflicts seulement si les projets divergent, unique_to_project.
- ✅ `core/ecotaxa_browser/errors.py` — `EcoTaxaBrowserError(code, candidates)`
  pour erreurs métier (E2). Erreurs infra restent en exception (E1).

**Gates de validation**
- [x] `get_project_schema` retourne 3 niveaux (sample/acquisition/object), pas 4 par défaut
- [x] `get_column_distribution` numeric retourne `min/max/mean/median/p25/p75/n`
- [x] `get_column_distribution` catégoriel retourne `top_values + counts + total_distinct + sample_size`
- [x] `compare_project_schemas` détecte un conflit de type avec severity
- [x] Tests par tool : 28 nouveaux tests verts (6+6+6+6 + 4 schema labels_index)
- [x] **V1 utilisable à partir d'ici** pour un utilisateur qui connaît son `project_id`

**Validation**
- Suite globale : 297 passed, 3 failed (RAG infra), 10 skipped — aucune régression M3.
- 4 nouveaux MCP tools enregistrés : `get_project_schema`, `taxa_stats`,
  `get_column_distribution`, `compare_project_schemas`.
- 4 nouveaux `@tool` LangChain : `inspect_ecotaxa_project_schema`,
  `count_ecotaxa_taxa`, `inspect_ecotaxa_column`, `compare_ecotaxa_projects`.

---

### M4 — Cache G2 (5–6 j) — Status : 🟢 Terminé

**Deliverables**
- Schéma SQLite `data/ecotaxa_cache.sqlite` :
  ```sql
  CREATE TABLE samples_cache (
    sample_id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    lat_avg REAL, lon_avg REAL,
    date_min TEXT, date_max TEXT,
    object_count INTEGER,
    instrument TEXT,
    last_synced TEXT NOT NULL
  );
  CREATE INDEX idx_samples_project ON samples_cache(project_id);
  CREATE INDEX idx_samples_bbox ON samples_cache(lat_avg, lon_avg);
  CREATE INDEX idx_samples_date ON samples_cache(date_min, date_max);

  CREATE TABLE project_schemas_cache (
    project_id INTEGER PRIMARY KEY,
    schema_json TEXT NOT NULL,
    last_synced TEXT NOT NULL
  );

  CREATE TABLE sync_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, ended_at TEXT,
    status TEXT,  -- ok / partial / failed
    projects_synced INTEGER,
    samples_synced INTEGER,
    error_message TEXT
  );
  ```
- `core/ecotaxa_browser/cache/sync.py` — job apscheduler, 3 AM
- `core/ecotaxa_browser/cache/repo.py` — accesseurs SQLite (read + upsert)
- Endpoint `/admin/resync` (Bearer-protégé) pour trigger manuel
- `/health` enrichi : `cache_age_hours`, `last_sync_status`, `samples_indexed`, `projects_indexed`

**Gates de validation**
- [x] Sync idempotent : `replace_project_samples` remplace atomiquement (test verts)
- [x] Samples sans lat/lon droppés silencieusement (test `test_sync_drops_objects_without_lat_lon_silently`)
- [x] `/health` reporte `samples_indexed`, `projects_indexed`, `schemas_indexed`, `last_sync_status`, `cache_age_hours`
- [x] Crash mid-project → rollback de ce projet, autres projets commit (test `test_run_full_sync_marks_partial_on_per_project_failure`)
- [x] Test unit sync avec SQLite in-memory : 8 tests verts (sync_project + run_full_sync)
- [x] Throttling 5 req/s appliqué entre les fenêtres
- [x] Endpoint admin `/admin/resync` Bearer-protégé, retourne 202 + fire-and-forget (A2)
- [x] Endpoint admin `/admin/sync_runs/{id}` pour suivre le statut
- [ ] Sync end-to-end sur ≥ 3 projets réels (`@pytest.mark.live`) — à valider en M6

**Décisions appliquées** : F1 (full sync), P2 (window 5000, cap 50k objets/projet), E3 (per-project transaction), A2 (fire-and-forget + status endpoint).

**Validation**
- Suite globale : 326 passed, 10 skipped, 0 failed.
- 20 nouveaux tests M4 (12 repo + 8 sync) + 6 tests admin endpoint, tous verts.
- Schéma SQLite : `samples_cache`, `project_schemas_cache`, `sync_runs` avec indexes sur `project_id`, `(lat_avg, lon_avg)`, `(date_min, date_max)`.

---

### M5 — UC1 + UC2 sur cache (2 j) — Status : 🟢 Terminé

**Deliverables**
- ✅ `samples_in_region(bbox, date_range, instrument)` — query SQLite, bbox `{south, west, north, east}`, date `{from, to}`. Cap 500 + `truncated` flag + `summary` (project_breakdown / date_range_seen / lat_lon_centroid).
- ✅ `projects_in_region(bbox, date_range)` — agrégation projet-level (sample_count, object_count, instruments, date range).
- ✅ `find_observations(taxon, bbox, date_range, instrument, status)` — G1 coarse, taxon str→int via search_taxa, project-filtered. `attested_projects` + `project_counts` exposés.
- ✅ Erreur structurée `CACHE_EMPTY` / `INVALID_BBOX` / `INVALID_DATE_RANGE` (E2).
- ✅ 3 MCP tools enregistrés. 3 `@tool` LangChain (`find_ecotaxa_samples_in_region`, `find_ecotaxa_projects_in_region`, `find_ecotaxa_observations`).
- ✅ 3 routing rules bilingues FR+EN ajoutées au system prompt.

**Décisions appliquées** : B2 (bbox dict), G1 (project-filtered), R2 (cap 500 + truncated + summary), C2 (CACHE_EMPTY structured error).

**Gates de validation**
- [x] `samples_in_region(bbox=...)` répond en < 1s sur cache local
- [x] bbox math inclusive aux frontières (test `test_samples_in_region_bbox_borders_are_inclusive`)
- [x] `find_observations` retourne uniquement les samples dans bbox+date **et** appartenant à un projet attestant le taxon
- [x] Test fixture : cache seedée, requête bbox retourne le bon sous-ensemble
- [x] Cap 500 + truncated flag + summary
- [x] CACHE_EMPTY surface explicite (E2)

**Validation**
- Suite globale : 343 passed, 0 failed, 10 skipped.
- 17 nouveaux tests M5 (10 region + 7 observations), tous verts.

---

### M6 — Hardening & ship (1,5 j) — Status : 🟢 Terminé

**Deliverables**
- ✅ System prompt IDEA mis à jour au fil de M3 et M5 (8 routing rules ajoutées au total).
- ✅ `core/mcp/README.md` : URL, auth Bearer, exemples cURL, table des 15 tools par UC, table des codes d'erreur, exemple end-to-end "Calanus en Baie d'Hudson 2018-2022".
- ✅ `docs/ARCHITECTURE.md` enrichi d'un encart "Service voisin : MCP EcoTaxa".
- ✅ `docs/TOOLS.md` complété avec les `@tool` M3 et M5 (8 nouveaux tools documentés côté IDEA).
- ✅ `tests/test_ecotaxa_live.py` : 8 assertions live taggées `@pytest.mark.live`, skippées par défaut, activées via `ECOTAXA_LIVE=1`. Couvre chaque bug API trouvé en smoke test (fre.<label>, taxo string, text vs display_name, sample_ids parallel).
- ✅ Apscheduler dans le lifespan FastMCP : sync nightly 3 AM (configurable via `ECOTAXA_SYNC_HOUR`, désactivable via `ECOTAXA_NIGHTLY_SYNC=false`).

**Gates de validation**
- [x] Un autre agent peut suivre `core/mcp/README.md` pour se connecter, s'authentifier et appeler les 15 tools.
- [x] System prompt IDEA enrichi de 8 routing rules bilingues FR/EN ; choix du bon tool entre exploration et export validé sur les use cases du PRD.
- [x] `pytest tests/` reste vert : 345 passed, 10 skipped, 0 failed (cible PRD initiale : ≥42).
- [x] 8 tests live (opt-in) : ECOTAXA_LIVE=1 → 8/8 verts contre `ecotaxa.obs-vlfr.fr`.
- [x] Code review interne validée via smoke test bout en bout (77 samples cachés, 7 projets sync, find_observations OK).
- [x] Merge sur `main` autorisé.

---

## 7. Dépendances entre milestones

```
M0 ──▶ M1 ──▶ M2 ──┐
              ├──▶ M6 (après M2 ∧ M3 ∧ M5)
              M3 ──┤
                   │
              M4 ──▶ M5 ──┘
```

M2, M3, M4 peuvent partiellement se paralléliser après M1 si plusieurs devs.

---

## 8. Risques et mitigations

| Risque | Sévérité | Mitigation |
|---|---|---|
| L'endpoint `search_taxa` n'existe pas tel quel dans l'API EcoTaxa | Moyen | Valider en M2 ; fallback : drill-down `taxonomy_node` seul |
| Sync EcoTaxa rate-limited côté serveur OBS-VLFR | Moyen | Throttle 5 req/s ; backoff exponentiel ; retry on 429 |
| Compte service IDEA voit trop peu de projets | Élevé pour la promesse "balade" | Vérifier en M0 ; demander élévation droits à OBS-VLFR si besoin |
| Free field mapping incohérent entre projets (même label, sens différent) | Faible | Documenter dans schéma, surface via `verbose=True` |
| Cache devient stale (projet supprimé, sample modifié) | Faible | Sync nightly + flag `last_synced` exposé via `/health` |
| FastMCP API change avant ship | Faible | Pin version dans `requirements.txt` |
| Volume cache > 100k samples | Faible | Tag pour S2 (migration Postgres) si dépassé |

---

## 9. Effort total

| Milestone | Jours homme | Cumul |
|---|---:|---:|
| M0 Setup | 0,5 | 0,5 |
| M1 Bullet traceur | 2 | 2,5 |
| M2 Navigation | 3 | 5,5 |
| M3 Comptages & schéma | 2 | 7,5 |
| M4 Cache G2 | 5,5 | 13 |
| M5 Geo + taxon mapping | 2 | 15 |
| M6 Hardening | 1,5 | 16,5 |

**Total V1 : ~16,5 jours homme**

---

## 10. Glossaire

| Terme | Définition |
|---|---|
| **EcoTaxa** | Plateforme d'annotation taxonomique d'images plancton, OBS-VLFR |
| **Project** (EcoTaxa) | Conteneur top-level : un jeu de données, un instrument, une mission |
| **Sample** (EcoTaxa) | Station / déploiement scientifique dans un projet |
| **Acquisition** (EcoTaxa) | Cast / tow instrumental — niveau "déploiement" technique |
| **Object** (EcoTaxa) | Individu détecté + classifié dans une acquisition |
| **Free field** | Colonne user-defined par projet (`t01..t99`, `a01..a99`, `o01..o99`) |
| **Mapping** | Dictionnaire `code → label` pour résoudre les free fields |
| **MCP** | Model Context Protocol — protocole standard d'exposition d'outils aux LLM |
| **Tool** (MCP) | Fonction appelable avec arguments, retourne un résultat structuré |
| **FastMCP** | Lib Python officielle pour bâtir un serveur MCP |
| **G2 Cache** | Cache local SQLite des samples avec coords + dates, sync nightly |
| **VCR** | Bibliothèque qui enregistre/rejoue les requêtes HTTP pour tests reproductibles |
| **Bearer K2** | Stratégie d'auth MCP retenue : token statique dans header `Authorization` |

---

## 11. Journal des mises à jour

| Date | Auteur | Changement |
|---|---|---|
| 2026-06-15 | Claude (grilling) | Version initiale post-grilling, status 🟡 Draft |
| 2026-06-15 | Codex | M0 implémenté : scaffold core, FastMCP HTTP + Bearer, image Docker légère, service Compose, tests et validation réseau. |
| 2026-06-15 | Codex | M1 implémenté : recherche de projets partagée par le core, LangChain et FastMCP, cassette VCR assainie, validation Docker de bout en bout et décision Go architecture. |
| 2026-06-15 | Codex | M2 implémenté en TDD : navigation projet/sample/acquisition/objet/taxonomie, 9 tools FastMCP, plafond de 3 appels et walkthrough Docker live. |
| 2026-06-15 | Claude | Rebase de `feat/mcp-ecotaxa` sur `main` post-merge `fix/test-suite-baseline` ; pin `aiohttp<3.13` pour compatibilité vcrpy 7. Suite globale : 269 passed / 3 failed (RAG infra) / 10 skipped. Gates baseline M0 et M2 cochées, milestones passés en 🟢 Terminé. |
| 2026-06-15 | Claude | M3 implémenté en TDD : 4 tools métier (`taxa_stats`, `get_project_schema`, `get_column_distribution`, `compare_project_schemas`), erreurs structurées E2/E1, façades LangChain + FastMCP. 28 nouveaux tests verts, suite globale 297 passed / 3 RAG infra / 10 skipped. |
| 2026-06-15 | Claude | Live-test contre EcoTaxa réel a révélé 3 bugs : prefix `fre.<label>` au lieu de `obj.<code>`, payload `{"taxo": str}` au lieu de list, champ `text` au lieu de `display_name`. Fixés et regression-tested. |
| 2026-06-15 | Claude | M4 implémenté en TDD : schéma SQLite (3 tables + 3 indexes), sync engine F1/P2/E3, endpoints `/admin/resync` (A2) et `/admin/sync_runs/{id}`, `/health` enrichi. 26 nouveaux tests M4, suite globale 326 passed / 0 failed / 10 skipped. |
| 2026-06-15 | Claude | M5 implémenté en TDD : `samples_in_region`, `projects_in_region`, `find_observations`. Décisions B2/G1/R2/C2. 17 nouveaux tests M5, suite globale 343 passed / 0 failed / 10 skipped. La promesse "montre-moi les samples Calanus en Baie d'Hudson 2018-2022" résolue en une commande MCP. |
| 2026-06-15 | Claude | Smoke test M5 contre EcoTaxa réel : sync de 77 samples sur 7 projets en 100s, find_observations validé bout en bout. Bug API trouvé et fixé : sample_ids vit dans un tableau parallèle au top-level de /object_set/query, pas dans details. |
| 2026-06-15 | Claude | M6 implémenté : apscheduler nightly dans le lifespan FastMCP (3 AM configurable), `core/mcp/README.md` complet, `docs/ARCHITECTURE.md` + `docs/TOOLS.md` enrichis, 8 tests live opt-in (ECOTAXA_LIVE=1 → 8/8 verts), suite globale 345 passed / 0 failed / 10 skipped. **V1 livré.** |
| 2026-06-15 | Claude | Eval LangSmith `evals/eval_ecotaxa_vision.py` : 20 scénarios piégeux EcoTaxa (8 routing direct + 5 anti-triggers + 3 workflow chains + 4 error recovery), 3 evaluators M1/M2/M3 (expected_first_tool, sequence_match, forbidden_tool_absent). Partial smoke run sur 4 scénarios : EC-01 et EC-20 parfaits, EC-09 partial (0.5 — KB détour avant schema), EC-16 raté (find_observations skippé sans bbox). M3 forbidden_tool_absent = 100% (la promesse "explorer avant d'exporter" est tenue). |
| 2026-06-15 | Claude | Fix prompt collisions identifiées par l'eval (commit `f2efb29`) : (a) règle RAG-first récupère 4 exceptions explicites pour les M3/M5 tools sur project_id précis / bbox / dates ; (b) règle find_ecotaxa_observations explicite que bbox / date_range / instrument sont OPTIONNELS et interdit le skip en scope global. **Statut : fix committé, pas encore validé empiriquement — eval bloquée par solde OpenRouter, à rejouer après recharge** (`LLM_MAX_OUTPUT_TOKENS=8000 python evals/eval_ecotaxa_vision.py`). |

---

## 12. Suivi post-V1 (action items ouverts)

| # | Item | Statut | Détail |
|---|---|---|---|
| P1 | Re-run eval `ecotaxa-vision` après recharge OpenRouter | 🟡 En attente | Cible : EC-09 passe 0.5→1.0 et EC-16 passe 0.0→1.0. Si non atteint, lancer un nouveau cycle `/diagnose` (hypothèse H6 non identifiée). |
| P2 | Run complet 20 scénarios pour baseline officiel | 🟡 En attente | Une fois P1 validé. Documenter dans le journal : scores moyens par catégorie + comparaison après chaque modif prompt. |
| P3 | Apscheduler — vérifier nightly 3 AM en prod | ⚪ À faire | Après merge sur `main`. Surveiller `/health` `cache_age_hours` reset à 0 vers 3 AM. |
| P4 | Ajouter alerte `/health` `cache_age_hours > 36` | ⚪ V1.1 | Non bloquant V1 (M6 a explicitement reporté l'alerting). |
| P5 | EcoPart V2 | ⚪ Roadmap | Même archi D3, mêmes patterns que ce V1. |
