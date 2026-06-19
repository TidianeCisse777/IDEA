# Enrichissement Environnemental — Catalogue Des Demandes Utilisateur

Ce document répertorie les types de demandes auxquelles l'agent peut répondre
quand l'utilisateur veut enrichir un fichier chargé (EcoTaxa, EcoPart, fichier
lab, etc.) avec des variables environnementales venant des trois sources
autorisées : Amundsen CTD, OGSL ISMER CTD et Bio-ORACLE.

L'enrichissement vise à ajouter des colonnes environnementales à une table
déjà en session, sans rejouer l'analyse en aval. Toutes les colonnes sources
sont préservées, et chaque enrichissement persiste son résultat sous une
variable dédiée (`df_amundsen_enriched_*`, `df_ogsl_enriched_*`,
`df_bio_oracle_enriched_*`) accessible ensuite via `run_pandas` ou `run_graph`.

## 0. Modes De Matching Disponibles

Quatre stratégies coexistent, choisies par l'agent selon les colonnes
présentes dans le fichier source. Les modes A, B, D restent disponibles via
les tools « legacy » pour les cas spécifiques où le fichier porte les
identifiants natifs ; le mode C est le chemin par défaut.

| Mode | Quand l'utiliser | Colonnes requises | Tolérances | Sources |
|---|---|---|---|---|
| **A. Amundsen par station + cast** | Fichier qui porte déjà `station` + `cast_number` Amundsen (typique EcoPart). | `station_column`, `cast_column` (+ `depth_column` optionnel, recommandé) | Aucune tolérance spatiale ou temporelle. Lookup exact par paire `(station, cast)`. Profondeur : nearest dans le profil retourné. | Amundsen seulement |
| **B. OGSL par stationID** | Fichier qui porte déjà un `stationID` OGSL et la date de sampling. | `station_column`, `time_column` (+ `depth_column` optionnel) | `time_tolerance_hours=24` (défaut) autour de chaque station. `depth_tolerance_m=10` (défaut) si `depth_column` fourni. | OGSL seulement |
| **C. Nearest-neighbour par lat/lon/time** | Cas par défaut — fichiers EcoTaxa, exports lab, fichiers de filets avec coordonnées et date sans identifiant natif. | `latitude_column`, `longitude_column`, `time_column` (+ `depth_column` optionnel). Auto-détectés si non fournis. | `spatial_tolerance_km=25` (défaut). `time_tolerance_hours=24` (défaut). Bio-ORACLE n'utilise pas ces tolérances (grille fixe). | Amundsen, OGSL, Bio-ORACLE |
| **D. Top-N stations Bio-ORACLE** | Construire une table stationnaire à partir d'un fichier zooplancton et l'enrichir, en se limitant aux N stations les plus échantillonnées. | `latitude_column`, `longitude_column`, `station_column` (+ `sample_column` pour le décompte, + `top_n_stations`). | Aucune. Lookup point Bio-ORACLE par station unique. | Bio-ORACLE seulement |

## 0bis. Méthode D'approximation (mode C)

Le mode C — nearest-neighbour par lat/lon/temps — est le seul qui approche.
Voici exactement comment l'agent procède pour Amundsen et OGSL :

1. **Détection des colonnes source.** L'agent reconnaît
   `latitude` / `lat` / `object_lat` / `sample_lat` / `latitude (degrees_north)` ;
   `longitude` / `lon` / `object_lon` / `sample_long` / `sample_lon` /
   `longitude (degrees_east)` ;
   `object_date` / `time` / `date` / `sampling_date` / `yyyy-mm-dd hh:mm` /
   `datetime` ; et pour la profondeur `object_depth_min` / `depth` /
   `pressure` / `pres` / `Depth [m]` / `depth_m`. Les noms sont matchés en
   case-insensitive. L'utilisateur peut forcer un nom via les paramètres
   `latitude_column`, `longitude_column`, `time_column`, `depth_column`.
2. **Validation.** Si une des trois séries lat/lon/time est entièrement
   vide après parsing numérique/datetime, l'enrichissement est refusé avec
   un diagnostic explicite — pas d'appel ERDDAP.
3. **Bbox + fenêtre temps.** L'agent calcule l'enveloppe spatiale
   (`min` − 0.25°, `max` + 0.25° sur lat et lon) et l'enveloppe temporelle
   (`min` − 24 h, `max` + 24 h par défaut ; pour OGSL le padding temporel
   vaut `time_tolerance_hours`). Une seule requête ERDDAP couvre toutes
   les lignes source — pas N requêtes.
