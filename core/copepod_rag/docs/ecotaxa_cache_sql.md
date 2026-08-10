# Cache SQLite EcoTaxa — référence de navigation
# Format RAG — chaque section délimitée par `---` est un chunk autonome

---

# Ce que le cache EcoTaxa permet, et sa limite objet

Mots-clés : EcoTaxa, cache SQLite, SQL, sample, objet, export, granularité, échantillon

Le cache EcoTaxa est une source locale en lecture seule, organisée au niveau
échantillon. Il répond directement aux questions de découverte, filtre, jointure,
compte, regroupement, zone, date, profondeur, station, cast et instrument. La
source de vérité immédiate reste son schéma réel : si une table ou colonne est
incertaine, l’inspecter avant d’écrire SQL.

Le cache ne fournit pas les valeurs individuelles d’objet nécessaires à une
abondance taxonomique exacte, une morphométrie, un score de classification ou
une analyse par bande de profondeur objet. Dans ce cas, résoudre d’abord la
sélection d’échantillons avec SQL, puis préparer l’export objet confirmé. Ne
jamais remplacer des valeurs objet manquantes par les compteurs d’enveloppe du
cache.

---

# Tables centrales et grain d’analyse EcoTaxa

Mots-clés : samples_cache, projects_cache, sample_id, project_id, station, profile, cast, colonnes EcoTaxa

`samples_cache` contient une ligne par échantillon EcoTaxa. Ses identifiants
stables sont `sample_id` et `project_id`. Les principaux champs de contexte
sont `original_id`, `station_id`, `profile_id` (cast/profil), `cruise_id`,
`ctd_rosette_filename`, `instrument`, `lat_avg`, `lon_avg`, `iho_zone` et
`zone_reference`.

Les statistiques au niveau sample sont `object_count`, `nb_validated`,
`nb_predicted`, `nb_dubious` et `nb_unclassified`. Elles sont autoritatives à
ce niveau, mais ne deviennent pas des comptages taxonomiques individuels.
`used_taxa` est une liste JSON d’identifiants taxonomiques observés.

`projects_cache` contient une ligne par projet synchronisé : `project_id`,
`title`, `instrument`, `description`, `status`, `contact_name`, `objcount`,
`pctvalidated`, `pctclassified` et `last_synced`. Joindre cette table par
`project_id` dès qu’un libellé ou une métadonnée de projet est demandé.

Compter les samples par `COUNT(DISTINCT sample_id)` et les casts par
`COUNT(DISTINCT profile_id)`. Une station est une localisation : elle ne doit
ni devenir un cast, ni être traitée comme une mesure numérique.

---

# Route SQL cache et tables persistantes

Mots-clés : SELECT, WITH, CTE, schema, SQL EcoTaxa, selection_name, table persistante, requête lecture seule

La route normale est : découvrir les tables si le schéma est inconnu, décrire
une table si les types/index sont nécessaires, puis lancer un unique `SELECT`
ou `WITH`/CTE read-only. Les jointures, sous-requêtes, agrégations et filtres
sont autorisés. Ne pas ajouter `LIMIT` sauf demande explicite d’aperçu, top ou
pagination.

Une requête renvoyant `sample_id` devient une sélection persistante ; lui donner
un nom descriptif afin de réutiliser exactement le même périmètre pour une
analyse, une carte ou un export. Ne pas rejouer une requête identique à la
suite : réutiliser sa table persistante. Les résultats SQL servent de base à
pandas pour les dérivations et à Matplotlib/Cartopy pour les visuels.

Pour joindre directement un DataFrame de session au cache, fournir son nom
persistant exact dans `dataframe_refs` de `query_ecotaxa_cache`. Chaque référence
déclarée devient une table de même nom dans une base SQLite en mémoire ; les
tables EcoTaxa y sont attachées en lecture seule et gardent leurs noms usuels.
Un `df_*` absent de `dataframe_refs` n'existe pas dans l'espace SQL.

Exemple conceptuel :

```sql
SELECT net.sample_id AS net_sample_id,
       uvp.sample_id AS uvp_sample_id,
       uvp.profile_id,
       net.station_name,
       net.deployment_datetime_start,
       uvp.datetime_min
FROM df_file_neolabs_sample AS net
JOIN samples_cache AS uvp
  ON LOWER(TRIM(uvp.station_id)) = LOWER(TRIM(net.station_name))
WHERE uvp.instrument LIKE 'UVP%';
```

Cet exemple exige
`dataframe_refs=["df_file_neolabs_sample"]`. La base temporaire et les copies
SQL disparaissent après la requête ; seul le résultat persistant conserve la
description, le SQL et `input_dataframes`. Utiliser ce pont pour une vraie
jointure tabulaire plutôt que sérialiser une longue liste de valeurs dans
`IN (...)`.

Workflow attendu de l'agent :

1. lire l'inventaire des DataFrames et choisir la table exacte selon sa
   description, son grain et ses colonnes ;
2. déclarer dans `dataframe_refs` chaque table `df_*` mentionnée par le SQL ;
3. préparer le grain source dans une CTE avec un identifiant réel. Une station
   ou un numéro de cast réutilisable ne suffit pas à dédupliquer ;
4. joindre directement la CTE aux tables EcoTaxa dans un unique SELECT ;
5. retourner les identifiants locaux et EcoTaxa ainsi que les deltas/états de
   correspondance. Pour créer une sélection EcoTaxa exportable, nommer
   l'identifiant EcoTaxa `sample_id` ;
6. fournir une `description` indiquant les DataFrames montés, filtres SQL, grain
   de sortie, rôle analytique et familles de colonnes ;
