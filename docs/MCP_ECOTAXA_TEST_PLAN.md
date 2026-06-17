# MCP EcoTaxa — Plan de test manuel UI (V1)

| Métadonnée | Valeur |
|---|---|
| Lié à | [`PRD_MCP_ECOTAXA.md`](PRD_MCP_ECOTAXA.md) §12 (suivi post-V1) |
| Périmètre | Validation manuelle, via Open WebUI, des UC1/UC2 (géo + temporel + taxon) sur cache |
| Pré-requis | Agent `serve.py` sur `:8000`, cache peuplé (`data/ecotaxa_cache.sqlite`), Open WebUI sur `:3000` |
| Auteur | Tidiane (séance dirigée step-by-step) |
| Date | 2026-06-16 |

---

## 1. Objectif

Vérifier sur **un parcours utilisateur réel** (questions tapées dans Open WebUI) que les tools de navigation géo / temporel / taxon du MCP EcoTaxa :

1. Sont **bien sélectionnés par le LLM** (pas de RAG ni `query_ecotaxa` à la place)
2. Reçoivent des **paramètres correctement formés** (bbox, date_range, instrument)
3. Renvoient les **bons chiffres** par rapport à la vérité de référence (cache SQLite)

C'est un complément humain à `evals/eval_ecotaxa_vision.py` — orienté observation et diagnostic interactif, pas mesure automatisée.

---

## 2. Vérité de référence (snapshot du cache au 2026-06-16)

Extrait par requête directe sur `data/ecotaxa_cache.sqlite` :

| Filtre | Résultat attendu |
|---|---|
| Total | **77 samples / 6 projets** (42, 14622, 14844, 14853, 14859, 17498) |
| Année 2015 | **6 samples** (projets 42 + 14622) |
| Année 2024 | **71 samples** (projets 14844, 14853, 14859, 17498) |
| Instrument UVP6 | **71** ; UVP5SD : **5** ; Loki : **1** |
| Latitude > 70°N | **69** ; > 60°N : **77** |
| Lat/lon range | lat 67.27 → 82.40 ; lon -93.71 → -59.02 (tout en Arctique haut) |
| Hudson Bay / Méditerranée | **0** (légitime, hors périmètre compte service) |

> Note : ces chiffres reflètent le snapshot du 15 juin 2026. À re-extraire avant chaque séance si le cache a été resynchronisé (`POST /admin/resync` ou cron nightly 3 AM UTC).

Requête sqlite pour ré-extraire :

```bash
sqlite3 data/ecotaxa_cache.sqlite \
  "SELECT COUNT(*) AS samples, COUNT(DISTINCT project_id) AS projects FROM samples_cache;
   SELECT instrument, COUNT(*) FROM samples_cache GROUP BY instrument;
   SELECT MIN(lat_avg), MAX(lat_avg), MIN(lon_avg), MAX(lon_avg) FROM samples_cache;"
```

---

## 3. Règles de la séance

1. **Une question à la fois.** Tester un seul axe par gate avant de combiner.
2. **Rapport pour chaque gate :** (a) nombre dans la réponse, (b) tool(s) appelé(s) et combien de fois, (c) latence approximative.
3. **PASS / FAIL explicite** avant d'avancer. Pas de gate sauté.
4. **FAIL → diagnostic.** Cherche la cause avant de toucher au prompt (mismatch contrat tool ? cache stale ? bug routage prompt ?). Cf. `feedback_structural_over_prompt` dans la mémoire de l'agent.
5. **Si le LLM "explique" au lieu d'appeler un tool**, coupe et vérifie le system prompt avant de continuer.

---

## 4. Phase A — Cache géo / temporel / taxon

### Gate A1 — Axe seul : DATE

**Question à coller :**
> Liste les samples EcoTaxa collectés en 2015.

**Tool attendu :**
`find_ecotaxa_samples_in_region(date_range={"from":"2015-01-01","to":"2015-12-31"})`

**Attendu :** 6 samples, projets 42 + 14622

**PASS si :**
- ≥1 appel au bon tool avec `date_range` non vide
- Réponse cite 6 samples (ou décomposition 5+1)

