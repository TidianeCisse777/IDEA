# MCP EcoTaxa — Orchestration & Pistes D'amélioration

Ce document décrit comment les capacités du `MCP_CAPABILITIES.md` sont
aujourd'hui orchestrées dans les 4 couches du système (prompt, skills,
tools Python, MCP server), et identifie les leviers concrets pour
**mieux utiliser le MCP** dans l'agent copépode.

---

## 1. Les Quatre Couches

```
┌─────────────────────────────────────────────────────────────────────┐
│  Couche 1 — System prompt  (agents/copepod_system_prompt.py)        │
│  Toujours chargée. ~25 règles EcoTaxa. Décide QUI appeler quand.    │
└─────────────────────────────────────────────────────────────────────┘
                              │ load_skill("ecotaxa_navigation")
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Couche 2 — Skills markdown  (agents/skills/ecotaxa_*.md)           │
│  Chargés à la demande. ~670 lignes de règles détaillées.            │
│  Désengorge le prompt always-on.                                    │
└─────────────────────────────────────────────────────────────────────┘
                              │ @tool calls
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Couche 3 — Tools Python LangChain  (tools/copepod_sources.py)      │
│  19 tools EcoTaxa @tool exposés à l'agent. C'est ce que le LLM voit.│
│                                                                     │
│   ├── import direct ──► core/ecotaxa_browser/*  (cache + EcoTaxa)   │
│   └── HTTP  ──────────► api EcoTaxa via EcotaxaClient (exports)     │
└─────────────────────────────────────────────────────────────────────┘

                  ┌──────────────────────────────────────┐
                  │  Couche 4 — MCP server               │
                  │  core/mcp/ecotaxa_server.py          │
                  │  FastMCP HTTP sur port 8001          │
                  │  19 tools MCP exposés à l'EXTÉRIEUR  │
                  │  (Claude Desktop, Cursor, etc.)      │
                  │                                      │
                  │  ► aujourd'hui IDEA NE l'utilise PAS │
                  └──────────────────────────────────────┘
                              │
                              ▼
                  ┌──────────────────────────────────────┐
                  │  Noyau partagé                       │
                  │  core/ecotaxa_browser/*              │
                  │  Cache SQLite + API EcoTaxa          │
                  │  Importé par C3 ET par C4            │
                  └──────────────────────────────────────┘
```

### Rôle réel de chaque couche

| Couche | Rôle | Fichiers | Volume |
|---|---|---|---|
| **C1 — Prompt** | Routage minimal toujours visible. Aiguillage gros grain : "EcoTaxa exploration → load_skill", "summary → summarize_*", etc. Pas de détail métier. | `agents/copepod_system_prompt.py` | 43 mentions ecotaxa |
| **C2 — Skills** | Règles détaillées chargées à la demande. Logique de chaînage, ambiguïtés ("samples présents"), gestion EXPORT_FAILED, instrument vs nom de projet, etc. | `agents/skills/ecotaxa_navigation.md` (429 l), `ecotaxa_query.md` (110 l), `uvp_ecotaxa.md` (130 l) | 669 lignes |
| **C3 — Tools Python** | Surface réelle vue par le LLM. Wrappers `@tool` qui appellent soit `core/ecotaxa_browser/*` en direct (lecture/cache), soit `EcotaxaClient` HTTP (export). | `tools/copepod_sources.py` | 19 tools |
| **C4 — MCP server** | Façade HTTP FastMCP pour clients externes (Claude Desktop, Cursor). Tools en lecture seule, pas d'export. Cache partagé avec C3 via le noyau commun. | `core/mcp/ecotaxa_server.py` | 19 tools MCP |

### Le noyau partagé

`core/ecotaxa_browser/` contient la vraie logique : connexion EcoTaxa,
cache SQLite (`data/ecotaxa_cache.sqlite`), nightly sync (3h UTC par
défaut), pagination, résolution taxon, regions, observations.

C3 (tools LangChain) **et** C4 (MCP server) importent **les mêmes
fonctions** depuis `core/ecotaxa_browser/`. C'est la même logique
exposée par deux portes différentes.

