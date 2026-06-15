# MCP EcoTaxa — Use cases couverts (V1)

État du serveur MCP au 2026-06-15, branche `feat/mcp-ecotaxa`.

Document factuel : ce qui marche, ce qui marche avec friction, ce qui n'est pas couvert. Pour la doc technique complète : `core/mcp/README.md`. Pour le PRD : `docs/PRD_MCP_ECOTAXA.md`.

---

## 1. La promesse V1 — résumée en une phrase

> **Avant de télécharger** des données EcoTaxa avec `query_ecotaxa` (qui prend 5-10 min sur un projet de 100k objets), l'utilisateur peut **explorer en moins d'une seconde** ce qui est dispo, où, quand, avec quel schéma, à quel statut de validation, et si c'est compatible pour un merge.

---

## 2. Ce qui marche bien (validé en smoke test live)

Tous les tools ci-dessous ont été appelés contre l'API EcoTaxa réelle (`ecotaxa.obs-vlfr.fr`) avec le compte service IDEA. Réponses obtenues, parsées, et affichées par l'agent IDEA. **7 projets accessibles, 77 samples cachés.**

### 2.1. Découverte de projets

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Liste les projets EcoTaxa accessibles » | `list_ecotaxa_projects` | (legacy) | ✅ 7 projets retournés |
| « Cherche les projets contenant Calanus / UVP5 / Amundsen » | `find_ecotaxa_projects(title, instrument)` | `search_projects` | ✅ Filtres titre+instrument |
| « Fiche du projet 42 » | `preview_ecotaxa_project(42)` | `get_project(42)` | ✅ Metadata + stats |

### 2.2. Inspection du schéma (avant export)

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Quelles colonnes a le projet 42 ? » | `inspect_ecotaxa_project_schema(42)` | `get_project_schema(42)` | ✅ 3 niveaux sample/acq/object, types inférés (number/text/datetime) |
| « Y a-t-il une colonne profondeur ? » | idem (le LLM lit le retour) | idem | ✅ Le schéma expose `depth_min` / `depth_max` fixed + free fields |
| « Free fields avec codes internes » | `inspect_ecotaxa_project_schema(42, verbose=True)` | `get_project_schema(42, verbose=True)` | ✅ Codes `n01`, `t05` exposés |

### 2.3. Distribution d'une colonne (avant export)

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Plage de profondeur sur le projet 42 » | `inspect_ecotaxa_column(42, "depth_min")` | `get_column_distribution(42, "depth_min")` | ✅ `min=0.6, max=221, mean=158, p25=121, p75=210, n=1000` |
| « Distribution de la colonne area » | `inspect_ecotaxa_column(42, "area")` | `get_column_distribution(42, "area")` | ✅ free field `fre.area`, stats numériques |
| « Valeurs distinctes de classif_qual » | `inspect_ecotaxa_column(42, "classif_qual")` | `get_column_distribution(42, "classif_qual")` | ✅ `top_values: [{value: "V", count: 1000}]` |
| Colonne ambiguë (`orig_id` existe à 3 niveaux) | erreur `AMBIGUOUS_COLUMN` avec candidates | idem | ✅ L'agent peut rejouer avec `level=` explicite |

### 2.4. Comptage de taxons (sans téléchargement)

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Combien de Calanus finmarchicus validés dans le projet 42 ? » | `count_ecotaxa_taxa([42], ["Calanus finmarchicus"])` | `taxa_stats(...)` | ✅ V/P/D/total par (projet, taxon) |
| « Calanus glacialis sur projets 42 et 2331 » | `count_ecotaxa_taxa([42, 2331], ["Calanus glacialis"])` | idem | ✅ 1 ligne par (projet × taxon), inaccessibles skippés |
| Taxon ambigu (« Copepoda » → 66 candidats) | erreur `AMBIGUOUS_TAXON` avec candidates | idem | ✅ L'agent peut désambiguïser |
| Taxon par ID entier | `count_ecotaxa_taxa([42], [82431])` | idem | ✅ Pas de résolution string→int nécessaire |

### 2.5. Comparaison de projets (avant export combiné)

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Projets 42 et 14844 compatibles ? » | `compare_ecotaxa_projects([42, 14844])` | `compare_project_schemas([42, 14844])` | ✅ 102 colonnes communes, 0 conflit |
| « Conflits de schéma avant merge ? » | idem | idem | ✅ severity blocker/warning si conflit |
| « Colonnes uniques à chaque projet » | idem | idem | ✅ `unique_to_project` exposé |

### 2.6. Navigation drill-down catalogue

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Liste les samples du projet 42 » | (via tools natifs IDEA) | `list_project_samples(42)` | ✅ Pagination |
| « Fiche du sample 42000013 » | (via MCP direct) | `get_sample(42000013)` | ✅ Metadata sample |
| « Liste les acquisitions du projet 42 » | (via MCP direct) | `list_project_acquisitions(42)` | ✅ |
| « Objets du sample X » | (via MCP direct) | `list_sample_objects(sample_id)` | ✅ |
| « Objet avec contexte vertical » | (via MCP direct) | `get_object(object_id)` | ✅ Objet + sample + acquisition + projet inlinés |

