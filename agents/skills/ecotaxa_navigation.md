---
name: ecotaxa_navigation
version: 2.2.0
triggers:
  - Explicit EcoTaxa discovery, navigation, read-only inspection, or export planning intent
forbidden_when:
  - EcoTaxa is not authorized by the source decision
requires:
  - "source:ecotaxa"
next_tool: null
max_tokens: 11000
size_exemption: The read-only EcoTaxa decision tree is kept atomic so the model can choose one route without loading a second navigation fragment; runtime delivery is budget-aware and tested end to end.
---

# Skill: ecotaxa_navigation

## Activation precondition

Apply this skill only when the Source Selection Gateway authorizes EcoTaxa,
either by an explicit current request or an inherited active-source follow-up.
Do not load or apply this skill for generic requests about samples, projects,
stations, positions, zones, maps, counts, or analyses. A loaded file remains
the default source unless the gateway authorizes EcoTaxa.

---

## Frontière avec `ecotaxa_query` — cache vs export

Deux skills EcoTaxa, deux niveaux de données. Ne pas les confondre :

| | `ecotaxa_navigation` (ce skill) | `ecotaxa_query` |
|---|---|---|
| Niveau | **Sample** (une ligne / sample) | **Objet** (un organisme / vignette) |
| Source | Cache SQL local (`query_ecotaxa_cache`) | API/export EcoTaxa (`query_ecotaxa`, download TSV) |
| Répond à | où / quand / quel cast / quel instrument / comptes sample-level V-P-D-U | détail taxon / taille / statut / score de chaque objet |
| Réseau | non (local) | oui (téléchargement, confirmation) |

Règle : **rester dans ce skill** tant que la question est au niveau sample
(zones, casts, positions, dates/heures/profondeurs, comptages de samples et
statistiques V/P/D/U au grain sample). **Basculer sur
`ecotaxa_query`** seulement quand il faut les **objets** (taxons précis, tailles,
statuts). Le cache trouve les `sample_id` ; l'export analyse leurs objets.

---

## Central exploration path — `query_ecotaxa_cache`

**All zone / time / region / grouping / ranking queries go through
`query_ecotaxa_cache(sql=...)`.**

The cache is a local SQLite database (`data/ecotaxa_cache.sqlite`). Use its
table map once when discovering the cache, preparing a join, or recovering
from an unknown-column error; the map includes actual tables, grains, columns,
keys, indexes, and relations. If the needed schema is already known, query it
directly without repeating discovery. Write arbitrary read-only `SELECT` or
`WITH`/CTE statements, including joins, subqueries, and aggregations. No
`INSERT`, `UPDATE`, `DELETE`, DDL, `ATTACH`, or mutating `PRAGMA` is allowed.
No implicit `LIMIT` is added: the full result is persisted while the displayed
preview remains compact.

**Le chemin par défaut est SAMPLE-level.** `samples_cache` porte une ligne par
sample, les statistiques autoritatives du sample et les enveloppes dérivées des
objets. `objects_cache` est optionnelle : ne l'utiliser que pour une question
explicitement object-level, après avoir vérifié sa présence avec
`describe_ecotaxa_cache_table`. Son absence ne bloque jamais les agrégats
sample-level.

### `samples_cache` — ce qu'on sait vraiment d'un sample

| Colonne | Type | Fiabilité / sens réel |
|---|---|---|
| `sample_id` | INTEGER PK | ID EcoTaxa du sample. **Toujours présent.** |
| `project_id` | INTEGER | Projet parent. **Toujours présent.** |
| `lat_avg` | REAL | Latitude du sample (WGS84). **Fiable** — position autoritative renvoyée par EcoTaxa au niveau sample. |
| `lon_avg` | REAL | Longitude du sample. **Fiable** (même source). |
| `instrument` | TEXT | ex. "UVP6", "UVP5SD", "Loki". **Fiable.** |
| `original_id` | TEXT | `orig_id` EcoTaxa du sample (ex. `am_leg2_hopedalesaddle_1`). **Toujours présent.** Encode souvent la station/cast. |
| `profile_id` | TEXT | **Le CAST (déploiement).** = free-column native si elle existe, sinon dérivé d'`original_id` (sans le `_<n>` final). Samples partageant un `profile_id` = samples d'un même cast → `COUNT(*) GROUP BY profile_id` = nb de samples par cast. |
| `station_id` | TEXT | Station (lieu). **Souvent NULL** : n'existe que si le projet a une free-column station native. Un cast n'est PAS une station — jamais dérivé d'`original_id`. |
| `object_count` | INTEGER | **Total réel d'objets du sample** = `nb_validated + nb_predicted + nb_dubious + nb_unclassified`, via `sample_taxo_stats` (sans plafond ni download). **Fiable.** |
| `nb_validated` | INTEGER | Objets **validés** (vérité terrain) dans le sample. Sans download. |
| `nb_predicted` | INTEGER | Objets **prédits** (modèle, PAS validés). Un sample tout-`nb_predicted` sans validé → prédictions jamais vérifiées, signaler avant analyse quantitative. |
| `nb_dubious` | INTEGER | Objets **douteux**. |
| `nb_unclassified` | INTEGER | Objets **non classifiés**. |
| `used_taxa` | TEXT (JSON) | **Liste des taxon_id présents** dans le sample. Permet « quels samples contiennent le taxon X » **depuis le cache** (`WHERE used_taxa LIKE '%25828%'`). IDs → noms via `search_ecotaxa_taxa` / `get_taxon`. |
| `date_min` / `date_max` | TEXT | Dates ISO issues du scan d'objets (object-level). **Peuvent être NULL** (dates par objet, pas de date au niveau sample). |
| `datetime_min` / `datetime_max` | TEXT | Enveloppe date-heure ISO dérivée des objets. Exacte seulement avec `metadata_complete = 1` et `temporal_precision = 'datetime'`. |
| `time_min` / `time_max` | TEXT | Enveloppe horaire `HH:MM:SS` dérivée des objets. Exacte seulement avec `metadata_complete = 1` et `missing_time_count = 0`. |
| `temporal_precision` | TEXT | `datetime`, `date`, `partial` ou `none` selon les métadonnées temporelles observées. |
| `depth_min` / `depth_max` | REAL | Profondeurs (m) issues du scan d'objets. **Peuvent être NULL** (même raison). |
| `missing_date_count` / `missing_time_count` | INTEGER | Nombre d'objets sans date / heure exploitable. |
| `missing_depth_min_count` / `missing_depth_max_count` | INTEGER | Nombre d'objets sans borne min / max de profondeur. |
| `depth_complete` | INTEGER | 1 si le scan est complet et toutes les bornes de profondeur sont présentes. |
| `metadata_objects_scanned` | INTEGER | Nombre d'objets inspectés pour construire les enveloppes. |
| `metadata_complete` | INTEGER | 1 si le scan couvre le total autoritatif sans divergence. |
| `metadata_coverage_pct` | REAL | Part du total autoritatif inspectée, en pourcentage. |
| `free_fields_json` | TEXT | Free-columns brutes du sample (souvent `{}`). |
| `iho_zone` | TEXT | Zone IHO/MEOW assignée par point-in-polygon au sync (ex. `"Baie de Baffin"`, `"MEOW: Northern Labrador"`, `"Hors zone référencée"`). **Fiable** (dérive de lat/lon). |