4. **Match au plus proche voisin, ligne par ligne.** Pour chaque ligne :
   a. **Filtrage temporel.** On ne garde que les mesures CTD dans la
      fenêtre `±time_tolerance_hours` autour de la date source.
   b. **Distance Haversine.** Calcul de la distance grand-cercle (rayon
      terrestre 6371 km) entre la ligne source et chaque mesure CTD
      restante.
   c. **Tolérance spatiale.** Si le plus proche voisin est au-delà de
      `spatial_tolerance_km`, statut → `no_match`.
   d. **Sélection de la mesure CTD dans le profil.** Quand plusieurs
      mesures CTD partagent la même distance (même profil), si la ligne
      source a une profondeur, on prend celle dont `PRES` est la plus
      proche. Sinon on prend la première (généralement la surface).
   e. **Statut.** `matched` si la mesure retenue a une valeur non-nulle
      pour les variables demandées, `matched_no_value` si toutes les
      variables demandées sont NaN sur la ligne retenue.
5. **Tracage de la qualité.** Chaque ligne enrichie reçoit
   `*_distance_km` (distance Haversine en km à la mesure retenue) et
   `*_time_delta_min` (écart en minutes entre la date source et la date
   CTD retenue).

Pour Bio-ORACLE en mode C, l'approche est plus simple : pas de bbox/window,
pas de tolérances. L'agent fait un appel ERDDAP par point unique
`(lat, lon, variable, scenario, depth_layer, target_year)` et déduplique
via un cache. Hors plage WGS84 ou hors grille → `no_value`.

## 1. Découvrir Les Sources Disponibles

L'utilisateur peut demander :

- `Quelles sources environnementales sont disponibles ?`
- `Liste les datasets Amundsen.`
- `Liste les datasets Bio-ORACLE.`
- `Quelles variables CTD posso-je récupérer dans Amundsen ?`
- `Quelles variables Bio-ORACLE existent ?`
- `Quels scénarios climatiques Bio-ORACLE sont supportés ?`

L'agent peut répondre avec :

- `dataset_id`, titre, lien griddap pour Amundsen et Bio-ORACLE ;
- liste des variables Bio-ORACLE acceptées (`temperature`, `salinity`,
  `oxygen`, `chlorophyll`, `nitrate`) ;
- liste des scénarios climatiques (`baseline`, `SSP1-2.6`, `SSP2-4.5`,
  `SSP5-8.5`) ;
- pour Amundsen : couverture spatiale (Arctique canadien, mer de Beaufort,
  baie de Baffin, etc.) ;
- pour OGSL : couverture du Saint-Laurent et du golfe par ISMER.

## 2. Prévisualiser Une Variable À Un Point

L'utilisateur peut demander :

- `Quelle est la température Bio-ORACLE à 58.7°N, -86.3°W en baseline ?`
- `Aperçu du profil CTD Amundsen pour la station BRK-15.`
- `Donne-moi la valeur Bio-ORACLE pour ce point en SSP5-8.5 horizon 2050.`
- `Préview rapide d'un profil Amundsen avant d'enrichir.`

L'agent peut répondre avec :

- valeur ponctuelle d'une variable Bio-ORACLE à (lat, lon) ;
- profil CTD complet d'une station / cast Amundsen (premières lignes) ;
- variable, scénario, couche de profondeur (`surface` par défaut), année
  cible ;
- `dataset_id` et timestamp de la valeur retournée.

## 3. Charger Un Profil CTD Ou Un Dataset Complet

L'utilisateur peut demander :

- `Charge le profil CTD complet de la station BRK-15 cast 7.`
- `Récupère le dataset Bio-ORACLE température SSP5-8.5 sur une région.`
- `Télécharge l'export Amundsen pour cette station.`

L'agent peut répondre avec :

- TSV téléchargeable persisté dans la session (variable `df_ctd`,
  `df_bio_oracle`, etc.) ;
- nombre de lignes ;
- URL de téléchargement ;
- métadonnées du dataset (station, cast, dates).

Ces appels sont des opérations « lourdes » et demandent une confirmation
utilisateur explicite avant exécution.

## 4. Enrichir Un Fichier Avec La CTD Amundsen Par Lat/Lon/Temps

C'est le cas par défaut quand le fichier chargé contient des coordonnées et
une date, sans station/cast Amundsen explicite (fichiers EcoTaxa, exports
lab, fichiers de filets).

L'utilisateur peut demander :