---

## 2. Comment Une Demande Traverse Les Couches

Exemple : « Combien de Calanus glacialis validés dans les projets de la
Baie de Baffin en 2024 ? »

1. **C1 — Prompt** matche la règle « EcoTaxa read-only + zone nommée » →
   décide d'appeler `load_skill("ecotaxa_navigation")` d'abord.
2. **C2 — Skill** lu en contexte : règles de chaînage zone → projets →
   comptage, ambiguïtés (LOKI comme instrument, pas comme nom de projet),
   exemple typique « où + V/P ».
3. **C3 — Tools** : le LLM appelle
   `get_zone_info(zone_name="Baie de Baffin")` →
   `find_ecotaxa_observations(taxon="Calanus glacialis", bbox=...)` →
   `count_ecotaxa_taxa(project_ids=result["attested_projects"], taxa=["Calanus glacialis"])`.
4. **C4 — MCP** : **pas appelé**. C3 importe directement
   `core.ecotaxa_browser.observations.find_observations` et
   `core.ecotaxa_browser.taxa_stats.taxa_stats`. Le serveur MCP HTTP
   ignore tout de cette requête.

Côté cache : c'est la même SQLite (`data/ecotaxa_cache.sqlite`) que
remplit la nightly sync — il n'y a pas de duplication de données,
juste deux portes d'entrée vers le même noyau.

---

## 3. État Aujourd'hui — Constats

### Ce qui marche bien

- **Désengorgement du prompt** : la règle « load_skill first » réduit
  les ~430 lignes d'ecotaxa_navigation à 1 ligne dans le prompt
  always-on. Cohérent avec le pattern multi-skill du repo.