**Règle d'or fiabilité** : fiables au niveau sample → `sample_id`, `project_id`,
`lat_avg`, `lon_avg`, `instrument`, `original_id`, `profile_id`, `iho_zone`,
`object_count`, `nb_validated/predicted/dubious/unclassified`, `used_taxa` (tous
via des appels sample-level, sans download). Peuvent être NULL → `date_*`,
`datetime_*`, `time_*`, `depth_*` (enveloppes dérivées des objets), `station_id`
(pas de donnée station pour beaucoup de projets). Ne jamais présenter un 0/NULL
comme un fait négatif sans le signaler. Position et comptes sont autoritatifs au
niveau sample ; date, heure, date-heure et profondeur restent des enveloppes
object-derived soumises aux gardes de complétude.

**Le cache répond donc, sans download** : où (`lat/lon`, `iho_zone`), quand
(`date_*` si dispo), quel cast (`profile_id`), quel instrument, **combien
d'objets et à quel niveau de validation** (`object_count`, `nb_*`), et **quels
taxons sont présents** (`used_taxa`). Seuls les objets individuels (tailles,
scores, position ou statut d'un objet précis) exigent `objects_cache` si
disponible, sinon l'export.

For cross-sample date, hour, date-time, or depth questions, query the cache
first. Restrict exact envelope claims to complete rows and report how many rows
in the same scope have unknown or partial metadata. For one resolved incomplete
sample, use `summarize_ecotaxa_sample_deployment`; never launch that live call
silently for a large batch.

### Zone queries — utiliser `iho_zone` directement

Le cache a une colonne `iho_zone` pré-calculée par point-in-polygon (IHO puis MEOW).
Toujours utiliser `LIKE` pour filtrer les zones — jamais `=` (les apostrophes et accents cassent silencieusement `=`).

```sql
WHERE iho_zone LIKE '%Baffin%'
WHERE iho_zone LIKE '%Hudson%'
WHERE iho_zone LIKE 'MEOW: %'
GROUP BY iho_zone
```

**Règle apostrophe/accent** : ne jamais écrire `WHERE iho_zone = 'Détroit d''Hudson'`. Toujours `LIKE '%Détroit%Hudson%'` ou `LIKE '%Hudson%'`.

**Invariance linguistique** : l'utilisateur peut nommer les zones en français ou en anglais. Convertir avant la requête :

| Ce que dit l'utilisateur | `LIKE` à utiliser |
|---|---|
| Hudson Strait / Détroit d'Hudson | `LIKE '%Hudson%'` + exclure `'%Baie%'` si besoin |
| Hudson Bay / Baie d'Hudson | `LIKE '%Hudson%'` + `NOT LIKE '%Détroit%'` |
| Baffin Bay / Baie de Baffin | `LIKE '%Baffin%'` |
| Davis Strait / Détroit de Davis | `LIKE '%Davis%'` |
| Labrador Sea / Mer du Labrador | `LIKE '%Labrador%'` |
| Beaufort Sea / Mer de Beaufort | `LIKE '%Beaufort%'` |
| Gulf of St. Lawrence / Golfe du Saint-Laurent | `LIKE '%Laurent%'` ou `LIKE '%Saint%Laurent%'` |
| Lincoln Sea / Mer de Lincoln | `LIKE '%Lincoln%'` |
| Arctic / Arctique | `LIKE '%Arctique%'` ou `LIKE '%Arctic%'` |

**Règle d'ambiguïté obligatoire** : quand le LIKE ramène plusieurs zones distinctes (ex. `Baie d'Hudson` + `Détroit d'Hudson`), NE PAS choisir silencieusement. Afficher la liste des zones trouvées avec leur nombre de samples, puis s'arrêter et demander : "Ces deux zones correspondent — laquelle vous intéresse, ou les deux ?" Ne passer à l'analyse qu'après confirmation explicite.

Ne plus utiliser `get_zone_info` + bbox pour les requêtes de zone — `iho_zone` est plus précis.
`get_zone_info` reste utile pour afficher la description d'une zone à l'utilisateur.

### Règles de persistance des variables — critique

**`df_ecotaxa_cache_query` = sélection canonique des samples.** Toujours
protégé. Règles :

1. **Inclure `iho_zone` dans tout SELECT sample-level.** Même si l'utilisateur
   ne demande pas un groupement par zone, inclure `iho_zone` dans les SELECTs
   qui retournent des lignes sample-level — cela permet une agrégation par zone
   en aval via `run_pandas` sans re-requêter le cache.

2. **Les agrégations ne doivent jamais écraser `df_ecotaxa_cache_query`.** Si
   un "groupe par zone" ou un COUNT est demandé après une sélection existante,
   deux options :
   - **Option A (préférentielle)** : `run_pandas` sur `df_ecotaxa_cache_query`
     existant — `df_ecotaxa_cache_query.groupby('iho_zone').size()`. Utilisable
     seulement si `iho_zone` est dans le DataFrame.
   - **Option B** : re-lancer `query_ecotaxa_cache` avec `GROUP BY iho_zone` et
     stocker le résultat dans une **variable distincte** (`df_zone_counts`,
     `df_zone_summary`, etc.). Ne jamais écraser `df_ecotaxa_cache_query`.

3. **Ne jamais reconstruire un découpage spatial avec des bbox manuelles** si
   `iho_zone` est disponible. Des bbox hardcodées de mémoire donnent des
   comptages faux ou incomplets pour les zones aux frontières complexes (baie
   d'Hudson, archipel arctique, etc.).

### Common SQL patterns

**Date envelope overlap in a zone (inclure `iho_zone` dans le SELECT) :**
```sql
SELECT sample_id, project_id, original_id, lat_avg, lon_avg, iho_zone,
       date_min, date_max, depth_min, depth_max, instrument
FROM samples_cache
WHERE iho_zone LIKE '%Baffin%'
  AND metadata_complete = 1
  AND missing_date_count = 0
  AND date_min <= '2024-12-31'
  AND date_max >= '2024-01-01'
ORDER BY date_min
```

**Date-time envelope overlap, complete timestamp metadata only :**
```sql
SELECT sample_id, project_id, datetime_min, datetime_max, iho_zone
FROM samples_cache
WHERE metadata_complete = 1
  AND temporal_precision = 'datetime'
  AND datetime_min <= '2015-05-22T16:00:00'
  AND datetime_max >= '2015-05-22T14:00:00'
```

**Hour envelope overlap, normal same-day range :**
```sql
SELECT sample_id, project_id, time_min, time_max, iho_zone
FROM samples_cache
WHERE metadata_complete = 1
  AND missing_time_count = 0
  AND time_min <= '16:00:00'
  AND time_max >= '14:00:00'
```

**Hour envelope overlap across midnight :**
```sql
SELECT sample_id, project_id, time_min, time_max, iho_zone
FROM samples_cache
WHERE metadata_complete = 1
  AND missing_time_count = 0
  AND (time_max >= '22:00:00' OR time_min <= '02:00:00')
```

**Complete depth-envelope overlap :**
```sql
SELECT sample_id, project_id, depth_min, depth_max, iho_zone
FROM samples_cache
WHERE depth_complete = 1
  AND depth_min <= 300
  AND depth_max >= 100
```

Dans chaque cas, les lignes exclues par la garde de complétude sont inconnues,
pas des non-correspondances. Exécuter un second `COUNT(*)` dans le même scope
`project_id` / `iho_zone` avec la garde complémentaire (`metadata_complete IS
NOT 1`, compteur manquant non nul, précision inadéquate, ou `depth_complete IS
NOT 1`) et rapporter ce nombre. Ne pas étendre silencieusement une enveloppe
partielle en minimum/maximum exact.

**Projects in a zone (aggregate) :**
```sql
SELECT project_id,
       COUNT(*) AS n_samples,
       MIN(date_min) AS date_min, MAX(date_max) AS date_max,
       GROUP_CONCAT(DISTINCT instrument) AS instruments
FROM samples_cache
WHERE iho_zone LIKE '%Baffin%'
GROUP BY project_id
ORDER BY n_samples DESC
```

**Samples per year in a zone:**
```sql
SELECT strftime('%Y', date_min) AS year,
       COUNT(*) AS n_samples,
       COUNT(DISTINCT profile_id) AS n_casts
FROM samples_cache
WHERE iho_zone LIKE '%Baffin%'
GROUP BY year ORDER BY year
```

**Rank all zones by cast count:**
```sql
SELECT iho_zone,
       COUNT(DISTINCT profile_id) AS n_casts,
       COUNT(*) AS n_samples,
       MIN(date_min) AS date_min, MAX(date_max) AS date_max
FROM samples_cache
WHERE iho_zone != 'Hors zone référencée'
GROUP BY iho_zone
ORDER BY n_casts ASC
```

**Samples of one project by zone:**
```sql
SELECT iho_zone,
       COUNT(*) AS n_samples,
       GROUP_CONCAT(sample_id) AS sample_ids
FROM samples_cache
WHERE project_id = 17498
GROUP BY iho_zone
ORDER BY n_samples DESC
```

**Audit taxonomique : distinguer le grain.** Les V/P/D/U et `object_count` au
grain sample viennent directement de `samples_cache`. Un `GROUP BY taxon` est
explicitement object-level : utiliser `objects_cache` seulement si cette table
optionnelle est présente, sinon exporter les objets après confirmation. Ne
jamais joindre `objects_cache` pour recalculer les comptes sample-level.

**Casts avec position (pour carte) — toujours inclure lat/lon :**
```sql
SELECT profile_id AS cast_id,
       AVG(lat_avg) AS lat,
       AVG(lon_avg) AS lon,
       COUNT(DISTINCT sample_id) AS n_samples,
       MIN(date_min) AS date_min,
       MAX(date_max) AS date_max,
       GROUP_CONCAT(DISTINCT instrument) AS instruments
FROM samples_cache
WHERE iho_zone LIKE '%Détroit%Hudson%'
GROUP BY profile_id
ORDER BY date_min
```

Règle : dès que l'utilisateur demande d'afficher des casts sur une carte, toujours inclure `AVG(lat_avg) AS lat` et `AVG(lon_avg) AS lon` dans le SELECT groupé par `profile_id`.

**`profile_id` = le cast, et il est renseigné.** Depuis le sync, `profile_id`
est rempli pour tout sample ayant un `original_id` : free-column native si elle
existe, sinon dérivé d'`original_id` (sans le `_<n>` final). Donc
`GROUP BY profile_id` fonctionne et `COUNT(*) GROUP BY profile_id` = **nb de
samples par cast**. Ne pas retomber sur l'ancienne règle « profile_id NULL →
grouper par sample_id » : elle est obsolète. `profile_id` n'est jamais inventé —
il vient toujours d'une donnée EcoTaxa réelle (`original_id`).

Cas limite unique : un sample sans `original_id` du tout (rarissime) aura
`profile_id` NULL — alors seulement, signaler et grouper par `sample_id`. Ne
jamais confondre avec `station_id`, qui lui est souvent NULL (voir schéma) : un
cast n'est pas une station.

**Depth filters :** une affirmation exacte sur l'enveloppe exige toujours
`depth_complete = 1`. Pour un intervalle demandé `[a, b]`, utiliser l'overlap
`depth_min <= b AND depth_max >= a`; compter séparément les lignes où
`depth_complete IS NOT 1` dans le même scope.

**Instrument filter:**
```sql
WHERE instrument = 'Loki'   -- exact match, case-sensitive
```
"LOKI" / "loki" / "projet LOKI" = instrument `'Loki'` unless the user explicitly says "projet nommé LOKI".

**Cache status:**
```sql
SELECT COUNT(*) AS n_samples, COUNT(DISTINCT project_id) AS n_projects FROM samples_cache;
SELECT status, ended_at FROM sync_runs ORDER BY run_id DESC LIMIT 1;
```

---

## Fallback API réelle — projet absent du cache

Si `query_ecotaxa_cache` retourne 0 lignes pour un `project_id` donné, **ne pas abandonner** : le projet existe mais n'est pas encore synchronisé dans le cache. Utiliser les tools API directement :

| Besoin | Tool API (sans cache) |
|---|---|
| Stats V/P/D/U + nb objets d'un projet | `preview_ecotaxa_project(project_id)` |
| Breakdown taxons V/P/D/U | `count_ecotaxa_taxa(project_ids=[...])` |
| Stats V/P/D/U d'une liste de samples | `summarize_ecotaxa_samples(sample_ids=[...])` |
| Détail d'un sample résolu dont les enveloppes cache sont incomplètes | `summarize_ecotaxa_sample_deployment(sample_id)` |
| Objets d'un sample (lecture seule) | `list_ecotaxa_sample_objects(sample_id)` |
| Télécharger un sample complet | `query_ecotaxa_sample(sample_id)` |

**Règle de routage V/P/D/U :**

Stats par sample depuis le cache (sans API) — **toujours utiliser `samples_cache` directement** :
```sql
SELECT sample_id, original_id, iho_zone,
       nb_validated, nb_predicted, nb_dubious, nb_unclassified, object_count
FROM samples_cache
WHERE iho_zone LIKE '%Labrador%'
ORDER BY date_min
```
Ces colonnes sont fiables, sans download, sans JOIN sur `objects_cache`.
Ne jamais faire un JOIN `samples_cache` × `objects_cache` pour obtenir des
stats V/P/D/U par sample — `nb_validated` etc. sont déjà agrégés au niveau sample.

For sample-level V/P/D/U counts, use the authoritative
`samples_cache.nb_validated`, `samples_cache.nb_predicted`,
`samples_cache.nb_dubious`, and `samples_cache.nb_unclassified` columns; never
derive a status count from `object_count`. Use
`objects_cache.classification_status` only for an explicitly object-level query
when the optional object cache is present.

- "état des images / stats du projet X" → sommer les colonnes `samples_cache.nb_*` si le projet est indexé ; utiliser le résumé direct seulement en fallback de cache absent
- "combien de validés dans le projet X" → `SUM(nb_validated)` dans `samples_cache`, pas `SUM(object_count)`
- "enveloppe incomplète du sample résolu Y" → `summarize_ecotaxa_sample_deployment(sample_id=Y)` ; ne jamais répéter cet appel live silencieusement sur un grand lot
- Ne jamais retourner 0/0/0/0 si le projet est connu — aller sur l'API.

After `query_ecotaxa_cache`, use `run_pandas` for derived tables, joins,
rankings, or cross-source comparisons. The result is available as
`df_ecotaxa_cache_query`.

### Campagne → export : `selection_name="latest"`

Dès qu'une requête cache renvoie une colonne `sample_id`, sa sélection (samples
+ projets résolus) est **mémorisée automatiquement**. Pour exporter EXACTEMENT ce
que la campagne a sélectionné — un ou plusieurs samples, un ou plusieurs projets
— appeler directement, sans ré-extraire les IDs :

```
export_ecotaxa_samples(selection_name="latest", status="", taxon=None)
```

Exemple « tous les objets de la mer du Labrador en 2014 » :
```
1. query_ecotaxa_cache("SELECT sample_id, project_id FROM samples_cache
       WHERE iho_zone LIKE '%Labrador%' AND date_min >= '2014-01-01'
         AND date_min <= '2014-12-31'")           → sélection mémorisée
2. export_ecotaxa_samples(selection_name="latest", status="")  # dry-run puis confirmed=True
```
`status=""` = tous les objets (pas seulement les validés). `taxon="Calanus"` pour
ne descendre qu'un taxon. Le pré-filtrage taxon peut se faire au niveau cache
via `used_taxa` (ex. `WHERE used_taxa LIKE '%25828%'`) avant l'export.

### Protocole obligatoire — préparer puis confirmer l'export

Ne lance jamais un téléchargement d'objets dès la première demande « exporte ».
L'intention déclenche un **plan**, puis une nouvelle confirmation explicite de
l'utilisateur déclenche l'export. Ne confonds pas un « oui » donné avant le plan,
une demande d'analyse/graphe, ou une ancienne confirmation avec l'approbation du
plan courant.

1. **Choisir le scope le plus étroit.**
   - Un sample résolu : `query_ecotaxa_sample(sample_id=S)`.
   - Plusieurs samples d'un seul projet connu, ou le projet entier :
     `query_ecotaxa(project_id=P, sample_ids=[...])` ou `query_ecotaxa(project_id=P)`.
   - Une sélection mémorisée, ou des samples couvrant plusieurs projets :
     `export_ecotaxa_samples`.
   - Après une campagne cache qui a retourné `sample_id`, employer
     `selection_name="latest"` : ne recopie jamais les IDs de l'aperçu.
2. **Décrire le plan à l'utilisateur.** Indiquer le scope (sample(s) et projet(s)
   si connus), les filtres demandés, et que l'opération téléchargera tous les
   objets concernés. Pour une sélection, obtenir le plan exact avec :

   ```
   export_ecotaxa_samples(
       selection_name="latest", status="", taxon=None, confirmed=False
   )
   ```

   `confirmed=False` est un dry-run : il n'exporte rien et renvoie la répartition
   projet → samples. Pour `query_ecotaxa` ou `query_ecotaxa_sample`, préparer le
   même résumé à partir du scope déjà résolu, sans appeler le download.