- `Enrichis ce fichier avec la CTD Amundsen.`
- `Ajoute la température et la salinité Amundsen à mon TSV.`
- `Joins les profils Amundsen au plus proche voisin spatio-temporel.`
- `Enrichis avec Amundsen, tolérance 50 km et 48 h.`

L'agent peut répondre avec :

- détection automatique des colonnes `latitude`, `longitude`, `time`,
  `depth` du fichier source ;
- une seule requête ERDDAP bbox + fenêtre temps pour toutes les lignes ;
- match au plus proche voisin (Haversine + fenêtre temps) avec choix de la
  mesure CTD la plus proche en profondeur quand `depth` est disponible ;
- colonnes ajoutées : `amundsen_match_status`, `amundsen_dataset_id`,
  `amundsen_station`, `amundsen_cast_number`, `amundsen_time`,
  `amundsen_distance_km`, `amundsen_time_delta_min`, `amundsen_pres_dbar`,
  `amundsen_te90_degC`, `amundsen_psal_psu` ;
- statuts par ligne : `matched`, `matched_no_value`, `no_match` ;
- bloc « Méthode » à la fin de la réponse listant colonnes détectées,
  tolérances, variables récupérées, comptes par statut ;
- persistance dans `df_amundsen_enriched_<id>`.

## 5. Enrichir Un Fichier Avec OGSL ISMER CTD Par Lat/Lon/Temps

Mêmes signatures, dataset OGSL ERDDAP, couverture Saint-Laurent + golfe.

L'utilisateur peut demander :

- `Enrichis ce fichier avec OGSL ISMER CTD.`
- `Ajoute température, salinité et oxygène OGSL.`
- `Joins l'oxygène dissous OGSL à mes samples du Saint-Laurent.`

L'agent peut répondre avec :

- détection automatique des colonnes lat/lon/temps/depth ;
- colonnes ajoutées : `ogsl_match_status`, `ogsl_dataset_id`,
  `ogsl_station_id`, `ogsl_cruise_id`, `ogsl_cast_number`, `ogsl_time`,
  `ogsl_distance_km`, `ogsl_time_delta_min`, `ogsl_pres_dbar`,
  `ogsl_te90_degC`, `ogsl_psal_psu`, `ogsl_oxym_umol_kg` ;
- statuts par ligne : `matched`, `matched_no_value`, `no_match` ;
- bloc « Méthode » ;
- persistance dans `df_ogsl_enriched_<id>`.

Hors couverture OGSL (Arctique canadien profond p. ex.), tous les statuts
remontent en `no_match` — l'agent le signale dans le bloc « Méthode ».

## 6. Enrichir Un Fichier Avec Bio-ORACLE Par Lat/Lon

L'utilisateur peut demander :

- `Enrichis mon csv avec Bio-ORACLE SSP5-8.5.`
- `Ajoute la température Bio-ORACLE par ligne.`
- `Bio-ORACLE baseline et SSP5-8.5 pour la salinité de surface.`
- `Compare baseline vs SSP1-2.6 vs SSP5-8.5 sur la température horizon 2050.`
- `Enrichis avec température + salinité + oxygène en surface.`

L'agent peut répondre avec :

- détection automatique des colonnes lat/lon ;
- déduplication des points uniques pour minimiser les appels ERDDAP ;
- une colonne par (variable × scénario), ex.
  `bio_oracle_temperature_ssp5_8_5` ;
- colonnes traçabilité par paire : `..._dataset_id`, `..._time` ;
- colonne globale `bio_oracle_match_status` (`matched`, `no_value`) ;
- bloc « Méthode » listant colonnes détectées, paramètres, comptes ;
- persistance dans `df_bio_oracle_enriched_<id>`.

`depth_layer` accepte `surface`, `mean`, `bottom`. `target_year` est utilisé
uniquement pour les scénarios SSP — il est ignoré pour `baseline`
(historique).

## 7. Cibler Un Fichier Précis Quand Plusieurs Sont En Session

Quand l'utilisateur a chargé plusieurs fichiers (par ex. un filet et un UVP),
les enrichissements opèrent par défaut sur le DataFrame courant (le dernier
chargé). Pour enrichir un fichier précis :

L'utilisateur peut demander :

- `Enrichis le fichier filet avec Bio-ORACLE.`
- `Enrichis l'UVP avec Amundsen.`
- `Enrichis les deux fichiers indépendamment avec OGSL.`

L'agent passe alors `source_variable="df_file_<nom>"` au tool, et persiste
chaque résultat sous une variable distincte (`df_amundsen_enriched_*`,
`df_ogsl_enriched_*`, etc.).

