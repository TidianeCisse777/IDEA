# colonnes_sources.md
# Colonnes des sources de données — EcoTaxa / EcoPart / CTD externe
# Référence générique basée sur des exports réels, sans dépendre d'un projet particulier
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Comment les sources EcoTaxa, EcoPart et CTD s'articulent-elles ?

Mots-clés : EcoTaxa, EcoPart, CTD, source, objet individuel, profil, bin profondeur, volume échantillonné, concentration, jointure

Trois familles de sources sont complémentaires :

```text
Instrument d'imagerie (UVP5, UVP6, LOKI, ZooScan, FlowCam)
        ↓
    [EcoPart]   — particules agrégées + CTD + volume échantillonné (niveau profil/bin)
        ↓
    [EcoTaxa]   — objets individuels + classification taxonomique (niveau vignette)

    [CTD externe] — référence physico-chimique indépendante (navire, rosette, plateforme)
```

**Règles fondamentales :**
- EcoTaxa = objets individuels avec taxon, morphométrie éventuelle et métadonnées d'acquisition.
- EcoPart = profils agrégés avec bins de profondeur, variables environnementales et volume échantillonné.
- Pour calculer une concentration d'organismes à partir d'objets EcoTaxa, il faut un volume échantillonné, généralement obtenu via EcoPart ou métadonnées instrument.
- Une CTD externe donne un contexte physico-chimique indépendant ; elle doit être jointe par proximité temps/position/profondeur sauf clé explicite.

---

# Quels schémas de colonnes EcoTaxa peut-on rencontrer ?

Mots-clés : EcoTaxa, schéma colonnes, object_*, obj_*, fre_*, txo_*, sample_*, process_*, acq_*, alias

EcoTaxa n'utilise pas un seul schéma universel. Les préfixes dépendent de l'instrument, de la version d'export et du traitement.

Schémas fréquents :

| Famille | Colonnes typiques | Usage |
|---------|-------------------|-------|
| Métadonnées objet modernes | `object_id`, `object_lat`, `object_lon`, `object_date`, `object_time`, `object_depth_min`, `object_depth_max` | Identifiant, position, temps, profondeur |
| Métadonnées objet alternatives | `obj_orig_id`, `obj_objdate`, `obj_objtime`, `obj_latitude`, `obj_longitude`, `obj_depth_min`, `obj_depth_max` | Ancien/export alternatif, souvent utile pour jointures |
| Taxonomie validée | `object_annotation_category`, `object_annotation_hierarchy`, `txo_display_name` | Nom de taxon selon le schéma exporté |
| Morphométrie objet | `object_area`, `object_feret`, `object_esd`, `object_major`, `object_minor` | Mesures image, souvent en pixels |
| Morphométrie alternative | `fre_area`, `fre_feret`, `fre_esd`, `fre_major`, `fre_minor` | Mesures image sous préfixe `fre_*` |
| Morphométrie LOKI / skimage | `fre_equivalent_diameter_area`, `fre_axis_major_length`, `fre_axis_minor_length`, `fre_feret_diameter_max`, `fre_intensity_mean` | Mesures image issues de champs libres EcoTaxa |
| Sample/profil | `sample_id`, `sample_profileid`, `sample_stationid`, `sample_cruise` | Regroupement par profil, station ou campagne |
| Acquisition | `acq_id`, `acq_instrument`, `acq_sn`, `acq_pixel`, `acq_volimage` | Instrument, calibration, volume par image |
| Acquisition LOKI | `acq_temperature_ctd`, `acq_salinity_ctd`, `acq_oxygen_concent`, `acq_fluo1`, `acq_raw_depth`, `acq_pixel_um_size` | CTD embarquée, capteurs et calibration image |
| Process | `process_id`, `process_software`, `process_pixel`, `process_calibration` | Traitement image et calibration |

Ne pas homogénéiser à l'aveugle : il faut d'abord détecter les colonnes présentes dans le TSV, puis appliquer les alias.

---

# Quelles colonnes identifiants, position, temps et profondeur chercher dans EcoTaxa ?

Mots-clés : object_id, obj_orig_id, sample_id, sample_profileid, latitude, longitude, date, time, depth_min, depth_max, profondeur

