# GATE UI — Migration `get_zone_filter` → `get_zone_info` (polygones IHO)

**But** : valider end-to-end dans OpenWebUI que la nouvelle chaîne (zone nommée → polygone précis IHO/NeoLab → tool aval) fonctionne, et que les anciens patterns bbox-only ne fuitent plus dans le LLM.

**Branche** : `feat/zones-polygones-iho`
**Commit** : `0cb841a feat(geo): replace bbox-based zone filter with IHO polygon registry`

## Procédure

1. **Démarrer le service** : `docker compose up -d` à la racine du repo. Vérifier Open WebUI accessible sur `http://localhost:3000` et le backend agent sur `http://localhost:8000`.
2. **Coller la question d'un gate à la fois**, dans une **nouvelle conversation** pour chaque gate (afin que le contexte n'aide pas le LLM à deviner).
3. **Noter le `thread_id`** de la conversation (visible dans l'URL Open WebUI ou dans `logs/conversations/`).
4. **Demander à Claude** : "audit le gate N, thread_id=`...`". Claude lance la skill `langsmith-trace-audit` :
   ```bash
   .venv/bin/python /Users/tidianecisse/.codex/skills/langsmith-trace-audit/scripts/audit_langsmith_trace.py --thread-id <THREAD_ID>
   ```
5. Verdict consigné dans la colonne **Résultat** du tableau de chaque gate.
6. Si **PASS**, on passe au gate suivant. Si **FAIL**, on diagnostique avant d'enchaîner.

---

## Gate 1 — Chaîne EcoTaxa de base : zone → samples

### Question à coller

> Liste les samples EcoTaxa en Baie d'Ungava en 2020

### Tools attendus

```
get_zone_info(zone_name="Baie d'Ungava")
  → find_ecotaxa_samples_in_region(bbox=..., date_range={from:"2020-01-01", to:"2020-12-31"})
```

### PASS si

- [ ] Le **premier** appel est `get_zone_info` (pas `get_zone_filter` — ce nom doit avoir disparu).
- [ ] Le second appel est `find_ecotaxa_samples_in_region`.
- [ ] L'argument `bbox` passé à `find_ecotaxa_samples_in_region` contient bien les clés `{south, west, north, east}` (pas `lat_min/lat_max/lon_min/lon_max`).
- [ ] Les valeurs `bbox` correspondent à l'enveloppe d'Ungava (south ≈ 55.8, north ≈ 61.4, west ≈ -72, east ≈ -64.4).
- [ ] La période 2020 est conservée dans `date_range`.
- [ ] Aucun appel à `query_copepod_knowledge_base` en amont (les bboxes de la RAG ont été purgées, le LLM ne doit pas avoir besoin de demander).

### FAIL connu à surveiller

- Le LLM appelle encore `get_zone_filter` → tool n'existe plus, erreur silencieuse possible (fallback hallucination).
- Le LLM construit `bbox` à partir de coordonnées hardcodées → fuite RAG non purgée.

### Résultat

| Date | Thread ID | Verdict | Notes |
|---|---|---|---|
| 2026-06-17 | `d82ab3aac3824253` | ✅ PASS clean | Chaîne nominale : `get_zone_info(Baie d'Ungava)` → `find_ecotaxa_samples_in_region(bbox={south:55.8449, west:-72.0538, north:61.3945, east:-64.4442}, date_range=2020)`. Tableau vide retourné — résultat légitime, pas de samples Ungava 2020 dans le cache local. Aucun appel `get_zone_filter`, aucun bbox hardcodé. |

---

## Gate 2 — Bio-ORACLE par zones (migration `bbox.south/west/...` lecture)

### Question à coller

> Donne-moi la température Bio-ORACLE en Baie d'Ungava et à Hawke Channel sous le scénario SSP5-8.5

### Tools attendus

```
query_bio_oracle_zones(
  zones=["Baie d'Ungava", "Hawke Channel"],
  variable="temperature",
  scenario="SSP5-8.5",
  depth_layer="surface"
)
```

Le tool en interne appelle `get_zone_info` pour chaque zone et lit `bbox.south/north/west/east` (code migré dans `tools/bio_oracle_sources.py`).

### PASS si

- [ ] Appel **direct** à `query_bio_oracle_zones` avec les 2 zones.
- [ ] **Pas** d'appel manuel à `get_zone_info` ni `preview_bio_oracle_point` en amont (le tool zone le fait en interne).
- [ ] La réponse contient une valeur de température pour Baie d'Ungava ET Hawke Channel.
- [ ] Pas de traceback Python type `KeyError: 'lat_min'` (signe que `bio_oracle_sources.py` n'aurait pas été migré).
- [ ] Les coordonnées de centre rapportées (`lat_centre`, `lon_centre`) pour Ungava sont cohérentes (~58-59°N, -68°W).

### FAIL connu à surveiller

- Tool retourne `{"errors": ["Baie d'Ungava: ..."]}` pour toutes les zones → mauvaise lecture de bbox.
- Le LLM substitue une autre tool (`couple_zooplankton_bio_oracle`) sans qu'il y ait de table chargée.

### Résultat

| Date | Thread ID | Verdict | Notes |
|---|---|---|---|
| 2026-06-17 | `d82ab3aac3824253` (turn 2) | ✅ PASS avec réserve | `query_bio_oracle_zones` correctement appelé, retourne Baie d'Ungava=5.14°C / Hawke Channel=5.72°C (SSP5-8.5, surface — plausible). Migration `bbox.south/west/...` validée (pas de KeyError). **Réserve** : 4 appels redondants `get_zone_info` (2 avant + 2 après), parce que le system prompt impose `get_zone_info` en premier — alors que `query_bio_oracle_zones` résout les noms en interne. Action prompt fix optionnelle : ajouter une exception au mandat `get_zone_info` quand le tool aval prend des noms de zone (`query_bio_oracle_zones`). Pas bloquant. |

---

## Gate 3 — Précision polygone : Ungava vs Détroit d'Hudson

### Question à coller

> Quels samples EcoTaxa sont dans la Baie d'Ungava précisément — exclure ceux qui seraient dans le Détroit d'Hudson juste à côté. Période 2018-2022.

### Tools attendus

```
get_zone_info(zone_name="Baie d'Ungava")
  → find_ecotaxa_samples_in_region(bbox=..., date_range=2018-2022)
  → run_pandas(code utilisant shapely.wkt.loads(polygon_wkt) + contains pour post-filtrer)
```

### PASS si

- [ ] `get_zone_info` est appelé.
- [ ] `find_ecotaxa_samples_in_region` est appelé avec le bbox d'Ungava (pré-filtre).
- [ ] Un appel `run_pandas` est fait après, **utilisant `polygon_wkt`** dans son code (mot-clé `polygon_wkt` ou `wkt.loads` ou `.contains(` dans l'arg `code`).
- [ ] La réponse mentionne explicitement la différence entre les counts avant/après filtre polygone (preuve que le filtre a réellement été appliqué).
- [ ] **Aucun sample situé clairement dans le Détroit (lat > 61°N et lon < -68°W) ne reste dans le résultat final**.

### FAIL connu à surveiller

- Le LLM ne fait que le filtre bbox et prétend que c'est "suffisamment précis" — c'est exactement le bug qu'on a corrigé, doit être absent.
- Le LLM utilise un polygone hardcodé au lieu du `polygon_wkt` retourné.
- Le LLM ne sait pas que `shapely` est disponible dans `run_pandas` — vérifier si c'est le cas (`tools/data_tools.py`), ajuster le prompt si besoin.

### Résultat

| Date | Thread ID | Verdict | Notes |
|---|---|---|---|
| 2026-06-17 | `d82ab3aac3824253` (turn 3) | ⚠ INCONCLUSIVE | Ungava 2018-2022 = 0 sample dans cache local → agent a court-circuité avant le run_pandas polygone. Logique défendable mais le critère central (polygon precision) non démontrable sur cette zone. **Retry suivant avec Baie de Baffin** (cache : 63 in bbox, 61 in polygon, 2 exclus en Lancaster Sound). |
| 2026-06-17 | `d82ab3aac3824253` (turn 4) | ⚠ INCONCLUSIVE | Baffin retry sans période explicite → LLM a inféré `date_range=2018-2022` (cohérence implicite avec turn 3, pas un default du tool). Or aucun sample Baffin du cache n'est en 2018-2022 → 0. Agent a infère "0→0" sans `run_pandas`. |
| 2026-06-17 | `d82ab3aac3824253` (turn 5) | ⚠ PASS routing / FAIL architectural | **Le gate critique.** Agent fait la chaîne attendue : `get_zone_info` → `find_ecotaxa_samples_in_region(bbox=Baffin, 2024)` → `run_pandas` avec `from shapely import wkt` + polygon WKT complet copié-collé. Mais `run_pandas` ne trouve aucun `df_ecotaxa` à filtrer parce que `find_ecotaxa_samples_in_region` renvoie ses résultats **comme texte au LLM**, pas comme DataFrame en session. L'agent l'a honnêtement reporté à l'utilisateur. **Conclusion** : le routing LLM est correct, le filtrage polygone end-to-end requiert Slice 2 (task #6) — ajouter un paramètre `polygon_wkt` à `find_ecotaxa_samples_in_region` pour que le filtre se fasse côté tool (SQLite ou shapely post-traitement) plutôt que côté agent. |

## Bilan final GATE UI Slice 1

- **Gate 1** ✅ PASS — chaîne basique migrée, nouveau nom de tool + shape bbox OK
- **Gate 2** ✅ PASS avec réserve — Bio-ORACLE zones migré, redondance `get_zone_info` côté prompt à corriger plus tard
- **Gate 3** ⚠ PASS routing / FAIL architectural — prouve la nécessité de Slice 2 (param `polygon_wkt` côté tool)
- **Gate 4** non testé (optionnel)

Slice 1 = **validé côté migration tool + prompt + RAG**. La promesse de précision polygone end-to-end requiert Slice 2.

---

# GATE UI — Slice 2 : post-filter polygone côté tool

**But** : valider que `find_ecotaxa_samples_in_region` (et frères) accepte maintenant `polygon_wkt` et fait le filtrage IN-polygon côté tool — plus besoin de `run_pandas` côté agent. Ferme la promesse du grilling : précision station-niveau réellement utilisable depuis OpenWebUI.

## Vérité terrain (cache local au 2026-06-17)

Mesure faite directement via `samples_in_region(...)` après migration :

```
Baffin bbox-only   : 63 samples
Baffin polygon WKT : 61 samples
Exclus par polygone (2) :
  sample_id=17498000006  project=17498  (73.74°N, -78.63°W)  Lancaster Sound
  sample_id=17498000017  project=17498  (73.74°N, -78.63°W)  Lancaster Sound
```

## Procédure

Même que Slice 1 : `docker compose up -d` (ou serve local) → coller la question dans une **nouvelle conversation** → me passer le `thread_id` → audit via skill `langsmith-trace-audit`.

---

## Gate S2-1 — Précision Baffin (LE test critique)

### Question à coller

> Quels samples EcoTaxa sont strictement dans la Baie de Baffin sur 2024 — exclure ceux qui seraient dans des passages voisins (Lancaster Sound, Northwest Passages). Donne-moi le décompte avant filtre polygone vs après, et la liste des sample_id exclus.

### Tools attendus

```
get_zone_info(zone_name="Baie de Baffin")
  → find_ecotaxa_samples_in_region(date_range=2024)       # bbox-only, baseline
  → find_ecotaxa_samples_in_region(polygon_wkt=...,        # polygon-strict
                                    date_range=2024)
```

OU une seule call avec les deux params, comparée mentalement par l'agent — peu importe la stratégie tant que les deux counts sont rapportés.

### PASS si

- [ ] L'appel `find_ecotaxa_samples_in_region` reçoit `polygon_wkt` (le param Slice 2)
- [ ] **PAS** de `run_pandas` avec `shapely.wkt.loads(...)` côté agent (Slice 2 rend ça inutile)
- [ ] La réponse mentionne explicitement « 27 → 25 » (ou les valeurs équivalentes pour 2024)
- [ ] La liste des 2 sample_id exclus est citée (17498000006, 17498000017) ou au minimum leur localisation Lancaster Sound

### FAIL connu à surveiller

- L'agent tente la stratégie pre-Slice 2 (`run_pandas` + WKT) → soit le prompt n'a pas été pushé sur LangSmith Hub (vérifier `push_prompt.py`), soit le LLM ignore la nouvelle règle
- L'agent ne fait qu'une seule call et invente un count "exclus = 2" sans preuve → demander le détail des sample_id

### Résultat

| Date | Thread ID | Verdict | Notes |
|---|---|---|---|
| — | — | — | — |

---

## Gate S2-2 — Projets agrégés avec polygone

### Question à coller

> Quels projets EcoTaxa ont des samples strictement dans la Baie de Baffin en 2024 ? Compare le décompte par projet avant et après filtre polygone précis.

### Tools attendus

```
get_zone_info(zone_name="Baie de Baffin")
  → find_ecotaxa_projects_in_region(date_range=2024)
  → find_ecotaxa_projects_in_region(polygon_wkt=..., date_range=2024)
```

### PASS si

- [ ] `find_ecotaxa_projects_in_region` est appelé avec `polygon_wkt`
- [ ] La réponse montre la différence par projet. D'après vérité terrain : projet `17498` doit passer de N à (N-2) — les autres projets ne changent pas (les 2 exclus sont tous deux dans 17498)

### Résultat

| Date | Thread ID | Verdict | Notes |
|---|---|---|---|
| — | — | — | — |

---

## Gate S2-3 — Mot-clé absent : pas de polygone si pas demandé

### Question à coller

> Liste les samples EcoTaxa en Baie de Baffin en 2024.

### Tools attendus

```
get_zone_info(zone_name="Baie de Baffin")
  → find_ecotaxa_samples_in_region(bbox=..., date_range=2024)   # bbox-only
```

### PASS si

- [ ] **AUCUN** `polygon_wkt` passé : la règle Slice 2 ne s'applique que sur les mots-clés de précision ("strictement", "exclure", "précis", etc.)
- [ ] Le résultat est exactement le bbox-only (27 samples Baffin 2024)
- [ ] L'agent n'invente pas une exclusion qu'on n'a pas demandée

### Résultat

| Date | Thread ID | Verdict | Notes |
|---|---|---|---|
| — | — | — | — |

---

## Note avant lancement

Avant de tester en UI, **pousser le system prompt mis à jour vers LangSmith Hub** :

```bash
python push_prompt.py
```

Sinon le LLM en prod continue de tirer l'ancien prompt sans la règle « Precision query EcoTaxa by polygon » et le Gate S2-1 va échouer pour cette raison-là, pas pour un bug Slice 2.

### Vérité terrain pour Gate 3 retry (Baie de Baffin)

Mesuré sur le cache EcoTaxa local au 2026-06-17 :

- bbox Baffin : **63 samples**
- polygon Baffin : **61 samples**
- 2 samples exclus (bbox-only, hors polygone IHO) :
  - `17498000006` (73.74°N, -78.63°W) 2024-09-27 — Lancaster Sound
  - `17498000017` (73.74°N, -78.63°W) 2024-09-27 — Lancaster Sound

### Observation hors-gate — zone "Arctique" trop étroite

Sur les mêmes 77 samples cache, la zone composite "Arctique" (Arctic Ocean basin + Beaufort + Chukchi + Lincoln + Groenland) renvoie **77 in bbox, 0 in polygon**. Géographiquement cohérent (Baffin Bay n'est pas dans le composite), mais ne matche pas l'attente intuitive d'un utilisateur qui dit "Arctique". À raffiner ultérieurement (élargir Arctique pour inclure Baffin/Davis/Hudson, ou ajouter une zone "Arctique canadien" plus large).

---

## Gate 4 — Alias / robustesse (optionnel, après les 3 premiers)

### Question à coller

> Combien de projets EcoTaxa couvrent Hudson Bay entre 2015 et 2024 ?

### Tools attendus

```
get_zone_info(zone_name="Hudson Bay")    # alias anglais → canonique "Baie d'Hudson"
  → find_ecotaxa_projects_in_region(bbox=..., date_range=2015-2024)
```

### PASS si

- [ ] Le tool résout l'alias anglais "Hudson Bay" vers le canonique "Baie d'Hudson".
- [ ] **Pas** d'erreur `"error": "Zone 'Hudson Bay' not recognised"`.
- [ ] La bbox correspond à Hudson Bay (sans James, séparé par le cut Cap Henrietta Maria → Pointe Louis-XIV : south ≈ 55, pas 51).
- [ ] `find_ecotaxa_projects_in_region` appelé (pas `_samples_`).

### Résultat

| Date | Thread ID | Verdict | Notes |
|---|---|---|---|
| — | — | — | — |

---

## Annexe — commande d'audit Claude

Pour chaque gate, après avoir collé la question dans Open WebUI :

```
Audit le gate N, thread_id=<COPIER_DEPUIS_OPEN_WEBUI>
```

Claude utilise alors la skill `langsmith-trace-audit` :

```bash
.venv/bin/python /Users/tidianecisse/.codex/skills/langsmith-trace-audit/scripts/audit_langsmith_trace.py --thread-id <THREAD_ID>
```

et reporte :
- **Verdict** : PASS clean / PASS avec réserve / FAIL routage / FAIL régression
- **Bons appels** : nom du tool + args clés
- **Mauvais appels** : nom du tool + ce qui cloche
- **Action** : prompt fix / tool fix / docs fix / re-test