### 2.7. Taxonomie

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Racines de la taxonomie EcoTaxa » | (via MCP direct) | `taxonomy_node()` | ✅ |
| « Sous Copepoda ? » | idem | `taxonomy_node(25828)` | ✅ |
| « Recherche taxon Calanus » | idem | `search_taxa("Calanus")` | ✅ 17 candidats |

### 2.8. Géographie + temporel cross-projets (cache SQLite)

| Question utilisateur | Tool LangChain (IDEA) | Tool MCP | Validation |
|---|---|---|---|
| « Samples en zone arctique ? » | `find_ecotaxa_samples_in_region(bbox)` | `samples_in_region(bbox)` | ✅ 77 samples filtrés en <1s |
| « Samples en 2015 ? » | `find_ecotaxa_samples_in_region(date_range)` | idem | ✅ 6 samples |
| « Quels projets en Hudson Bay ? » | `find_ecotaxa_projects_in_region(bbox)` | `projects_in_region(bbox)` | ✅ Agrégation par projet |
| « Où Calanus glacialis ? » | `find_ecotaxa_observations(taxon)` | `find_observations(taxon)` | ✅ Projets attestants + samples |
| Cache vide → erreur explicite `CACHE_EMPTY` | idem | idem | ✅ L'agent peut suggérer un resync |

---

## 3. Ce qui marche avec friction (à confirmer post-recharge OpenRouter)

L'eval `evals/eval_ecotaxa_vision.py` (4 scénarios sur 20 tournés) a identifié 2 cas où le routing du LLM était sous-optimal. **Fix prompt committé (`f2efb29`), validation empirique en attente** — voir §12 du PRD (P1).

| Cas | Symptôme observé | Statut |
|---|---|---|
| « Y a-t-il une colonne température dans le projet 42 ? » | LLM passait par RAG avant d'arriver au schema (1 step de trop) | Fix prompt committé, valide après recharge |
| « Où Calanus glacialis + ratio V/P » sans bbox | LLM skip `find_observations`, va direct à `count_taxa` | Fix prompt committé, valide après recharge |

**À noter** : sur les 4 scénarios tournés, la **promesse centrale du V1 est tenue** — le LLM n'utilise jamais `query_ecotaxa` (téléchargement coûteux) quand un tool d'exploration suffit (M3 forbidden_tool_absent = 100%).

---

## 4. Ce qui n'est pas couvert (hors scope V1, par choix)

| Capacité | Pourquoi pas en V1 |
|---|---|
| Export effectif des données | C'est `query_ecotaxa` (tool legacy IDEA, hors MCP). Le MCP sert à **décider d'exporter**, pas à exporter |
| Counts précis par sample (G2) | V1 est en G1 (project-level filter). Pour les vrais counts, chaîner sur `count_ecotaxa_taxa` |
| Images, URLs vault, mosaïques | Décision explicite : pas d'images en V1 |
| Écriture (annotation, classification) | MCP read-only strict |
| EcoPart | V2 |
| Multi-tenant per-user | Compte service partagé en V1 ; per-user en V1.1 si demande |
| Alerting cache stale | V1.1 (M6 a explicitement reporté) |

---

## 5. Limites naturelles à connaître

- **Le compte service IDEA voit 7 projets** : UVP5 GREEN EDGE 2015, LOKI copepod lipids, LOKI ArcticNet 2015, UVP6 Amundsen 2024 (4 legs). Toute question sur d'autres projets retourne vide — c'est correct, pas un bug.
- **Cache nightly à 3 AM UTC** : les samples créés/modifiés après le sync ne sont pas visibles avant le run suivant. Acceptable pour la balade ; admin peut forcer via `POST /admin/resync`.
- **Distribution des colonnes obj.free** : limitée à 1000 objets échantillonnés en fallback si `/project_set/column_stats` ne supporte pas la colonne (rare). Représentatif pour les distrib, pas exact pour les `n`.
- **Samples sans lat/lon** : droppés silencieusement à l'indexation (objets de cabine, calibration…). Cohérent.

---

## 6. Pour aller plus loin

- `core/mcp/README.md` — doc technique complète (auth, endpoints, payload formats, codes d'erreur)
- `docs/PRD_MCP_ECOTAXA.md` — PRD V1 avec décisions verrouillées, milestones, journal
- `docs/ARCHITECTURE.md` — câblage avec l'agent IDEA et le reste du runtime
- `docs/TOOLS.md` — inventaire des `@tool` LangChain côté agent IDEA
- `tests/test_ecotaxa_live.py` — assertions live qui verrouillent le contrat API EcoTaxa (taggé `@pytest.mark.live`, opt-in via `ECOTAXA_LIVE=1`)