| Concept | Colonnes possibles | Définition | Unité |
|---------|--------------------|------------|-------|
| Identifiant objet | `object_id`, `objid`, `obj_orig_id` | ID de l'objet ou ID original instrument | id/texte |
| Identifiant sample | `sample_id`, `sample_id_internal` | ID d'échantillon ou de profil | id |
| Profil instrument | `sample_profileid`, `sample_station_name`, profil extrait de `obj_orig_id` | Profil UVP, station LOKI ou série instrument | texte |
| Latitude | `object_lat`, `obj_latitude`, `sample_lat`, `sample_latitude` | Latitude objet ou sample | degrés décimaux |
| Longitude | `object_lon`, `obj_longitude`, `sample_long`, `sample_longitude` | Longitude objet ou sample | degrés décimaux |
| Date | `object_date`, `obj_objdate`, `sample_deployment_date_start`, `sample_deployment_datetime_start` | Date d'acquisition ou d'échantillonnage | date |
| Heure | `object_time`, `obj_objtime`, `sample_deployment_time_start`, `sample_deployment_time_start_str` | Heure d'acquisition ou d'échantillonnage | time |
| Profondeur min | `object_depth_min`, `obj_depth_min`, `sample_min_net_sampling_depth` | Profondeur minimale associée à l'objet ou au trait | m |
| Profondeur max | `object_depth_max`, `obj_depth_max`, `sample_max_net_sampling_depth` | Profondeur maximale associée à l'objet ou au trait | m |

**Profondeur de l'objet à calculer :**
```python
object_depth = (depth_min + depth_max) / 2
```

Ne jamais utiliser uniquement la profondeur minimale quand une profondeur max est disponible.

---

# Où trouver le taxon validé dans EcoTaxa ?

Mots-clés : taxon, annotation validée, object_annotation_category, object_annotation_hierarchy, txo_display_name, classif_auto_name, classif_auto_score

Le champ taxonomique principal dépend du schéma exporté.

| Colonnes possibles | Quand l'utiliser |
|--------------------|------------------|
| `object_annotation_category` | Schéma EcoTaxa avec préfixe `object_*`; champ principal pour le taxon annoté |
| `object_annotation_hierarchy` | Hiérarchie taxonomique complète associée à `object_annotation_category` |
| `txo_display_name` | Schéma avec préfixes `obj_*` / `txo_*`; champ d'affichage du taxon, souvent principal dans les exports LOKI |
| `classif_auto_name` | Classification automatique proposée ; ne remplace pas une annotation validée |
| `classif_auto_score` | Score de confiance automatique ; utile pour audit, pas pour taxonomie finale |

Priorité recommandée :
1. utiliser le taxon validé si présent (`object_annotation_category` ou `txo_display_name`) ;
2. vérifier le statut d'annotation (`object_annotation_status`) quand il existe ;
3. utiliser les colonnes automatiques seulement pour audit ou pré-tri.

---

# Quelles colonnes de morphométrie EcoTaxa sont importantes ?

Mots-clés : morphométrie, object_area, object_area_exc, object_feret, object_esd, object_major, object_minor, fre_area, fre_feret, acq_pixel

Les mesures morphométriques sont des mesures d'image. Elles sont généralement en pixels, sauf indication contraire. La conversion en unités physiques nécessite `acq_pixel` ou un équivalent de calibration.