**FAIL si :**
- Appelle `query_ecotaxa` (le coûteux)
- Passe par le RAG (`query_copepod_knowledge_base`)
- Retourne autre chose que 6

---

### Gate A2 — Axe seul : BBOX

**Question à coller :**
> Combien de samples EcoTaxa au-dessus de 70° de latitude nord ?

**Tool attendu :**
`find_ecotaxa_samples_in_region(bbox={"south":70, "west":-180, "north":90, "east":180})`

**Attendu :** 69 samples

**PASS si :**
- Bbox bien formée avec `south:70`
- Réponse = 69

**FAIL si :**
- Confusion lat/lon dans la bbox
- Bbox absurde (north < south, etc.)
- Résultat ≠ 69 (au-delà d'une erreur de borne explicable)

---

### Gate A3 — Axe seul : INSTRUMENT

**Question à coller :**
> Combien de samples UVP6 sont disponibles dans le cache EcoTaxa ?

**Tool attendu :**
`find_ecotaxa_samples_in_region(instrument="UVP6")`

**Attendu :** 71

**PASS si :**
- Réponse = 71
- Tool appelé avec `instrument="UVP6"` (string exacte, pas `uvp-6`, `UVP-6`, `uvp6`)

---

### Gate A4 — Combo 2 axes : DATE + BBOX

**Question à coller :**
> Quels samples EcoTaxa en 2024 au-dessus de 75°N ?

**Tool attendu :**
Un **seul** appel à `find_ecotaxa_samples_in_region` avec `bbox` + `date_range` simultanément.

**Attendu :** à calculer en live (sqlite) au moment du gate :
```bash
sqlite3 data/ecotaxa_cache.sqlite \
  "SELECT COUNT(*) FROM samples_cache
   WHERE lat_avg > 75 AND date_min >= '2024-01-01' AND date_min < '2025-01-01';"
```

**PASS si :**
- Un seul appel combinant les deux filtres
- Pas deux appels séparés que le LLM intersecte mentalement

---

### Gate A5 — Agrégation projet (tool différent)

**Question à coller :**
> Quels projets EcoTaxa ont collecté des données en 2024 ?

**Tool attendu :**
`find_ecotaxa_projects_in_region(date_range=...)` — **pas** `find_ecotaxa_samples_in_region`

**Attendu :** 4 projets (14844, 14853, 14859, 17498)

**PASS si :**
- Bon tool utilisé (projects, pas samples)
- Les 4 IDs de projet cités

---

### Gate A6 — Combo riche : GÉO + DATE + TAXON

**Question à coller :**
> Où a-t-on observé Calanus glacialis validé dans le cache EcoTaxa ?

**Tool attendu :**
`find_ecotaxa_observations(taxon="Calanus glacialis", status="V")`

**Attendu :** dépend des projets attestants (requiert un live call EcoTaxa au tool `taxo_stats`)

**PASS si :**
- Appelle `find_observations`
- Retourne projets attestants + samples
- Ne propose **pas** un export `query_ecotaxa`

---

## 5. Edge cases Phase A (optionnels, après les 6 principaux)

| Gate | Question | Attendu |
|---|---|---|
| E1 — Ambiguïté taxon | « Où a-t-on observé Copepoda ? » | Erreur `AMBIGUOUS_TAXON` avec liste de candidats. LLM redemande clarification. |
| E2 — Zone vide | « Samples EcoTaxa en Méditerranée » | `Aucun sample dans cette zone / période.` (légitime, pas un bug) |
| E3 — Cache stale | (forcer `cache_age_hours > 24`) | `/health` flag visible côté admin ; comportement utilisateur inchangé |
| E4 — Anti-régression no-download | « Combien de Calanus finmarchicus validés dans le projet 42 ? » | `count_ecotaxa_taxa` appelé, **pas** `query_ecotaxa` |

---

## 6. Phase B — Exploration catalogue avant export

Objectif : tester le parcours réel *« je fouille ce à quoi mon compte EcoTaxa donne accès avant de décider quoi exporter »*. Ces gates couvrent les UC catalogue, schéma, colonnes, compatibilité multi-projets, drill-down et anti-export.

Règle additionnelle Phase B : après chaque gate, vérifier les tool calls réels dans LangSmith avec :

```bash
.venv/bin/python /Users/tidianecisse/.codex/skills/langsmith-trace-audit/scripts/audit_langsmith_trace.py --thread-id <THREAD_ID> --limit 1
```

### Gate B1 — Inventaire des accès

**Question à coller :**
> Quels projets EcoTaxa sont accessibles avec le compte configuré ? Donne les IDs, titres, instruments et nombre d'objets si disponible.

**Tool attendu :**
`list_ecotaxa_projects`

**PASS si :**
- Appelle `list_ecotaxa_projects`
- Ne présente pas une liste hardcodée
- Cite les projets accessibles au compte configuré
- N'appelle pas `query_ecotaxa`

**FAIL si :**
- Passe par le RAG
- Cherche seulement un mot-clé avec `find_ecotaxa_projects`
- Appelle `query_ecotaxa`

---

### Gate B2 — Recherche orientée instrument

**Question à coller :**
> Quels projets UVP6 sont accessibles dans EcoTaxa ?

**Tool attendu :**
`find_ecotaxa_projects(instrument="UVP6")`

**PASS si :**
- Appelle `find_ecotaxa_projects` avec `instrument="UVP6"`
- Retourne les projets UVP6 accessibles
- N'appelle pas `query_ecotaxa`

---

### Gate B3 — Zone nommée au niveau projet

**Question à coller :**
> Quels projets EcoTaxa couvrent la baie de Baffin en 2024 ?

**Tools attendus :**
`get_zone_info(zone_name="baie de Baffin")` → `find_ecotaxa_projects_in_region(bbox=..., date_range=2024)`

**PASS si :**
- Commence par `get_zone_info`
- Utilise `find_ecotaxa_projects_in_region`, pas `find_ecotaxa_samples_in_region`
- Combine bbox + date_range dans l'appel projet
- N'appelle pas `query_ecotaxa`

---

### Gate B4 — Fouille taxon globale

**Question à coller :**
> Où trouve-t-on Calanus glacialis dans mes projets EcoTaxa accessibles ?

**Tool attendu :**
`find_ecotaxa_observations(taxon="Calanus glacialis", status="V")`

**PASS si :**
- Appelle `find_ecotaxa_observations`
- Ne transforme pas `Calanus` en recherche de titre de projet
- Retourne les projets/samples attestants
- N'appelle pas `query_ecotaxa`

**FAIL si :**
- Appelle seulement `find_ecotaxa_projects(title="Calanus")`
- Passe par le RAG

---

### Gate B5 — Question complexe exploratoire no-export

**Question à coller :**
> Je veux fouiller ce à quoi j'ai accès dans EcoTaxa pour préparer une analyse Calanus en Arctique. Trouve les projets pertinents, vérifie les périodes et zones couvertes, regarde si Calanus glacialis est attesté, puis recommande quels projets inspecter avant export. N'exporte rien.

**Tools attendus :**
Combinaison raisonnée de :
- `find_ecotaxa_projects_in_region` ou `find_ecotaxa_samples_in_region` pour la couverture arctique
- `find_ecotaxa_observations(taxon="Calanus glacialis")`
- éventuellement `count_ecotaxa_taxa` sur les projets attestants
- éventuellement `inspect_ecotaxa_project_schema` si l'agent recommande d'inspecter un projet précis

**PASS si :**
- Le taxon est traité par `find_ecotaxa_observations`, pas comme mot-clé de titre
- La zone Arctique est traitée par bbox/cache, pas par recherche de titre seulement
- La réponse recommande des projets candidats avec justification
- Aucun export n'est lancé

**FAIL si :**
- Appelle `query_ecotaxa`
- Appelle `load_skill("ecotaxa_query")`
- Se limite à `find_ecotaxa_projects(title="Calanus")` ou `title="Arctique"`

---

### Gate B6 — Inspection schéma avant export

**Question à coller :**
> Avant d'exporter le projet 14622, vérifie s'il contient latitude, longitude, date, profondeur et taxon validé.

**Tool attendu :**
`inspect_ecotaxa_project_schema(project_id=14622)`

**PASS si :**
- Appelle `inspect_ecotaxa_project_schema`
- Mentionne les niveaux pertinents (`sample`, `acquisition`, `object`)
- N'appelle pas `query_ecotaxa`

---

### Gate B7 — Distribution d'une colonne

**Question à coller :**
> Quelle est la plage de profondeur du projet 42 ?

**Tool attendu :**
`inspect_ecotaxa_column(project_id=42, column_name="depth_min" ou équivalent)`

**PASS si :**
- Appelle `inspect_ecotaxa_column`
- Retourne min/max ou indique clairement la colonne utilisée
- N'appelle pas `query_ecotaxa`

---

### Gate B8 — Colonne ambiguë et retry

**Question à coller :**
> Inspecte la colonne orig_id dans le projet 42.

**Tool attendu :**
`inspect_ecotaxa_column(project_id=42, column_name="orig_id")`, puis si `AMBIGUOUS_COLUMN`, retry avec `level=` explicite.

**PASS si :**
- Le premier appel expose ou gère l'ambiguïté
- L'agent relance avec un niveau candidat si nécessaire
- La réponse explique quel niveau a été inspecté

---

### Gate B9 — Compatibilité multi-projets

**Question à coller :**
> Compare les projets 14844, 14853, 14859 et 17498 avant un export combiné. Dis-moi les colonnes communes et les conflits bloquants s'il y en a.

**Tool attendu :**
`compare_ecotaxa_projects(project_ids=[14844, 14853, 14859, 17498])`

**PASS si :**
- Appelle `compare_ecotaxa_projects`
- Mentionne colonnes communes, conflits de type, conflits de niveau ou absence de conflit
- N'appelle pas `query_ecotaxa`

---

### Gate B10 — Drill-down sample EcoTaxa

**Question à coller :**
> Donne-moi les métadonnées complètes du sample EcoTaxa 42000002.

**Tool attendu :**
`get_ecotaxa_sample(sample_id=42000002)`

**PASS si :**
- Appelle `get_ecotaxa_sample`
- Ne confond pas avec EcoPart (`preview_ecopart_sample`)
- Retourne les métadonnées et free fields du sample

---

### Gate B11 — Comptage no-download

**Question à coller :**
> Combien de Calanus finmarchicus validés dans le projet 42 ?

**Tool attendu :**
`count_ecotaxa_taxa(project_ids=[42], taxa=["Calanus finmarchicus"])`

**PASS si :**
- Appelle `count_ecotaxa_taxa`
- Retourne V/P/D/total
- N'appelle pas `query_ecotaxa`

---

### Gate B12 — Follow-up contextuel

**Question à coller après une liste filtrée, par exemple Gate A4 ou B3 :**
> Il y en a combien ?

**Tool attendu :**
Réutilisation du contexte du filtre précédent ou nouvel appel au même tool avec les mêmes paramètres.

**PASS si :**
- Le nombre correspond au dernier filtre, pas au cache total
- N'appelle pas `run_pandas` sur un `df_ecotaxa` non lié au cache
- Ne relance pas un appel sans filtre `{}` 

**FAIL si :**
- Répond `77` après un filtre plus restreint
- Appelle `run_pandas` sur `df_ecotaxa`
- Appelle `find_ecotaxa_samples_in_region({})`

---

### Gate B13 — Spatial + temporel + taxon + recommandation no-export

**Question à coller :**
> Quels projets EcoTaxa accessibles couvrent la baie de Baffin entre 2015 et 2024, et parmi eux lesquels attestent Calanus glacialis validé ? Donne les périodes couvertes, le nombre de samples par projet, puis recommande quel projet inspecter avant export. N'exporte rien.

**Tools attendus :**
`get_zone_info(zone_name="baie de Baffin")` → `find_ecotaxa_projects_in_region(bbox=..., date_range=2015-2024)` → `find_ecotaxa_observations(taxon="Calanus glacialis", bbox=..., date_range=2015-2024, status="V")`

**PASS si :**
- Combine bien le filtre spatial et temporel dans les deux appels de recherche
- Utilise `find_ecotaxa_projects_in_region` pour l'agrégation projets
- Utilise `find_ecotaxa_observations` pour le taxon
- Recommande un ou plusieurs projets candidats avant export
- N'appelle ni `query_ecotaxa` ni `load_skill("ecotaxa_query")`

---

## 7. Journal Phase A — séance du 2026-06-16

| Gate | Date | Tool(s) appelé(s) | Latence | Nombre retourné | PASS / FAIL | Note |
|---|---|---|---|---|---|---|
| 1 | 2026-06-16 | `find_ecotaxa_samples_in_region` (date_range) | OK (bonne latence) | 6 samples | ✅ PASS | Routage direct, pas de RAG ni query_ecotaxa |
| 2 | 2026-06-16 | `find_ecotaxa_samples_in_region` (bbox south=70) | OK | 69 samples | ✅ PASS | Bbox bien formée, pas de confusion lat/lon |
| 3 | 2026-06-16 | `find_ecotaxa_samples_in_region` (instrument=UVP6) | OK | 71 (au 3e essai, puis du 1er essai après fix) | ⚠️ → ✅ PASS après fix | T1 → RAG ("I could not find..."), T2 → 77 (total, filtre perdu), T3 → 71. Bug racine : règle 25 RAG-first trop large ("data sources", "geographic zones"). **Fix structurel appliqué** : règle 25 refondue (knowledge vs data, examples explicites de routage), prompt push vers Hub. Re-test Gate 3 → 71 du 1er essai. |
| 4 | 2026-06-16 | `find_ecotaxa_samples_in_region` (bbox + date_range) | OK sur question complète | 59 samples (projets 14859 + 17498) | ⚠️ PASS conditionnel | Question initiale "Quels samples..." → table correcte. **Follow-up "yen a combien ?" → "77" (filtre perdu)**. Re-formulé complet → "59 samples". Bug : le LLM ne réutilise pas le contexte du tool précédent, refait un appel sans paramètres. À investiguer : tool result truncation ? prompt qui n'incite pas à raisonner sur le contexte ? |
| 5 | 2026-06-16 | `find_ecotaxa_projects_in_region` (date_range 2024) | OK | 4 projets (14844, 14853, 14859, 17498) | ✅ PASS | Bon switch projects vs samples, agrégation au bon niveau |
| 6 | 2026-06-16 | `find_ecotaxa_observations` (Calanus glacialis, status=V) | OK | 1 sample (projet 14622, LOKI ArcticNet 2015) | ✅ PASS | Bon tool, pas de proposition `query_ecotaxa` (anti-régression OK). UX : LLM ne verbalise pas "projets attestants" mais l'info est dans la colonne `projet`. À améliorer côté skill `data_explorer` si on veut un message + riche. |
| 7 | 2026-06-16 | `get_zone_filter` → `find_ecotaxa_samples_in_region` (bbox) | OK | 70 samples | ✅ PASS clean | Chaîne 2 tools parfaite sur question utilisateur naturelle "baie de Baffin". Pas de fuite RAG, pas d'invention de bbox. Le path "zone nommée → bbox → cache" est solide. |
| 8 | 2026-06-16 | `get_zone_filter` → `find_ecotaxa_samples_in_region` (bbox + date 2024) | OK | 64 samples | ✅ PASS | Combo zone + date — la chaîne 2 tools fonctionne avec date_range ajouté. C'est le cas utilisateur le plus réaliste. |
| 9 | 2026-06-16 | `find_ecotaxa_samples_in_region` (date_range avril 2015) | OK | 2 samples | ✅ PASS | LLM traduit correctement "avril 2015" en `from:2015-04-01, to:2015-04-30`. Bonne robustesse au phrasing FR. |
| 10 | 2026-06-16 | 2× `get_zone_filter` + 2× `find_ecotaxa_samples_in_region` | OK | Baffin 70, Beaufort 0 (tableau comparatif) | ✅ PASS | Workflow multi-tools 4 appels enchaîné proprement, rendu en tableau. Gap UX mineur : le LLM ne contextualise pas le 0 (pas de mention "hors compte service"). |
| 11 | 2026-06-16 | `find_ecotaxa_samples_in_region()` sans param + comptage manuel | OK | 6 (au 2e essai) | ⚠️ → ✅ PASS après fix | Run #1 → hallucination `df_ecotaxa`. Run #2 → dump 77 + comptage manuel = 6. **Bug B fixé structurellement** : garde-fou ajouté aux wrappers `find_ecotaxa_samples_in_region` et `find_ecotaxa_projects_in_region` (erreur si tous filtres None). 2 tests TDD verts. Re-test → LLM enchaîne 2 appels filtrés explicites → 6. |
| E1 | 2026-06-16 | `find_ecotaxa_observations` (Copepoda) → AMBIGUOUS_TAXON → liste candidats | OK | Liste candidats propre | ⚠️ → ✅ PASS après 2e fix | T1 → "I could not find this information in the knowledge base" (fuite RAG sur taxon+où). **2e fix structurel** : règle 25 passée à routage par VERBE (où/combien/liste → data ; qu'est-ce que/explique → KB) + garde-fou explicite "ne PAS fallback KB sur AMBIGUOUS_TAXON". Hub push `ef6e9e8d`. Retry → candidats list propre. |
| E2 | 2026-06-16 | `find_ecotaxa_samples_in_region` (bbox Méditerranée) | OK | "aucun sample en méditerranée" | ✅ PASS | Réponse honnête sur zone hors périmètre compte service. Pas d'hallucination, pas de fuite RAG. |
| E3 | | | | | | |
| E4 | 2026-06-16 | `count_ecotaxa_taxa` (projet 42, Calanus finmarchicus) | OK | 0/0/0/0 (V/P/D/total) | ✅ PASS clean | Anti-régression critique V1 validée : **pas d'appel `query_ecotaxa`** pour un comptage. Réponse factuelle : projet 42 n'a pas de *Calanus finmarchicus* annoté (UVP5 GREEN EDGE 2015, autres taxons). |

---

## 8. Journal Phase B — exploration catalogue avant export

| Gate | Date | Question courte | Tool(s) appelé(s) LangSmith | Latence | Résultat | PASS / FAIL | Note |
|---|---|---|---|---|---|---|---|
| B1 | 2026-06-16 | Inventaire accès | `list_ecotaxa_projects` | OK | 7 projets listés (IDs + noms) | ✅ PASS | Routage correct : pas de RAG, pas de `query_ecotaxa`. Réponse minimale : instruments / nb objets non affichés dans ce rendu. |
| B2 | 2026-06-16 | Projets UVP6 | `find_ecotaxa_projects(instrument="UVP6")` | OK | 4 projets UVP6 | ✅ PASS | Routage exact : filtre instrument conservé, pas de RAG, pas de `query_ecotaxa`. |
| B3 | 2026-06-16 | Projets Baffin 2024 | Aucun tool sur le run LangSmith | OK | Réponse plausible avec projets agrégés | ⚠️ FAIL routage | LangSmith montre `TOOLS: NONE`. Le résultat peut venir du contexte précédent, mais le gate exigeait `get_zone_filter` → `find_ecotaxa_projects_in_region`. À retester avec formulation qui force le recalcul. |
| B4 | 2026-06-16 | Calanus glacialis global | `find_ecotaxa_observations(taxon="Calanus glacialis", status="V")` | OK | 1 sample projet 14622 | ✅ PASS | Routage taxon correct : pas de recherche titre `Calanus`, pas de RAG, pas de `query_ecotaxa`. |
| B5 | 2026-06-16 | Fouille Calanus Arctique no-export | `get_zone_filter` → `find_ecotaxa_projects_in_region` → `find_ecotaxa_observations` | OK | Projets arctiques + attestation Calanus glacialis | ✅ PASS | Corrige le mauvais routage précédent : taxon traité par observation, zone traitée par bbox/cache, aucun `load_skill("ecotaxa_query")`, aucun `query_ecotaxa`. Note : bbox large `south=65`, période 2015-2024 ; pas de `count_ecotaxa_taxa` additionnel, acceptable pour ce gate. |
| B6 | | Schéma projet 14622 | | | | | |
| B7 | | Plage profondeur projet 42 | | | | | |
| B8 | | Colonne orig_id ambiguë | | | | | |
| B9 | | Compatibilité projets 2024 | | | | | |
| B10 | | Sample EcoTaxa 42000002 | | | | | |
| B11 | | Count no-download projet 42 | | | | | |
| B12 | | Follow-up "combien ?" | | | | | |
| B13 | 2026-06-16 | Baffin 2015-2024 + Calanus glacialis | `get_zone_filter` → `find_ecotaxa_projects_in_region` → `find_ecotaxa_observations` | OK | Projets Baffin 2015-2024 + attestation Calanus glacialis | ✅ PASS | Très bon routage : bbox baie de Baffin conservée, période 2015-2024 conservée, taxon traité via observation, aucun export. C'est le scénario le plus démonstratif pour superviseurs. |

---

## 9. Diagnostic en cas de FAIL

| Symptôme observé | Hypothèse | Action |
|---|---|---|
| LLM appelle RAG avant le tool MCP | Routage prompt sous-optimal | Voir §4 `agents/copepod_system_prompt.py` (M3/M5 routing rules) |
| LLM appelle `query_ecotaxa` direct | Le tool MCP n'est pas dans le contexte (skill manquant ?) ou le prompt ne décourage pas l'export prématuré | Vérifier `tools/copepod_sources.py` import + skill `data_explorer` |
| Tool retourne `CACHE_EMPTY` | Cache vide ou mauvais chemin | `ls -la data/ecotaxa_cache.sqlite` + `sqlite3 ... "SELECT COUNT(*) FROM samples_cache;"` |
| Tool retourne `AMBIGUOUS_TAXON` non géré par LLM | LLM ne lit pas la liste `candidates` | Vérifier docstring du tool + skill `data_explorer` |
| Bbox mal formée (lat/lon inversées) | Prompt insuffisant sur le format `{south, west, north, east}` | Renforcer docstring du tool, **pas** le system prompt (cf. feedback memory) |
| Latence > 5s sur un appel cache | Cache pas trouvé → fallback live API ? | Tracer dans LangSmith le tool input + temps réel |
| Question exploratoire complexe appelle `load_skill("ecotaxa_query")` | Le LLM associe "analyse/export" au skill post-export malgré "N'exporte rien" | Renforcer la règle no-export et vérifier avec `langsmith-trace-audit` |
| Taxon traité comme mot-clé de projet | Routage confond catalogue title search et observation taxonomique | Prioriser `find_ecotaxa_observations` pour "où trouve-t-on TAXON" |
| Sample EcoTaxa envoyé vers EcoPart | Ambiguïté "sample" entre domaines | Renforcer docstring/routing : "sample EcoTaxa" → `get_ecotaxa_sample` |
| Follow-up perd le filtre précédent | Le résultat tool précédent n'est pas réutilisé ou a été tronqué | Refaire le même tool call avec les mêmes paramètres ; éviter `run_pandas` sur `df_ecotaxa` |

---

## 10. Référence

- `docs/PRD_MCP_ECOTAXA.md` — PRD complet (§12 = post-V1 action items)
- `docs/MCP_ECOTAXA_USE_CASES.md` — UC factuels couverts en V1
- `core/mcp/README.md` — doc technique MCP (endpoints, auth, codes d'erreur)
- `tools/copepod_sources.py` — implémentation des `@tool` LangChain côté agent
- `core/ecotaxa_browser/region.py` — accès SQLite (samples_in_region, projects_in_region)
- `core/ecotaxa_browser/observations.py` — find_observations
- `evals/eval_ecotaxa_vision.py` — eval automatisée (complément aux gates manuels ci-dessus)
- `$langsmith-trace-audit` — skill locale pour extraire rapidement les tool calls LangSmith