7. conserver tous les candidats ambigus et, pour un audit de couverture, les
   lignes locales sans correspondance avec un `LEFT JOIN`.

Pour filet/NeoLabs ↔ UVP, utiliser le fichier sample au grain prélèvement,
normaliser la station, filtrer `instrument LIKE 'UVP%'`, puis calculer :

```sql
ABS((julianday(uvp.datetime_min) - julianday(net.net_datetime)) * 24.0)
  AS time_delta_h
```

Appliquer ensuite `time_delta_h <= seuil_h`, avec le seuil demandé par
l'utilisateur. La même station normalisée suffit : ne pas ajouter de seuil de
distance. Une table abundance au grain taxon/analyse ne remplace jamais la
table sample pour établir les déploiements.

Exemple de sélection d’une zone et période :

```sql
SELECT sample_id, project_id, original_id, profile_id, station_id,
       lat_avg, lon_avg, iho_zone, date_min, date_max, instrument
FROM samples_cache
WHERE iho_zone = 'Baie de Baffin'
  AND metadata_complete = 1
  AND date_min <= '2024-12-31'
  AND date_max >= '2024-01-01';
```

---

# Zones, temps, profondeur et données incomplètes

Mots-clés : iho_zone, zone_reference, IHO, MEOW, OUTSIDE, coordonnées manquantes, date, profondeur, couverture

`iho_zone` est le libellé géographique mis en cache et `zone_reference` indique
son système : `IHO`, `MEOW`, `OUTSIDE` ou `MISSING_COORDINATES`. Toute
agrégation par zone sélectionne et groupe les deux colonnes. Ne jamais mélanger
IHO et MEOW dans un même total, classement ou encodage de légende.

Pour une zone explicitement nommée, utiliser l’égalité sur le libellé canonique,
pas `LIKE`. Dans une vue globale, ne pas éliminer les lignes où `iho_zone` est
NULL : elles correspondent à de vrais samples sans coordonnées utilisables et
doivent apparaître comme telles.

Les dates et profondeurs sont des enveloppes dérivées d’objets :
`date_min`/`date_max` et `depth_min`/`depth_max`. Une intersection d’intervalle
utilise `minimum <= borne_fin AND maximum >= borne_début`. Toute affirmation
exacte vérifie la complétude appropriée : `metadata_complete`, `depth_complete`
et, pour l’heure, `missing_time_count = 0`. Les exclusions pour incomplétude
sont rapportées comme inconnues, jamais comme absentes.

---

# Joindre les projets et résumer le cache sans double compte

Mots-clés : jointure projects_cache, project_id, projet, titre, V P D U, object_count, group by, EcoTaxa

Pour afficher des métadonnées de projet, joindre `samples_cache` à
`projects_cache` par `project_id`. Préserver le grain sample avant de sommer
des compteurs : une jointure vers plusieurs lignes objet peut sinon multiplier
artificiellement `object_count` et les compteurs V/P/D/U.

Exemple de résumé par projet :

```sql
SELECT sc.project_id, p.title,
       COUNT(DISTINCT sc.sample_id) AS n_samples,
       SUM(sc.object_count) AS n_objects,
       SUM(sc.nb_validated) AS n_validated,
       SUM(sc.nb_predicted) AS n_predicted,
       SUM(sc.nb_dubious) AS n_dubious,
       SUM(sc.nb_unclassified) AS n_unclassified
FROM samples_cache AS sc
LEFT JOIN projects_cache AS p USING (project_id)
GROUP BY sc.project_id, p.title
ORDER BY n_samples DESC;
```

Les compteurs V/P/D/U proviennent de statistiques autoritatives EcoTaxa ; ne
pas les déduire de `object_count`, ni les employer comme abondance biologique
par taxon.

---

# Taxons dans le cache et frontière vers l’export objet

Mots-clés : used_taxa, json_each, taxon_id, Copepoda, taxonomie EcoTaxa, objets, export confirmé

Le cache stocke les identifiants taxonomiques observés dans `used_taxa`, pas un
dictionnaire complet de noms. Résoudre d’abord un nom taxonomique avec l’outil
de taxonomie dédié, puis trouver les samples concernés avec `json_each` :

```sql
SELECT s.sample_id, s.project_id, s.original_id, s.iho_zone
FROM samples_cache AS s
WHERE EXISTS (
  SELECT 1 FROM json_each(s.used_taxa)
  WHERE CAST(value AS INTEGER) = :taxon_id
);
```

Cette requête indique la présence d’un taxon dans un sample. Elle ne donne ni
abondance par taxon, ni morphométrie, ni statut objet exact. Ces demandes
nécessitent l’export objet du périmètre SQL déjà résolu, avec confirmation.
Après l’export, conserver `export_project_id` et la provenance lors des calculs
ou graphes multi-projets.

---

# Carte EcoTaxa à partir du résultat SQL

Mots-clés : carte EcoTaxa, Cartopy, profile_id, station, échantillon, coordonnées, map

Une carte EcoTaxa part d’une requête SQL ramenant au minimum `sample_id`,
`lat_avg`, `lon_avg`, `iho_zone` et la mesure demandée. Le résultat est ensuite
préparé au bon grain : une marque par sample, station ou cast/profil selon la
question ; agréger les coordonnées coïncidentes quand elles représenteraient
autrement un empilement illisible. Une ligne taxonomique ou un objet n’est pas
automatiquement une station.

La figure est une carte Cartopy avec coordonnées réelles et géométrie autorisée.
Ne pas substituer un nuage longitude–latitude à une carte. Si une mesure est
encodée par taille ou couleur, elle doit provenir de la table SQL et conserver
son unité ; les identifiants de sample/profil/station restent des libellés.