| Concept | Colonnes possibles | Définition |
|---------|--------------------|------------|
| Surface | `object_area`, `fre_area` | Aire de l'objet |
| Surface sans trous | `object_area_exc` | Aire excluant les trous ; souvent préférable pour taille réelle |
| Longueur maximale | `object_feret`, `fre_feret` | Diamètre de Feret, proxy robuste de longueur |
| Grand axe | `object_major`, `fre_major` | Grand axe de l'ellipse ajustée |
| Petit axe | `object_minor`, `fre_minor` | Petit axe de l'ellipse ajustée |
| ESD | `object_esd`, `fre_esd` | Diamètre équivalent sphérique |
| ESD LOKI | `fre_equivalent_diameter_area` | Diamètre équivalent calculé depuis l'aire, souvent affiché comme `ESD` |
| Forme | `object_elongation`, `object_circ.`, `object_fractal` | Élongation, circularité, contour |
| Forme LOKI | `fre_eccentricity`, `fre_extent`, `fre_solidity`, `fre_perimeter`, `fre_orientation` | Forme, contour et orientation |
| Intensité | `object_mean`, `object_stddev`, `object_median`, `object_min`, `object_max` | Niveaux de gris |
| Intensité LOKI | `fre_intensity_mean`, `fre_intensity_min`, `fre_intensity_max`, `fre_image_pixel_int_mean` | Niveaux de gris et intensité image |
| Texture | `object_skew`, `object_kurt`, `object_histcum1`, `object_histcum2`, `object_histcum3` | Distribution des niveaux de gris |

**Conversion pixels → unités physiques :**
```python
longueur_mm = longueur_pixels * acq_pixel
surface_mm2 = surface_pixels * (acq_pixel ** 2)
```

Pour certains exports LOKI, la calibration est fournie en micromètres par pixel :
```python
longueur_mm = longueur_pixels * (acq_pixel_um_size / 1000)
surface_mm2 = surface_pixels * ((acq_pixel_um_size / 1000) ** 2)
```

⚠️ La morphométrie image n'est pas un poids, une biomasse ou une mesure lipidique directe.

---

# Quelles colonnes EcoTaxa sont prioritaires pour une table d'analyse ?

Mots-clés : table clean, colonnes prioritaires, spatio-temporel, profondeur, taxonomie, taille, forme, texture, sample, acquisition

| Famille | Colonnes candidates | Rôle |
|---------|---------------------|------|
| Identifiant | `object_id`, `obj_orig_id` | Identifie chaque objet/vignette |
| Spatio-temporel | `object_lat`, `object_lon`, `object_date`, `object_time`, ou alias `obj_*` | Position et moment de l'observation |
| Profondeur | `object_depth_min`, `object_depth_max`, ou alias `obj_depth_*` | Calcul du midpoint de profondeur |
| Taxonomie validée | `object_annotation_category`, `object_annotation_hierarchy`, `txo_display_name` | Taxon principal et lignée |
| Taille | `object_area`, `object_area_exc`, `object_esd`, `object_feret`, `object_major`, `object_minor`, ou alias `fre_*` | Taille en pixels, conversion avec calibration |
| Forme | `object_elongation`, `object_circ.`, `object_fractal`, `object_convarea`, `object_convperim` | Descripteurs morphologiques |
| Intensité/texture | `object_mean`, `object_stddev`, `object_median`, `object_min`, `object_max`, `object_skew`, `object_kurt` | Niveaux de gris et texture |
| Sample/profil | `sample_id`, `sample_profileid`, `sample_stationid`, `sample_station_name`, `sample_ctdrosettefilename` | Regroupement et liaison contexte |
| Acquisition | `acq_id`, `acq_instrument`, `acq_sn`, `acq_volimage`, `acq_pixel`, `acq_pixel_um_size` | Instrument, volume par image et calibration |
| CTD/capteurs embarqués | `acq_temperature_ctd`, `acq_salinity_ctd`, `acq_oxygen_concent`, `acq_fluo1`, `acq_raw_depth` | Contexte physico-chimique associé à l'acquisition |

Pour une question taxonomique, identifier d'abord la colonne de taxon validé présente dans le fichier.
Pour une question de profondeur, calculer un midpoint.
Pour une question de taille réelle, convertir avec `acq_pixel`.

---

# Comment décider quelles colonnes EcoTaxa supprimer dans une table clean ?

Mots-clés : nettoyage, colonnes nulles, colonnes constantes, sparse, valeurs manquantes, métadonnées, object_random_value, données personnelles

La suppression doit être pilotée par le contenu réel du TSV, pas seulement par le nom de colonne.

Règle recommandée :
1. supprimer les colonnes toujours nulles ;
2. supprimer les colonnes constantes si elles ne varient pas entre objets ;
3. supprimer ou déplacer en métadonnées les colonnes très sparse avec une seule valeur informative ;
4. conserver les colonnes variables utiles à l'analyse ;
5. documenter chaque suppression dans un fichier de traçabilité.