- **Découpage explicite read-only vs export** : C3 a `find_*`,
  `summarize_*`, `count_*`, `inspect_*`, `preview_*` (lecture) et
  `query_*`, `export_*` (téléchargement). Le routage prompt + skill
  pousse le LLM à préférer read-only — le README MCP renforce ça
  côté serveur (pas d'export exposé).
- **Cache local partagé** : C3 et C4 lisent la même SQLite. Un sync
  bénéficie aux deux.
- **Auth séparée** : MCP exige Bearer token (`MCP_AUTH_TOKEN`),
  EcoTaxa exige user/password ou token. Les surfaces externes sont
  protégées.

### Ce qui pose problème

| # | Constat | Impact |
|---|---|---|
| **P1** | **Le MCP server n'est pas consommé par IDEA lui-même.** Tous les `@tool` de C3 importent `core/ecotaxa_browser/*` en direct au lieu de passer par `localhost:8001/mcp`. | Le MCP devient une couche fantôme pour l'agent. Toute amélioration côté MCP (rate limiting, logs centralisés, métriques) ne profite pas à IDEA. Le README pourtant cible « IDEA itself ». |
| **P2** | **Duplication des wrappers** : 19 tools MCP + 19 `@tool` font sensiblement la même chose, avec naming inconsistant (`samples_in_region` vs `find_ecotaxa_samples_in_region`, `taxa_stats` vs `count_ecotaxa_taxa`, `compare_project_schemas` vs `compare_ecotaxa_projects`). | Maintenance double : un changement de signature dans le noyau impose de patcher deux façades. Risque de drift. |
| **P3** | **Tools MCP non exposés au LLM** : `search_taxa` (autocomplete), `taxonomy_node`, `list_sample_objects`, `get_object`, `list_project_acquisitions`, `get_acquisition`, `get_project` (basique). | Le LLM ne peut pas désambiguïser un nom de taxon via autocomplete avant un comptage — il appelle directement `count_ecotaxa_taxa` qui peut retourner `AMBIGUOUS_TAXON`. `search_taxa` côté MCP résoudrait. |
| **P4** | **`@tool` non exposés au MCP** : `preview_ecotaxa_project`, `list_ecotaxa_projects`, `summarize_ecotaxa_project` (singulier), `summarize_ecotaxa_sample` (singulier), `summarize_ecotaxa_sample_deployment`. | Un client externe (Claude Desktop) ne peut pas obtenir ce que l'agent IDEA propose. Asymétrie incohérente. |
| **P5** | **Routage prompt + skill se répète** : la section EcoTaxa du prompt (~25 règles) reprend en partie ce que le skill `ecotaxa_navigation` formalise. Une modification de routage demande de toucher les deux. | Drift possible entre prompt et skill (déjà observé dans le diff récent). |
| **P6** | **MCP server seul à avoir** un endpoint `/admin/resync` et un scheduler nightly visible. Le tool `@tool` n'expose aucun moyen de déclencher / vérifier la fraîcheur du cache. | Un utilisateur IDEA qui voit `CACHE_EMPTY` ne sait pas comment forcer un sync. L'agent non plus. |
| **P7** | **Le code de fallback EcoTaxa direct** dans `EcotaxaClient` ne passe ni par le cache ni par le MCP. Si l'API EcoTaxa est lente ou indisponible, le `query_ecotaxa` casse seul, alors que le MCP a déjà la logique de retry/cache. | Surface de panne séparée. |

---

## 4. Pistes Pour Mieux Utiliser Le MCP

Trois directions possibles, ordonnées par rapport impact / effort. Pas
de recommandation imposée — le choix dépend de combien on veut
rapprocher ou diverger les deux façades.

### Direction A — Garder l'agent en imports directs, enrichir le MCP pour les clients externes uniquement

**Effort** : faible. **Impact MCP côté agent** : nul.

- Aligner les noms (`@tool` reste préfixe `ecotaxa_*`, MCP garde ses
  noms compacts).
- Combler P4 : exposer côté MCP les `preview_*`, `summarize_<singulier>`,
  `summarize_sample_deployment` qui manquent.
- Documenter explicitement que l'agent IDEA n'utilise PAS le MCP HTTP
  en interne (corriger le README MCP).
- Ajouter au `@tool` une méthode `refresh_ecotaxa_cache` qui appelle
  `core/ecotaxa_browser/cache/sync.run_full_sync` directement, pour
  régler P6 sans dépendre du MCP.

> Avantage : le MCP devient un produit autonome pour Claude Desktop &
> co, IDEA reste rapide (pas de hop HTTP). Inconvénient : on continue
> à maintenir deux façades parallèles.

### Direction B — Router l'agent à travers le MCP HTTP pour les opérations read-only

**Effort** : moyen. **Impact MCP côté agent** : fort.

- Remplacer les imports directs de `core/ecotaxa_browser/*` dans
  `tools/copepod_sources.py` par des appels HTTP au MCP server local
  (`http://mcp-ecotaxa:8001/mcp` via Bearer interne).
- Les `query_*` (export) restent en `EcotaxaClient` direct, le MCP
  reste read-only conformément à son README.
- Les `@tool` deviennent des wrappers minces : authentification,
  formatage de la réponse en markdown français pour le LLM, et
  délégation au MCP.
- Avantages : métriques centralisées, rate-limiting, logs unifiés,
  un seul endroit pour patcher la logique. Tous les clients (IDEA +
  externes) voient le même comportement.
- Coûts : latence (un hop HTTP local ~5-20 ms), couplage runtime à
  `mcp-ecotaxa` (déjà UP dans le compose), surface d'erreur réseau
  à gérer côté `@tool`.

> Avantage : tout passe par une porte. Inconvénient : refonte de C3
> et tests de régression sur les ~25 règles de routage prompt+skill.

### Direction C — Fusion totale : un seul registre déclaratif

**Effort** : élevé. **Impact MCP côté agent** : maximal.

- Déclarer chaque tool une seule fois dans un registre Python
  (`core/ecotaxa_browser/registry.py`) avec ses paramètres, sa
  docstring française pour le LLM, son nom MCP, son nom `@tool`.
- Génération automatique :
  - des `@tool` LangChain à partir du registre,
  - des `@mcp.tool` FastMCP à partir du registre,
  - de la matrice de traçabilité capacité → tool.
- Avantages : zéro drift entre les façades, un seul endroit où ajouter
  un tool (ex. `search_taxa` apparaît automatiquement des deux côtés).
- Coûts : refactor important, complexité supplémentaire dans le
  registre, perte de la flexibilité d'avoir des signatures différentes
  entre @tool (français, descriptions LLM-friendly) et MCP (compact,
  schema-first).

---

## 4bis. Convention De Naming `@tool` (Source De Vérité)

Tant que la couche `@tool` (C3) reste la surface utilisée par l'agent
IDEA, c'est elle qui fait foi. Le serveur MCP (C4) suivra plus tard.

**Convention adoptée** pour tous les `@tool` EcoTaxa :

```
<verbe>_ecotaxa_<nom>
```

- **`<verbe>`** = `find` (recherche/locate), `list` (énumération
  complète), `preview` (échantillon léger), `inspect` (schéma/colonnes
  d'un objet), `summarize` (agrégats V/P/D/U), `count` (comptes
  taxon×projet), `compare` (diff entre projets), `search` (autocomplete),
  `get` (un objet par ID), `query` (export/téléchargement),
  `export` (téléchargement multi-projet).
- **`<nom>`** = l'entité ciblée : `project`, `projects`, `sample`,
  `samples`, `taxa`, `cache_status`, `column`, `project_schema`,
  `observations`, `sample_deployment`.
- Pour les variantes **régionales**, suffixer `_in_region` :
  `find_ecotaxa_samples_in_region`, `find_ecotaxa_projects_in_region`.

Côté MCP (C4) le naming est plus compact (`samples_in_region`,
`taxa_stats`, `compare_project_schemas`). Cet écart est documenté
mais pas corrigé tout de suite — pour mémoire la table des
correspondances actuelles est dans [`docs/TOOLS.md`](docs/TOOLS.md).

Quand on ajoutera un nouveau tool, on respecte la convention
`@tool` d'abord, puis on duplique avec un nom compact côté MCP si
besoin.

---

## 5. Petites Améliorations Indépendantes Du Choix Ci-dessus

Quelle que soit la direction, ces actions ont un ROI direct :

1. **Exposer `search_taxa` au LLM** comme `@tool`. C'est la pièce
   manquante pour résoudre `AMBIGUOUS_TAXON` proactivement. (P3)
2. **Exposer un `ecotaxa_cache_status` au LLM** qui appelle
   `core/ecotaxa_browser/cache/repo.latest_sync_status`. Permet au LLM
   de répondre clairement « cache vide, sync nécessaire » au lieu de
   l'erreur opaque actuelle. (P6)
3. **Aligner les naming patterns** : décider une convention (`<verbe>_ecotaxa_<nom>`
   ou `<nom>_<verbe>`) et l'appliquer aux deux façades.
4. **Mettre à jour le README MCP** pour clarifier explicitement qui
   consomme quoi (IDEA = imports directs, externes = HTTP). Tant
   qu'on n'a pas choisi entre direction A et B, dire la vérité.
5. **Test de parité** : un test pytest qui vérifie pour chaque
   capacité du `MCP_CAPABILITIES.md` qu'il existe au moins un tool
   MCP **et** un `@tool` qui la couvrent. Surface les écarts de P3/P4
   automatiquement.

---

## 6. Pour Aller Plus Loin

- Capacités utilisateur : [`MCP_CAPABILITIES.md`](MCP_CAPABILITIES.md)
- Spec d'enrichissement par lat/lon/temps :
  [`ENRICHMENT_CAPABILITIES.md`](ENRICHMENT_CAPABILITIES.md) +
  [`ENRICHMENT_QUICKSTART.md`](ENRICHMENT_QUICKSTART.md)
- Architecture globale : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Inventaire tools : [`docs/TOOLS.md`](docs/TOOLS.md)
- README MCP : [`core/mcp/README.md`](core/mcp/README.md)