3. **Attendre une nouvelle approbation explicite.** Une fois le plan présenté,
   accepter par exemple « oui, lance cet export » ou « confirme le plan ci-dessus ».
   Si l'utilisateur change de période, de taxon, de statut, de profondeur ou de
   sélection, refaire le plan : l'ancienne confirmation ne vaut plus.
4. **Exécuter exactement le plan confirmé.** Dès cette confirmation, appeler
   l'export dans le même tour : ne pas répondre avec le plan, ne pas redemander
   les `sample_id`, et ne pas exiger une formulation technique. Pour une sélection, rappeler avec
   les mêmes arguments et `confirmed=True`. Pour un sample/projet, appeler le
   téléchargement choisi à l'étape 1 seulement après confirmation. Ne remplacer
   jamais silencieusement un scope multi-projets par le dernier projet vu.
5. **Après le résultat.** Si l'export réussit, annoncer le lien de téléchargement,
   la source, le scope effectivement exporté et la prochaine analyse possible.
   Si EcoTaxa retourne `EXPORT_FAILED`, reprendre son message, signaler que les
   objets n'ont pas été téléchargés, puis proposer une prévisualisation ou un
   résumé read-only ; ne fabriquer aucun résultat partiel.

Après un export multi-projets réussi, la table active est la **table de campagne
consolidée** : elle contient toutes les lignes objet exportées et la colonne
`export_project_id`. Utiliser cette table pour l'analyse, le graphe ou
l'enrichissement de toute la campagne ; ne jamais analyser par défaut le dernier
projet traité. Les tables brutes par projet sont conservées séparément, seulement
pour une question explicitement limitée à un projet.