Exemples de colonnes souvent supprimables selon le profil du TSV :

| Type | Colonnes possibles | Raison |
|------|--------------------|--------|
| Liens ou compléments vides | `object_link`, `complement_info` | Souvent nulls |
| Identifiants internes | `objid`, `processid_internal`, `acq_id_internal`, `sample_id_internal` | Traçabilité interne, peu scientifique |
| Classification automatique vide | `classif_auto_id`, `classif_auto_score`, `classif_auto_when` | À retirer si null |
| Paramètres constants | `acq_instrument`, `sample_cruise`, `sample_ship`, `sample_stationid` | À déplacer en métadonnées si constants |
| Valeurs internes | `object_random_value` | Variable mais non scientifique |
| Données personnelles | `object_annotation_person_name`, `object_annotation_person_email` | À éviter dans exports publics |

Attention : une colonne constante dans un projet peut être variable dans un autre. Toujours recalculer le profil null/constance pour chaque export.

---

# Comment lire un export EcoTaxa LOKI avec préfixes obj_*, txo_*, fre_*, sample_* et acq_* ?

Mots-clés : LOKI, EcoTaxa, obj_orig_id, txo_display_name, fre_equivalent_diameter_area, pixel_um_size, CTD embarquée, filet, station

Certains projets LOKI exposent les colonnes EcoTaxa sous forme de familles `obj_*`, `txo_*`, `fre_*`, `sample_*`, `acq_*` plutôt que sous le schéma `object_*`.

Colonnes clés à chercher :

| Famille | Colonnes prioritaires | Rôle |
|---------|-----------------------|------|
| Objet | `obj_orig_id`, `obj_latitude`, `obj_longitude`, `obj_objdate`, `obj_objtime`, `obj_depth_min`, `obj_depth_max` | Identifiant, position, temps, profondeur |
| Taxonomie | `txo_display_name`, `txo_name`, `txo_id`, `obj_classif_qual` | Taxon affiché et statut de validation |
| Classification auto | `obj_classif_auto_id`, `obj_classif_auto_score`, `obj_classif_auto_when` | Audit/pré-tri, pas taxon final |
| Taille | `fre_equivalent_diameter_area`, `fre_axis_major_length`, `fre_axis_minor_length`, `fre_feret_diameter_max`, `fre_area` | Taille image |
| Forme | `fre_eccentricity`, `fre_extent`, `fre_solidity`, `fre_perimeter`, `fre_orientation` | Forme et contour |
| Intensité | `fre_intensity_mean`, `fre_intensity_min`, `fre_intensity_max`, `fre_image_pixel_int_mean`, `fre_image_pixel_int_stddev` | Niveaux de gris |
| Sample | `sample_station_name`, `sample_deployment_datetime_start`, `sample_gear`, `sample_tow_type`, `sample_cast_number` | Station, trait, cast |
| Filet | `sample_net_mesh_size`, `sample_net_mouth_aperture`, `sample_min_net_sampling_depth`, `sample_max_net_sampling_depth` | Propriétés du prélèvement |
| Acquisition | `acq_temperature_ctd`, `acq_salinity_ctd`, `acq_oxygen_concent`, `acq_fluo1`, `acq_raw_depth`, `acq_pixel_um_size` | CTD/capteurs et calibration |

En syntaxe API EcoTaxa, ces mêmes champs peuvent apparaître avec des points, par exemple `obj.orig_id`, `txo.display_name`, `fre.equivalent_diameter_area`, `acq.pixel_um_size`.

Règles RAG :
- Pour le taxon, privilégier `txo_display_name` ou `txo.name` selon la colonne disponible, puis vérifier `obj_classif_qual`.
- Pour la profondeur objet, utiliser `obj_depth_min` et `obj_depth_max` si présents ; sinon documenter explicitement la profondeur alternative (`fre_Depth min`, `acq_raw_depth`, ou profondeur de trait).
- Pour convertir la morphométrie LOKI, utiliser `acq_pixel_um_size` si les mesures sont en pixels.
- Pour l'environnement, les colonnes `acq_*_ctd`, `acq_oxygen_*`, `acq_fluo*` sont des capteurs/acquisitions associées ; ne pas les confondre avec une CTD externe indépendante.

