# PRD — MCP EcoTaxa (V1)

| Métadonnée | Valeur |
|---|---|
| Status | 🟡 Draft — En cours d'implémentation |
| Version | 0.1 |
| Branche | `feat/mcp-ecotaxa` |
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

### M0 — Setup (0,5 j) — Status : 🟡 Implémenté — baseline globale à réparer

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
- [ ] Pas de régression : `pytest tests/` complet reste vert

> Baseline au 2026-06-15 : la suite complète était déjà rouge avant M0
> (`188 passed`, `17 failed`, `40 errors`, `10 skipped`). Après M0 :
> `198 passed`, `17 failed`, `40 errors`, `10 skipped`. Aucun nouvel échec M0,
> mais le gate reste ouvert tant que la baseline globale n'est pas réparée.

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

### M2 — Catalogue navigation sans cache (3 j) — Status : 🟡 Implémenté — baseline globale à réparer

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
- [ ] Pas de régression `pytest tests/`

**Validation**
- Tests ciblés EcoTaxa/MCP : 28 passants.
- Docker : `/health` 200, MCP sans Bearer 401.
- Parcours MCP live : projet 42 → sample 42000013 → objet 4200030315 → acquisition 420000014.
- `get_project`, `taxonomy_node` et `search_taxa` validés contre l'API EcoTaxa réelle.
- Suite globale en worktree propre : 261 passants, 10 échecs, 10 ignorés. Les échecs restants concernent Bio-ORACLE, RAG et les métadonnées chat ; aucun test M2 n'échoue.

---

### M3 — Comptages & schéma (2 j) — Status : ⚪ Pas démarré

**Deliverables**
- `taxa_stats(project_ids, taxa_ids=None, status=None)` — counts agrégés
- `get_project_schema(project_id, verbose=False, include_process=False)` — niveau sample/acquisition/object avec free fields résolus en labels
- `get_column_distribution(project_id, column_name, exhaustive=False, sample_size=1000)` — numeric stats ou top-N
- `compare_project_schemas(project_ids)` — common / unique / type conflicts
- Helper interne : parser `mappingsample` / `mappingacq` / `mappingobj` pour résoudre `t01` → `station_name`

**Gates de validation**
- [ ] `get_project_schema` retourne 3 niveaux (sample/acquisition/object), pas 4 par défaut
- [ ] `get_column_distribution` numeric retourne `min/max/mean/median/p25/p75/n`
- [ ] `get_column_distribution` catégoriel retourne `top_N_values + counts + total_distinct`
- [ ] `compare_project_schemas` détecte un conflit de type (ex. `depth` numeric vs string entre projets)
- [ ] Tests + VCR pour chaque
- [ ] **V1 utilisable à partir d'ici** pour un utilisateur qui connaît son `project_id`

---

### M4 — Cache G2 (5–6 j) — Status : ⚪ Pas démarré

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
- [ ] Sync end-to-end sur ≥ 3 projets réels (`@pytest.mark.live`) réussit en < 5 min
- [ ] Sync idempotent : run 2× consécutifs → aucun doublon, `last_synced` mis à jour
- [ ] Samples sans lat/lon sont droppés (pas d'erreur, juste skip + log)
- [ ] `/health` reporte des chiffres réalistes après sync
- [ ] Crash du sync mid-run → état partial cohérent (pas de transaction half-committed)
- [ ] Test unit sync avec SQLite in-memory + cassettes EcoTaxa simulées passe
- [ ] Throttling : pas plus de 5 requêtes/sec vers EcoTaxa pendant sync

---

### M5 — UC1 + UC2 sur cache (2 j) — Status : ⚪ Pas démarré

**Deliverables**
- `samples_in_region(bbox=None, date_range=None, instrument=None, taxon=None)` — query SQLite
- `projects_in_region(bbox=None, date_range=None)` — agrégation au niveau projet depuis cache
- `find_observations(taxon, bbox=None, date_range=None, status="V")` — cache + `/project_set/taxo_stats`

**Gates de validation**
- [ ] `samples_in_region(bbox=[-70, 55, -55, 75])` répond en < 1s sur cache local 10k samples
- [ ] bbox math correcte : un sample à exactement la frontière est inclus (inclusif)
- [ ] `find_observations` avec bbox + taxon retourne uniquement les samples dans bbox **et** où le taxon est attesté
- [ ] Test fixture : cache seedée avec 50 samples connus, requête bbox St-Lawrence retourne le bon sous-ensemble
- [ ] Walk-through manuel : *« montre-moi les samples Calanus en Baie d'Hudson 2018–2022 »* résolu en une seule commande MCP

---

### M6 — Hardening & ship (1,5 j) — Status : ⚪ Pas démarré

**Deliverables**
- System prompt IDEA (`agents/copepod_system_prompt.py`) : nouvelle section décrivant **quand** utiliser les nouveaux tools d'exploration vs `query_ecotaxa` pour exporter
- `core/mcp/README.md` : auth, URL, exemples cURL, liste tools
- `docs/ARCHITECTURE.md` mis à jour avec le service `mcp-ecotaxa`
- `docs/TOOLS.md` mis à jour avec les nouveaux `@tool` IDEA
- Test live optionnel `tests/test_ecotaxa_live.py` (skippé sauf `ECOTAXA_LIVE=1`)
- PRD passe en status 🟢 Done

**Gates de validation**
- [ ] Un autre agent (Claude Code CLI ou cURL scripté) peut, en suivant le README seul, se connecter au MCP et naviguer EcoTaxa
- [ ] System prompt IDEA mis à jour : le LLM choisit le bon tool entre exploration et export sur 5 prompts test
- [ ] `pytest tests/` reste vert (≥ 42 tests verts pour ne pas régresser)
- [ ] Code review interne validée
- [ ] Merge sur `main` autorisé

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