## 8. Chaîner Plusieurs Enrichissements Sur Le Même Fichier

L'utilisateur peut demander :

- `Enrichis avec Amundsen, puis avec OGSL, puis avec Bio-ORACLE.`
- `Ajoute toutes les variables CTD disponibles.`
- `Compare les températures Amundsen, OGSL et Bio-ORACLE pour chaque ligne.`

L'agent peut empiler les enrichissements : chaque étape utilise le snapshot
précédent comme source via `source_variable`, et le DataFrame final cumule
les colonnes des trois sources (`amundsen_*`, `ogsl_*`, `bio_oracle_*`)
plus toutes les colonnes d'origine.

## 9. Comprendre Les Statuts D'enrichissement

Chaque ligne enrichie reçoit un `*_match_status`. L'utilisateur peut
demander :

- `Combien de lignes ont matché ?`
- `Pourquoi cette ligne est en no_match ?`
- `Combien de lignes matchées mais sans valeur ?`

L'agent peut répondre avec :

- `matched` : un profil/point CTD a été trouvé dans les tolérances ET la
  variable demandée a une valeur ;
- `matched_no_value` : profil trouvé mais variables CTD vides à l'origine
  (cas Amundsen / OGSL) ;
- `no_match` : aucun profil dans la zone-temps avec les tolérances
  spatiale + temporelle données ;
- `no_value` : pour Bio-ORACLE, point hors grille (souvent terre ou bord) ;
- pour les statuts négatifs, l'agent signale la cause probable
  (zone hors couverture, fichier sans coordonnées, valeurs entièrement
  vides dans la colonne `latitude`/`longitude`/`time`).

Les colonnes `*_distance_km` et `*_time_delta_min` documentent la qualité
de chaque match.

## 10. Cas Spécifiques — Enrichissement Par Identifiants Explicites

Les fichiers qui portent déjà des identifiants natifs des sources peuvent
être enrichis via les tools « legacy », qui restent disponibles pour ces
cas précis. Chacun produit son propre jeu de colonnes — distinct du
mode C.

### 10.A — Mode A : Amundsen par station + cast

Quand l'utilisateur demande :

- `Enrichis ce fichier EcoPart avec Amundsen — il a déjà station et cast.`
- `Joins le profil CTD Amundsen via station + cast_number + depth.`

L'agent route vers le tool dédié et passe explicitement `station_column`,
`cast_column`, et `depth_column` (recommandé). Le tool fait UNE requête
Amundsen par paire `(station, cast_number)` unique, choisit la mesure CTD
dont la profondeur est la plus proche de `depth_column`, puis recolle
ces colonnes au fichier d'origine :

- `ctd_match_status` (`matched`, `no_match`, `missing_sample_metadata`) ;
- `amundsen_nearest_time` ;
- `amundsen_nearest_lat`, `amundsen_nearest_lon` ;
- `amundsen_nearest_depth_m`, `amundsen_nearest_depth_delta_m` (écart
  source ↔ CTD en m) ;
- `amundsen_temperature_degC_nearest` (lit `TE90` puis `Temp`) ;
- `amundsen_salinity_psu_nearest` (lit `PSAL` puis `Sal`) ;
- `amundsen_station`, `amundsen_cast_number`.

Si le fichier n'a ni station/cast ni lat/lon/time, le tool retourne un
diagnostic traçable avec `ctd_match_status=missing_sample_metadata` au
lieu d'une erreur opaque. Le tool accepte aussi `max_rows` pour limiter
les premières N lignes lors d'un test.

### 10.B — Mode B : OGSL par stationID

Quand l'utilisateur demande :

- `Joins OGSL via la colonne stationID.`
- `Enrichis ces stations OGSL avec température, salinité, oxygène.`

L'agent passe `station_column`, `time_column`, `depth_column` optionnel,
plus la liste `variables` (codes OGSL : `PRES`, `TE90`, `PSAL`, `OXYM`).
Le tool calcule une fenêtre temps padded par `time_tolerance_hours=24`
autour de chaque station unique, fait une requête OGSL par station,
puis matche localement chaque ligne source à la mesure OGSL la plus
proche en temps (≤ `time_tolerance_hours`) et en profondeur
(≤ `depth_tolerance_m=10` si `depth_column` est fourni).