---

# Quelles colonnes de profil et CTD contient EcoPart ?

Mots-clés : EcoPart, Profile, Rawfilename, Depth, Sampled volume, température, salinité, oxygène, fluorescence, nitrate, LPM, qc flag

EcoPart travaille au niveau **profil + bin de profondeur**. Il ne contient pas les objets individuels EcoTaxa.

| Colonne | Définition | Unité |
|---------|------------|-------|
| `Profile` | Identifiant du profil instrument — clé fréquente vers EcoTaxa | texte |
| `Rawfilename` | Nom du fichier source instrument | texte |
| `yyyy-mm-dd hh:mm` | Date/heure du profil | datetime |
| `Project` | Nom du projet EcoPart | texte |
| `Depth [m]` | Profondeur du bin | m |
| `Sampled volume [L]` | Volume d'eau échantillonné — obligatoire pour concentration | L |
| `temperature [degc]` | Température du bin | degC |
| `practical salinity [psu]` | Salinité pratique | psu |
| `oxygen [umol kg-1]` | Oxygène dissous massique | µmol kg⁻¹ |
| `oxygen [ml l-1]` | Oxygène dissous volumique | ml l⁻¹ |
| `chloro fluo [mg chl m-3]` | Fluorescence chlorophylle | mg chl m⁻³ |
| `nitrate [umol l-1]` | Nitrate | µmol l⁻¹ |
| `pressure [db]` | Pression | db |
| `LPM (...) [# l-1]` | Concentration particules par classe de taille | # l⁻¹ |
| `LPM biovolume (...) [mm3 l-1]` | Biovolume particules par classe de taille | mm³ l⁻¹ |
| `qc flag` | Indicateur qualité | code |

⚠️ Les variables environnementales EcoPart proviennent du système associé à l'instrument. Ne pas les confondre automatiquement avec une CTD externe.

---

# Comment joindre EcoTaxa avec EcoPart ?

Mots-clés : jointure EcoTaxa EcoPart, profile_id, Profile, object_depth, Depth, Sampled volume, depth_delta_m, concentration

Pour calculer une concentration de zooplancton ou rapprocher objets et volumes, il faut joindre EcoTaxa et EcoPart.

**Clés de jointure possibles :**
```text
EcoTaxa profile_id       → EcoPart Profile
EcoTaxa object_depth     → EcoPart Depth [m]
EcoTaxa date/time/latlon → EcoPart date/time/latlon si aucune clé directe
```

**Étapes concrètes :**
1. Détecter ou créer un `profile_id` côté EcoTaxa :
   - utiliser `sample_profileid` si présent ;
   - ou extraire le profil depuis `obj_orig_id` quand l'ID contient un suffixe objet.
2. Calculer `object_depth = (depth_min + depth_max) / 2`.
3. Joindre `profile_id` = `Profile` quand la clé existe.
4. Matcher au bin EcoPart le plus proche ; une tolérance de quelques mètres est souvent nécessaire.
5. Récupérer `Sampled volume [L]` pour calculer une concentration.

**Colonnes créées par une jointure :**

| Colonne créée | Définition |
|---------------|------------|
| `profile_id` | Profil harmonisé côté EcoTaxa |
| `object_depth` | Midpoint des profondeurs min/max |
| `ecopart_depth` | Profondeur du bin EcoPart matché |
| `depth_delta_m` | Différence absolue de profondeur |
| `depth_match_quality` | Qualité du match profondeur |

---

# Quelles colonnes physico-chimiques contient une CTD externe ?

Mots-clés : CTD, plateforme, campagne, station, cast, latitude, longitude, depth, PRES, TE90, PSAL, OXYM, FLOR, NTRA

Les noms exacts changent selon fournisseur et plateforme, mais les concepts sont stables.