Les filtres suivent toujours le plan confirmé : `status="V"` signifie validés
seulement, `status="P"` prédits seulement et `status=""` tous les statuts.
`taxon` est optionnel ; les filtres de profondeur sont disponibles pour un export
de projet. Ne télécharge pas des objets pour obtenir simplement un count, un
schéma, un aperçu, ou les V/P/D/U : ces besoins restent couverts par le cache et
les outils de résumé légers.

---

## Scénarios de navigation — arbre de décision complet

Trois niveaux d'exploration. Chaque niveau s'appuie sur le précédent ; ne pas sauter de niveau.

```
NIVEAU 1 — Cache local (SQL, sans réseau)
  query_ecotaxa_cache → sample_id, lat/lon, zone, date/heure/profondeur,
                         instrument, object_count, V/P/D/U

NIVEAU 2 — Détail live d'un sample résolu (fallback ciblé)
  summarize_ecotaxa_sample_deployment(sample_id=...) → enveloppes et couverture

NIVEAU 3 — Objets individuels (réseau, téléchargement)
  ├─ Browse read-only : list_ecotaxa_sample_objects(sample_id)
  ├─ Download 1 sample : query_ecotaxa_sample(sample_id)
  ├─ Download N samples, 1 projet : query_ecotaxa(project_id=X, sample_ids=[...])
  └─ Download N samples, M projets : export_ecotaxa_samples(sample_ids=[...])
```