Colonnes produites (préfixe `ogsl_`, sans suffixe d'unité dans ce mode) :

- `ogsl_match_status` (`matched`, `no_match`, `missing_station`,
  `missing_time`, `invalid_time`, `missing_depth`, `invalid_depth`) ;
- `ogsl_station_id`, `ogsl_cruise_id`, `ogsl_cast_number` ;
- `ogsl_time`, `ogsl_time_delta_min` ;
- `ogsl_pres`, `ogsl_depth_delta_m` ;
- une colonne par variable demandée, en minuscules : `ogsl_te90`,
  `ogsl_psal`, `ogsl_oxym` (≠ des suffixes d'unités du mode C).

Le tool exige une confirmation explicite si plus de 10 stations uniques
sont détectées (chaque station = une requête HTTP). Deux datasets sont
persistés : le brut `df_ogsl` et l'enrichi `df_ogsl_enriched_*`.

### 10.D — Mode D : Top-N stations Bio-ORACLE

Quand l'utilisateur demande :

- `Couple les top 10 stations zooplancton avec Bio-ORACLE.`
- `Compare baseline et SSP5-8.5 sur les 5 stations les plus échantillonnées.`

L'agent passe `latitude_column`, `longitude_column`, `variable`,
`scenario` (ou `scenarios` pour plusieurs), `depth_layer`, plus
`station_column`, `sample_column` (pour le décompte), et
`top_n_stations`. Le tool construit en interne une table stationnaire
agrégée (1 ligne par station, triée par nombre de samples décroissant,
limitée aux N premières), puis appelle Bio-ORACLE une fois par point
unique.

Colonnes produites (≠ mode C — pas de préfixe `bio_oracle_`) :

- pour un seul scénario : `<variable>_<scenario_clean>`, `time`,
  `dataset_id` ;
- pour plusieurs scénarios : `<variable>_<scenario_clean>` par scénario,
  `time_<scenario_clean>`, `dataset_id_<scenario_clean>` ;
- `n_samples` (décompte de samples par station) quand `top_n_stations`
  est passé.

Persisté sous `df_bio_oracle_coupling_*`.

Pour la majorité des fichiers EcoTaxa / lab sans identifiants natifs ni
besoin de top-N, le chemin par défaut reste le mode C (sections 4-6).

## 11. Inspecter Et Analyser Le Résultat Enrichi

Après un enrichissement, l'utilisateur peut demander :

- `Affiche les 10 premières lignes enrichies.`
- `Trace température Amundsen vs profondeur du sample.`
- `Compare Bio-ORACLE baseline et SSP5-8.5 par station.`
- `Filtre les lignes matchées dans la baie de Baffin.`
- `Exporte le fichier enrichi en TSV.`

L'agent peut répondre avec :

- table markdown des colonnes pertinentes ;
- graphiques (matplotlib via `run_graph`) ;
- statistiques par groupe via `run_pandas` ;
- lien de téléchargement du TSV/CSV enrichi ;
- export d'un livrable PDF synthétisant les résultats.

## 12. Confirmer Avant Une Opération Coûteuse

Certaines combinaisons sont volumineuses et demandent confirmation explicite
avant exécution :

- `enrich_with_bio_oracle` sur plus de 10 lignes avec plusieurs
  `variables × scenarios` (multiplie les appels ERDDAP) ;
- `query_amundsen_ctd` complet sur tout le dataset ;
- `query_bio_oracle` sur une région entière (pas un point) ;
- toute chaîne d'enrichissement combinée à un export `export_deliverable`.

L'agent annonce d'abord son plan et attend `oui / go / lance / confirme`.

## 13. Ce Que L'utilisateur Ne Peut Pas Demander

L'enrichissement par lat/lon/temps ne sert pas à :

- modifier les valeurs d'origine du fichier source ;
- inventer une valeur quand la zone-temps n'est pas couverte par la source
  (le statut reste `no_match`, jamais une extrapolation) ;
- enrichir un fichier sans colonnes `latitude` / `longitude` exploitables —
  l'agent retourne alors un diagnostic explicite ;
- proposer une interprétation scientifique des résultats (les valeurs sont
  livrées brutes, sans lecture biologique automatique) ;
- garantir une variable comme `oxygen` si elle n'existe pas dans le profil
  CTD trouvé (le statut devient `matched_no_value`) ;
- contourner les tolérances : un point à plus de `spatial_tolerance_km` ou
  hors de `time_tolerance_hours` reste `no_match`. Pour assouplir, il faut
  passer explicitement les paramètres au tool ;
- enrichir depuis une source non autorisée (OBIS, World Ocean Atlas, etc.).