| Concept | Colonnes possibles | Unité |
|---------|--------------------|-------|
| Plateforme | `platform_name`, `ship`, `vessel` | texte |
| Campagne | `cruise_name`, `cruise_number`, `campaign` | texte/int |
| Station/cast | `station`, `cast_number`, `event_id` | texte/int |
| Temps | `time`, `time (UTC)`, `datetime` | UTC |
| Latitude | `latitude`, `lat` | degrees_north |
| Longitude | `longitude`, `lon` | degrees_east |
| Profondeur | `depth`, `PRES` | m ou dbar |
| Température | `TE90`, `temperature`, `temperature [degc]` | degC |
| Salinité | `PSAL`, `salinity`, `practical salinity [psu]` | PSU |
| Oxygène | `OXYM`, `oxygen`, `oxygen [umol kg-1]` | µM ou µmol kg⁻¹ |
| Fluorescence | `FLOR`, `fluorescence`, `chloro fluo [mg chl m-3]` | variable |
| Nitrate | `NTRA`, `nitrate [umol l-1]` | µmol L⁻¹ ou mmol m⁻³ |

**Équivalences langage naturel → colonne :**
```text
"température"           → TE90 / temperature
"salinité"              → PSAL / salinity
"oxygène"               → OXYM / oxygen
"fluorescence" / "chla" → FLOR / fluorescence / chloro fluo
"nitrate"               → NTRA / nitrate
```

---

# Comment joindre EcoPart ou EcoTaxa avec une CTD externe ?

Mots-clés : jointure CTD, proximité temporelle, proximité spatiale, profondeur, time_delta, distance_km, depth_delta_m, match quality

La liaison se fait généralement par proximité **date/heure + latitude/longitude + profondeur**. Il ne faut pas supposer une clé directe.

Approche recommandée :
1. Harmoniser les dates/heures en UTC.
2. Harmoniser les coordonnées en degrés décimaux.
3. Calculer une profondeur objet ou bin comparable.
4. Chercher le cast/profil CTD le plus proche temporellement et spatialement.
5. Interpoler ou matcher la profondeur CTD la plus proche.
6. Conserver les deltas de match (`time_delta`, `distance_km`, `depth_delta_m`) pour contrôler la qualité.

Colonnes de sortie utiles :
| Colonne créée | Définition |
|---------------|------------|
| `ctd_match_id` | Identifiant du cast/profil CTD matché |
| `ctd_depth` | Profondeur CTD retenue |
| `ctd_time_delta_min` | Écart temporel |
| `ctd_distance_km` | Distance horizontale |
| `ctd_depth_delta_m` | Écart vertical |
| `ctd_match_quality` | Classe de qualité du match |

---

# Quels sont les pièges courants avec EcoTaxa, EcoPart et CTD ?

Mots-clés : pièges, concentration, volume échantillonné, midpoint profondeur, taxon validé, classification automatique, acq_pixel, CTD externe, anonymisation

| Piège | Source | Règle |
|-------|--------|-------|
| Calculer une concentration depuis EcoTaxa seul | EcoTaxa | Chercher un volume échantillonné dans EcoPart ou métadonnées instrument |
| Utiliser uniquement la profondeur minimum | EcoTaxa | Toujours calculer le midpoint si min et max existent |
| Supposer un nom unique pour le taxon | EcoTaxa | Détecter `object_annotation_category`, `txo_display_name` ou équivalent |
| Faire confiance à la classification automatique sans validation | EcoTaxa | Utiliser les colonnes automatiques seulement pour audit/pré-tri |
| Répéter des colonnes constantes dans une table d'analyse | EcoTaxa | Les déplacer en métadonnées dataset |
| Convertir des pixels sans calibration | EcoTaxa | Utiliser `acq_pixel` ou une calibration équivalente |
| Confondre EcoPart et CTD externe | EcoPart/CTD | Ce sont des sources distinctes ; documenter la provenance |
| Joindre CTD par clé directe inexistante | EcoPart/CTD | Utiliser proximité temps + position + profondeur |
| Publier des emails d'annotateurs | EcoTaxa | Retirer ou anonymiser les colonnes personnelles |

*Référence générique basée sur exports EcoTaxa/EcoPart/CTD réels ; recalculer le profil des colonnes pour chaque nouveau projet.*
*Dernière mise à jour : mai 2026*