### Tableau de routage complet

| # | Ce que dit l'utilisateur | Niveau | Tool(s) | Download ? |
|---|---|---|---|---|
| A | "quels samples dans Baie d'Hudson 2021" | 1 | `query_ecotaxa_cache` SQL | Non |
| B | "nb images validées / prédites par sample" | 1 | `query_ecotaxa_cache` sur `samples_cache.nb_*` | Non |
| C | "carte : positions des samples + nb prédits" | 1 | cache SQL avec lat/lon + `nb_predicted` → `run_graph` | Non |
| D | "browse les objets du sample 123" | 3 | `list_ecotaxa_sample_objects(sample_id=123)` | Non |
| E | "télécharge / analyse le sample 123" | 3 | `query_ecotaxa_sample(sample_id=123)` → `load_file` | Oui (1 sample) |
| F | "tous les objets des samples 123 et 456, même projet" | 3 | `query_ecotaxa(project_id=X, sample_ids=[123,456])` → `load_file` | Oui |
| G | "tous les objets des samples 123 et 456, projets différents" | 3 | `export_ecotaxa_samples(sample_ids=[123,456])` → `load_file` | Oui (lourd) |
| H | "filtre Calanus sur ces objets" | 3 | après E/F/G → `run_pandas` | — |
| I | "carte taxons précis sur ces objets" | 3 | après E/F/G → `run_graph` | — |

**Règle de sélection du tool niveau 3 (download) :**
```
1 sample                        → query_ecotaxa_sample(sample_id=S)
N samples, 1 projet             → query_ecotaxa(project_id=X, sample_ids=[...])
N samples, M projets différents → export_ecotaxa_samples(sample_ids=[...])
Projet entier                   → query_ecotaxa(project_id=X)
```

### API lecture vs export — quand utiliser lequel

Deux mécaniques distinctes pour accéder aux objets. Ne pas les confondre.

| | API lecture (`list_ecotaxa_sample_objects`) | Export (`query_ecotaxa_sample` / `query_ecotaxa` / `export_ecotaxa_samples`) |
|---|---|---|
| Mécanique | requête paginée `object_set/query` | job EcoTaxa → TSV téléchargé → DataFrame |
| Volume | 1 page (max 200 objets) | tous les objets du scope |
| Persistance | rien, éphémère | `df_ecotaxa_*` réutilisable en session |
| Coût | léger, pas de confirmation | lourd, **confirmation requise** |
| Analysable ? | non (juste affichage) | oui — `run_pandas` / `run_graph` |

**La question qui tranche : REGARDER ou CALCULER ?**
- Feuilleter, vérifier « qu'y a-t-il dans ce sample ? », voir quelques objets d'un taxon avant de décider → **API lecture**.
- Compter, agréger, filtrer sur l'ensemble, tracer un graphe/carte, sauvegarder → **export**.

**Règle graphe/analyse — toujours proposer l'export.** Dès que la demande implique un
graphe, une carte au grain objet, une distribution, un histogramme, un profil, ou tout
calcul sur l'ensemble des objets : l'API paginée ne suffit pas (bornée à 200). Proposer
l'export — jamais tenter de construire un graphe à partir d'une page API. Exemples qui
exigent l'export : « histogramme de taille des objets », « profil de profondeur par
taxon », « carte pondérée par abondance d'objets », « distribution des scores ».

**Enchaînement type :** API d'abord pour explorer/décider (léger), puis proposer l'export
si l'utilisateur veut analyser ou visualiser. L'export reste confirmé avant lancement.

### Scénario C en détail — carte "nb taxons par sample" (sans download)

```
1. query_ecotaxa_cache(sql="""
       SELECT sample_id, lat_avg AS lat, lon_avg AS lon,
              iho_zone, date_min, instrument,
              nb_validated, nb_predicted
       FROM samples_cache
       WHERE iho_zone LIKE '%Hudson%'
         AND metadata_complete = 1
         AND missing_date_count = 0
         AND date_min <= '2021-12-31'
         AND date_max >= '2021-01-01'
   """)
   → df_ecotaxa_cache_query  [sample_id, lat, lon, date_min, instrument, V, P]

2. Compter séparément les lignes du même scope où `metadata_complete IS NOT 1`
   ou `missing_date_count <> 0`, puis rapporter cette couverture inconnue.

3. run_pandas:
   result = df_ecotaxa_cache_query.assign(
       n_predicted=df_ecotaxa_cache_query["nb_predicted"]
   )

4. run_graph: scatter map lat/lon, taille/couleur = n_predicted
```

### Scénarios F/G — objets de plusieurs samples

Toujours dry-run d'abord pour `export_ecotaxa_samples` :
```python
export_ecotaxa_samples(sample_ids=[123, 456], confirmed=False)  # affiche le plan
# → montrer à l'utilisateur : projets impliqués, nb objets estimé
export_ecotaxa_samples(sample_ids=[123, 456], confirmed=True)   # après "oui" explicite
```
Ne jamais sauter le dry-run, même si l'utilisateur dit "vas-y direct".

Pour `query_ecotaxa` (même projet), pas de dry-run requis — le tool est idempotent.

### Quand descendre au niveau 3 (objets)

Descendre **uniquement** si l'utilisateur veut :
- filtrer sur un taxon **précis** (pas juste voir le top taxa → niveau 2 suffit)
- accéder aux **scores de classification** (`auto_score`, `rank`)
- obtenir les **object_id** pour annotation ou export externe
- faire une **analyse pandas/graphique sur les objets eux-mêmes** (profil de taille, abondance, etc.)

Si le besoin est "nb de prédits / validés par sample" → `samples_cache.nb_*`
suffit ; ne pas appeler le live et ne pas exporter.

---

## Audit taxonomique

Un audit taxonomique peut s'appliquer à n'importe quel ensemble de samples, quelle que soit leur origine (zone, date, instrument, projet, sélection manuelle). Deux niveaux de profondeur possibles :

### Niveau léger — top taxa sans download

`summarize_ecotaxa_samples(sample_ids=[...])` retourne par sample :
- V / P / D / U (counts de classification)
- top taxa : jusqu'à **5 taxa** (les plus abondants) — pas exhaustif

Utilisable pour : "combien d'objets annotés ?", "quels grands groupes présents ?", "lesquels valent l'export ?"

Agrégation possible ensuite dans `run_pandas` à n'importe quel niveau de grain :
```python
# par cast (profile_id)
df = df_stats.merge(df_ecotaxa_cache_query[["sample_id","profile_id"]], on="sample_id")
df.groupby("profile_id")[["V","P","D","U"]].sum()

# par zone
df = df_stats.merge(df_ecotaxa_cache_query[["sample_id","iho_zone"]], on="sample_id")
df.groupby("iho_zone")[["V","P","D","U"]].sum()

# par année
df = df_stats.merge(df_ecotaxa_cache_query[["sample_id","date_min"]], on="sample_id")
df["year"] = df["date_min"].str[:4]
df.groupby("year")[["V","P","D","U"]].sum()
```

### Niveau complet — tous les taxa avec counts exacts (download requis)

Quand l'utilisateur veut tous les taxa (pas juste le top 5), ou des counts exacts par taxon par sample/cast, il faut exporter les objets.

Signaler la limite avant de proposer l'export :
> "summarize_ecotaxa_samples donne les 5 taxa dominants par sample. Pour un audit complet avec tous les taxa, il faut télécharger les objets — voulez-vous lancer l'export ?"

Après confirmation :
```python
# Après export → df_ecotaxa disponible dans run_pandas
# Joindre le grain voulu depuis df_ecotaxa_cache_query
df = df_ecotaxa.merge(
    df_ecotaxa_cache_query[["sample_id", "profile_id", "iho_zone", "date_min"]],
    on="sample_id", how="left"
)

# Audit par cast × taxon
result = (
    df.groupby(["profile_id", "object_annotation_category"])
      .agg(n=("object_id", "count"),
           pct_V=("object_annotation_status", lambda x: (x=="V").mean()*100))
      .reset_index()
      .sort_values(["profile_id", "n"], ascending=[True, False])
)
```

Le même pattern fonctionne en remplaçant `profile_id` par `iho_zone`, `date_min`, `instrument`, ou tout autre niveau de grain disponible dans `df_ecotaxa_cache_query`.

---

## Navigation pipeline

```
1. FIND (query_ecotaxa_cache SQL)
   WHERE iho_zone LIKE '...' → SELECT from samples_cache
   Résultat : sample_id, project_id, lat/lon, dates, depth, instrument

1b. PROJECT SCAN (optionnel, avant drill)
    GROUP BY project_id → n_samples, enveloppe, instruments
    + count_ecotaxa_taxa(project_ids=[...]) pour V/P/D/U niveau projet

2. SAMPLE SCAN (optionnel, avant export)
   summarize_ecotaxa_samples(sample_ids=[...])
   → V/P/D/U + top taxa par sample — 1 appel API, aucun download

3. EXPORT (confirmé — niveau 3 seulement)
   export_ecotaxa_samples(sample_ids=[...], confirmed=False)  ← dry-run obligatoire
   export_ecotaxa_samples(sample_ids=[...], confirmed=True)   ← après ack utilisateur
```

---

## Ambiguity rules

- **STOP rule — ambiguous "samples présents" / "qu'est-ce qu'on a"**: when
  no scope was established in the previous turn, ask ONE clarifying question
  with 2–3 concrete options. Call ZERO tools this turn.
- Follow-up wording ("ces samples", "ce tableau", "parmi ceux-là") means
  reuse the `sample_id` values already shown. Do not launch a new search.
- "stats", "tableau", "résumé", "scan", "liste", "combien", "où", "top",
  "rank" → read-only SQL path, not export.
- When the user gives numeric `project_ids` and wants project stats →
  `query_ecotaxa_cache` GROUP BY project_id, optionally `count_ecotaxa_taxa`
  for V/P/D/U. Do not route to `run_pandas` or `query_ecotaxa`.
- Cache is not the source: a sample absent from the cache may still exist
  in EcoTaxa. Use `describe_ecotaxa_project_coverage(project_id=...)` to
  distinguish a real absence (`vide_source`) from `non_indexe` / `partiel`.
- When the only plausible routes are a read-only summary and a full export,
  choose the read-only SQL path unless the user says "exporte", "charge",
  or "download".

---

## Colonnes disponibles après un export d'objets

L'export retourne un TSV chargé en DataFrame (`df_ecotaxa_*`). Les colonnes sont structurées en 4 niveaux de préfixe.

### Colonnes fixes (toujours présentes)

| Colonne | Contenu |
|---|---|
| `object_id` | ID interne EcoTaxa de l'objet |
| `object_lat`, `object_lon` | Position GPS de l'objet |
| `object_depth_min`, `object_depth_max` | Profondeur (m) |
| `object_date`, `object_time` | Horodatage de la capture |
| `object_annotation_category` | Nom du taxon assigné (V ou P) |
| `object_annotation_category_id` | ID EcoTaxa du taxon |
| `object_annotation_status` | `V` validé / `P` prédit / `D` douteux / `U` non classifié |
| `object_annotation_person_name` | Validateur (si V) |
| `object_annotation_date` | Date de classification |
| `sample_id` | ID du sample parent |
| `sample_original_id` | Label de station / déploiement |
| `acq_id` | ID d'acquisition |

### Champs libres (variables par projet/instrument)

| Préfixe | Exemples typiques (UVP) |
|---|---|
| `object_<champ>` | `object_esd`, `object_biovolume`, `object_area`, `object_major`, `object_minor` |
| `sample_<champ>` | `sample_towtype`, `sample_net_opening`, `sample_ship` |
| `acq_<champ>` | `acq_pixel`, `acq_sub` |
| `process_<champ>` | `process_soft`, `process_version` |

**Les champs libres dépendent du projet.** Avant un export inconnu, appeler `inspect_ecotaxa_project_schema(project_id=...)` pour voir les colonnes disponibles.

### Positions géographiques dans un export

`object_lat` et `object_lon` sont présents pour chaque objet, **mais pour les instruments verticaux (UVP, Loki), tous les objets d'un même cast partagent la même lat/lon** (position du navire au moment du déploiement). Il n'y a pas de variation horizontale entre objets du même cast.

Conséquence directe sur les cartes :
- **"1 point par objet sur une carte"** → inutile, tous les objets du même cast se superposent au même pixel.
- **Carte correcte = 1 point par sample**, taille ou couleur = agrégat des objets (nb Calanus, abondance, etc.)

**Chemin carte avec taxon précis après export :**
```python
# 1. Filtrer sur le taxon voulu
df_cal = df[df["object_annotation_category"].str.contains("Calanus", na=False)]

# 2. Agréger par sample_id
agg = df_cal.groupby("sample_id").agg(
    n_calanus=("object_id", "count"),
    lat=("object_lat", "first"),      # même lat pour tout le sample
    lon=("object_lon", "first"),
).reset_index()

# 3. run_graph : scatter lat/lon, size=n_calanus
```

Ce chemin donne la carte "nb Calanus par sample" avec taxon précis — l'équivalent du scénario C mais avec filtre taxon exact au lieu du top taxa.

**Autres analyses pertinentes avec les positions :**
```python
# Profil de profondeur (axe Y inversé = on descend)
df.groupby(pd.cut(df["object_depth_min"], bins=range(0, 1000, 50)))["object_id"].count()

# Section latitudinale : lat vs profondeur, couleur = taxon
# → utile sur une transect (plusieurs casts alignés)

# Abondance par profondeur et par cast
df.groupby(["sample_id", pd.cut(df["object_depth_min"], 10)])["object_id"].count()
```

### Colonne `year` ajoutée automatiquement

Après chaque export, une colonne `year` (entier) est ajoutée si une colonne date est trouvée — permet directement `groupby("year")` sans parsing manuel.

---

## Scan avant export — `summarize_ecotaxa_samples`

`summarize_ecotaxa_samples(sample_ids=[...])` — 1 appel API, aucun objet téléchargé.

| Colonne retournée | Signification |
|---|---|
| `V` | objets validés (vérité terrain) |
| `P` | prédits par le modèle (PAS validés) |
| `D` | douteux |
| `U` | non classifiés |
| `top taxa` | jusqu'à 5 taxons présents dans le sample |

Utiliser pour "lequel vaut l'export ?", "qu'y a-t-il dedans ?", ranking par total.
Un sample avec uniquement `P` et aucun `V` = prédictions modèle jamais validées — signaler à l'utilisateur avant toute analyse quantitative.

---

## Export d'objets — sélection du tool

```
1 sample                        → query_ecotaxa_sample(sample_id=S)
N samples, 1 projet             → query_ecotaxa(project_id=X, sample_ids=[...])
N samples, M projets différents → export_ecotaxa_samples(sample_ids=[...])
Projet entier                   → query_ecotaxa(project_id=X)
```

`export_ecotaxa_samples` : toujours dry-run d'abord (`confirmed=False`), puis `confirmed=True` après "oui" explicite. Ne jamais sauter le dry-run.

Après `EXPORT_FAILED` : citer le message serveur, proposer `preview_ecotaxa_project(project_id=...)` pour vérifier les droits. Ne pas retomber sur une requête cache.

---

## Session state — stocker, référencer, combiner les données

### Ce qui est disponible dans `run_pandas` et `run_graph`

Chaque dataset chargé pendant la session est injecté automatiquement dans le namespace de `run_pandas` et `run_graph` par son **nom de variable exact**. Ils sont tous disponibles simultanément — pas besoin de les recharger.

| Variable | Produite par | Contenu |
|---|---|---|
| `df_ecotaxa_cache_query` | `query_ecotaxa_cache` | Résultat SQL cache (sample_id, lat, lon, zone, date…) |
| `df_ecotaxa_sample_{id}` | `query_ecotaxa_sample(sample_id=id)` | Objets du sample `id` |
| `df_ecotaxa_{project}_{ids_hash}` | `query_ecotaxa` / `export_ecotaxa_samples` | Objets d'un export batch |
| `df_ecotaxa` | alias toujours mis à jour | Dernier export EcoTaxa actif |
| `df_file_{nom}` | `load_file` | Fichier chargé par l'utilisateur |
| `loaded_file` | `load_file` | Alias stable du dernier fichier chargé |

La liste des variables actives est visible dans la capsule **WORKING TABLES** injectée à chaque tour — utiliser les noms exacts listés là.

### Combiner plusieurs datasets dans run_pandas

```python
import pandas as pd

# Combiner des objets de 2 samples téléchargés séparément
df_all = pd.concat([df_ecotaxa_sample_123, df_ecotaxa_sample_456], ignore_index=True)

# Joindre objets exportés + lat/lon depuis le cache
# (df_ecotaxa_cache_query a lat_avg, lon_avg par sample_id)
agg = df_all.groupby("sample_id").agg(
    n_calanus=("object_id", "count"),
).reset_index()
df_map = agg.merge(df_ecotaxa_cache_query[["sample_id", "lat_avg", "lon_avg"]], on="sample_id")

# Résultat: une ligne par sample avec lat/lon + comptage objets → prêt pour run_graph
```

### Workflow complet multi-samples avec taxon précis

```
Étape 1 — Cache SQL (pas de réseau)
  query_ecotaxa_cache → df_ecotaxa_cache_query [sample_id, lat_avg, lon_avg, iho_zone, date_min]

Étape 2 — Download objets (réseau)
  query_ecotaxa_sample(123) → df_ecotaxa_sample_123 [object_id, object_lat, object_lon,
                                                       object_depth_min, object_annotation_category,
                                                       object_annotation_status, sample_id, …]
  query_ecotaxa_sample(456) → df_ecotaxa_sample_456  (même schéma)

Étape 3 — Combiner + filtrer dans run_pandas
  df_all = pd.concat([df_ecotaxa_sample_123, df_ecotaxa_sample_456])
  df_cal = df_all[df_all["object_annotation_category"].str.contains("Calanus", na=False)]
  agg = df_cal.groupby("sample_id")["object_id"].count().reset_index(name="n_calanus")
  df_map = agg.merge(df_ecotaxa_cache_query[["sample_id","lat_avg","lon_avg"]], on="sample_id")

Étape 4 — Carte dans run_graph
  scatter lat_avg/lon_avg, size=n_calanus, label=sample_id
```

### Règles de nommage et persistance

- Les variables persistent toute la session (même après plusieurs tours).
- Pour N samples du même projet : `query_ecotaxa(project_id=X, sample_ids=[...])` produit un seul df contenant tous les objets — plus efficace que N appels `query_ecotaxa_sample`.
- Pour M projets différents : `export_ecotaxa_samples(sample_ids=[...])` regroupe tout dans un seul df au format commun.
- Après un `run_pandas` qui produit un résultat (`result = ...`), ce résultat est affiché mais **non stocké** comme variable de session. Si l'utilisateur veut réutiliser ce résultat dans le tour suivant, le recalculer dans le même bloc ou demander un export.

---

## Taxon counts — `count_ecotaxa_taxa`

For "combien de Calanus validés dans le projet 17498":
`count_ecotaxa_taxa(project_ids=[17498], taxa=["Calanus"])` →
V/P/D/U per (project × taxon). Project-level only, NOT per-sample.

Broad copepod alias: `Copepoda<Multicrustacea` (taxon_id 25828). When
`count_ecotaxa_taxa` returns `AMBIGUOUS_TAXON`, call
`search_ecotaxa_taxa(query=...)` first to resolve the ID, then retry.
Never invent a `taxon_id`.

---

## Taxon observations — `find_ecotaxa_observations`

Use when the user names a taxon AND a zone/date: "samples avec Calanus en
Baie de Baffin". Prefer over a cache SQL when taxon presence is the
primary filter — it searches directly via EcoTaxa project stats.

---

## Project and sample inspection tools

| Tool | When |
|---|---|
| `list_ecotaxa_projects()` | "quels projets j'ai accès" |
| `find_ecotaxa_projects(title=..., instrument=...)` | keyword search on project names |
| `preview_ecotaxa_project(project_id=...)` | metadata + 10 example objects — light first look |
| `inspect_ecotaxa_project_schema(project_id=...)` | column/field list before export |
| `inspect_ecotaxa_column(project_id=..., column_name=...)` | distribution of one column |
| `compare_ecotaxa_projects(project_ids=[...])` | schema diff before multi-project export |
| `get_ecotaxa_sample(sample_id=...)` | full metadata of one sample (no taxa) |
| `resolve_ecotaxa_sample(reference=..., project_id=...)` | resolve a label/station/profile to sample_id |
| `list_ecotaxa_sample_objects(sample_id=...)` | paginated object list, read-only (no export) |
| `get_ecotaxa_object(object_id=...)` | detail of one object from `list_ecotaxa_sample_objects` |
| `describe_ecotaxa_project_coverage(project_id=...)` | cache vs network reconciliation |

**resolve_ecotaxa_sample priority rule:** when the user gives a label,
station, profile, deployment, or numeric ID without a grounded project,
call `resolve_ecotaxa_sample` immediately — do not call the RAG, do not
guess a project, do not explain a procedure instead of executing.

---

## Common chains

| User intent | Tool chain |
|---|---|
| "samples en Baie de Baffin 2024" | `query_ecotaxa_cache` WHERE iho_zone LIKE '%Baffin%' AND date_min >= '2024-01-01' |
| "projets en Baie de Baffin 2024" | `query_ecotaxa_cache` WHERE iho_zone LIKE '%Baffin%' GROUP BY project_id |
| "samples par année en Baie de Baffin" | `query_ecotaxa_cache` WHERE iho_zone LIKE '%Baffin%' GROUP BY strftime('%Y', date_min) |
| "zones les moins échantillonnées" | `query_ecotaxa_cache` GROUP BY iho_zone ORDER BY COUNT(DISTINCT profile_id) ASC |
| "groupe les samples du projet 17498 par zone" | `query_ecotaxa_cache` WHERE project_id = 17498 GROUP BY iho_zone |
| "samples LOKI dans Baie de Baffin" | `query_ecotaxa_cache` WHERE iho_zone LIKE '%Baffin%' AND instrument = 'Loki' |
| "carte positions samples + nb prédits" | cache SQL → `summarize_ecotaxa_samples` → `run_pandas` join → `run_graph` (scénario C) |
| "samples avec Calanus en mer du Labrador" | `find_ecotaxa_observations(taxon="Calanus", zone_name=...)` |
| "combien de Calanus validés dans ces 3 projets" | `count_ecotaxa_taxa(project_ids=[...], taxa=["Calanus"])` |
| "scan / état des images de ces samples" | `summarize_ecotaxa_samples(sample_ids=[...])` |
| "browse les objets du sample 123" | `list_ecotaxa_sample_objects(sample_id=123)` (read-only, pas de download) |
| "télécharge / analyse le sample 123" | `query_ecotaxa_sample(sample_id=123)` → `load_file` → `run_pandas` |
| "tous les objets des samples 123 et 456 (même projet X)" | `query_ecotaxa(project_id=X, sample_ids=[123,456])` → `load_file` |
| "tous les objets des samples 123 et 456 (projets diff)" | `export_ecotaxa_samples(sample_ids=[123,456], confirmed=False)` → confirmation → `load_file` |
| "filtre Calanus sur ces objets" | après download → `run_pandas` |
| "exporte cette sélection" | `export_ecotaxa_samples(sample_ids=[...], confirmed=False)` then user confirms |
| "les colonnes de ce projet" | `inspect_ecotaxa_project_schema(project_id=...)` |
| "ces 3 projets sont-ils compatibles" | `compare_ecotaxa_projects(project_ids=[...])` |
| "qu'y a-t-il dans le projet 1165 ?" | `preview_ecotaxa_project(1165)` |

---

## Runtime routing contract

- For any EcoTaxa navigation request with a named zone: (1) `load_skill("ecotaxa_navigation")`, (2) `query_ecotaxa_cache` with `WHERE iho_zone = '...'` — do NOT call `get_zone_info` for zone filtering.
- With multiple named zones, use `WHERE iho_zone IN ('Zone A', 'Zone B')` or a `CASE iho_zone` label before graphing — never plot only the last selection.
- Do not use paginated object browsing in an agent workflow: one page is incomplete, non-persistent, and cannot support analysis. A request to export objects goes directly to the narrowest export path.
- For ANY object-level graph, map, distribution, histogram, depth profile, or aggregate over objects: propose an export (`query_ecotaxa_sample` / `query_ecotaxa` / `export_ecotaxa_samples`) — the paginated API (max 200) cannot back a graph. Never build a graph from a `list_ecotaxa_sample_objects` page.
- EcoTaxa dry-run export ("prépare l'export", "mais ne lance rien"): call `export_ecotaxa_samples(..., confirmed=False)` — do not stop after loading the skill.
- After a previous `EXPORT_FAILED` / rights failure: use `preview_ecotaxa_project(project_id=...)` to verify access; do not call `query_ecotaxa` or `export_ecotaxa_samples`.
- For distribution/stats on one column: `inspect_ecotaxa_column(project_id=..., column_name=...)`.
- Preserve EcoTaxa source links: `https://ecotaxa.obs-vlfr.fr/prj/{project_id}` and `?samples={sample_id}`.
- A no-export approximation uses `summarize_ecotaxa_samples(sample_ids=[...])`. Exact per-sample counts for one taxon require an export/download path with confirmation.
