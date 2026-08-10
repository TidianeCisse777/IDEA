# jointures_environnementales.md
# Méthodes de jointure entre zooplancton et sources environnementales
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Principe général

Mots-clés : jointure, merge, merge_asof, station, cast, profile_id, depth, time, latitude, longitude, Bio-ORACLE, OGSL, CTD, EcoTaxa, EcoPart

Une bonne jointure environnementale doit rester traçable. Il faut préserver les colonnes brutes, choisir une clé explicite, et documenter la qualité du match.

Règles de base :
- garder les colonnes sources intactes ;
- ajouter des alias seulement en plus des colonnes d'origine ;
- choisir la clé la plus stable disponible ;
- enregistrer les deltas de match ;
- demander une clarification si une clé critique manque.

Colonnes de qualité recommandées :
- `match_status`
- `time_delta_min`
- `depth_delta_m`
- `distance_km`
- `source_dataset_id`

---

# Quel type de jointure utiliser ?

Mots-clés : exact match, nearest, asof, profondeur, intervalle, station, cast

| Situation | Pattern pandas recommandé | Clé principale |
|---|---|---|
| Même station/cast/profil | `merge(..., on=[...], how="left")` | identifiant exact |
| Temps proche mais non identique | `merge_asof(..., direction="nearest")` | temps |
| Profondeur voisine | calcul de distance absolue + minimum | profondeur / pression |
| Point géographique | filtrage par lat/lon puis sélection | coordonnées |
| Profil vertical complet | jointure sur station/cast puis profondeur | cast + profondeur |

Exemple minimal :
```python
joined = samples.merge(ctd, on=["station_id", "cast_number"], how="left")
```

Exemple temps proche :
```python
samples = samples.sort_values("time")
ctd = ctd.sort_values("time")
joined = pd.merge_asof(samples, ctd, on="time", direction="nearest")
```

---

# CTD verticale

Mots-clés : CTD, Amundsen, profil, pression, température, salinité, oxygène, profondeur

Une CTD verticale fournit un profil par profondeur. La jointure doit se faire en deux étapes :
1. identifier le cast ou le profil ;
2. rattacher la mesure du zooplancton à la profondeur la plus pertinente.

Colonnes utiles :
- `station_id`
- `cast_number`
- `profile_id`
- `time`
- `latitude`
- `longitude`
- `Pres` ou `depth`

Règle pratique :
- si le fichier zooplancton contient un intervalle de profondeur, utiliser l'intersection ou la profondeur moyenne ;
- si le fichier zooplancton contient une profondeur ponctuelle, choisir la ligne CTD la plus proche ;
- garder `depth_delta_m` ou `pres_delta_db` dans la sortie.

Ne pas faire :
- ne pas supprimer les lignes CTD redondantes avant d'avoir défini la règle de profondeur ;
- ne pas confondre pression et profondeur sans conversion explicite ;
- ne pas inventer une station si elle n'existe pas dans la source.

---

# Comment présélectionner les profils UVP correspondant aux samples filet ?

Mots-clés : NeoLabs, fichier sample, fichier abundance, SAMPLE_ID, filet, UVP,
EcoTaxa, profil UVP, station, position, datetime, fenêtre temporelle, seuil_h,
time_delta_h, delta 10 h, delta 12 h, correspondance, appariement

La fenêtre temporelle est un paramètre de la demande, jamais une constante du
RAG. Pour rechercher les profils UVP proches de samples filet :

- utiliser la table locale au grain **sample/déploiement** comme source des
  métadonnées de prélèvement (`SAMPLE_ID`, station, date/heure, position,
  cast/profil et profondeur selon le schéma réel inspecté) ;
- ne pas utiliser une table d'abondance au grain taxon/analyse comme table de
  déploiements : elle répète les métadonnées de sample. Ne jamais la réduire
  avec `drop_duplicates(station, cast)`, car un numéro de cast peut être
  réutilisé entre plusieurs dates ou campagnes ;
- construire un horodatage exact avec les colonnes de date et d'heure
  effectivement observées dans la table sample, puis conserver une ligne par
  `SAMPLE_ID` ou identifiant de déploiement vérifié ;
- côté EcoTaxa, limiter les candidats aux instruments UVP et conserver au
  minimum `sample_id`, `profile_id`, `station_id` et date/heure. Latitude et
  longitude sont des informations facultatives de contexte ;
- comparer uniquement les candidats de même station normalisée, puis calculer
  `time_delta_h = abs(datetime_uvp - datetime_filet)` ;
- filtrer avec `time_delta_h <= seuil_h`, où `seuil_h` vient de la demande de
  l'utilisateur. Le seuil peut donc valoir 10 h, 12 h ou toute autre valeur
  explicitement demandée ;
- ne pas appliquer de seuil de distance lorsque la station correspond. Une
  distance calculable peut être conservée comme diagnostic, mais elle ne doit
  ni filtrer ni invalider la correspondance ;
- conserver `time_delta_h`, les candidats multiples et les samples sans
  correspondance afin que la couverture et les ambiguïtés restent visibles.

Cette présélection produit des candidats traçables. Elle ne suffit pas, à elle
seule, à certifier une correspondance filet–UVP pour une comparaison scientifique.

---

# Correspondance filet ↔ UVP/EcoTaxa certifiée par CTD Amundsen

Mots-clés : filet, UVP, EcoTaxa, Amundsen, ctdrosettefilename, fichier CTD,
station, date, position, join_eligible, correspondance certifiée

Cette procédure est plus stricte qu'un enrichissement CTD ordinaire. Elle sert
uniquement à établir qu'un fichier filet chargé correspond réellement à des
samples UVP/EcoTaxa, avant toute comparaison ou calcul d'abondance croisé.

Validation obligatoire, dans cet ordre :
1. même station normalisée et compatibilité temporelle entre le déploiement
   filet et le sample UVP/EcoTaxa ; les coordonnées ne constituent pas un filtre
   supplémentaire lorsque la station correspond ;
2. présence d'un même fichier CTD Amundsen (`ctdrosettefilename` ou son alias)
   côté UVP/EcoTaxa et côté Amundsen ;
3. confirmation par Amundsen des métadonnées du fichier : station, heure et
   coordonnées cohérentes.

Seules les lignes marquées `join_eligible=true` constituent une correspondance
validée. Une proximité spatiale, une même journée, un nom de station ressemblant
ou un identifiant d'analyse ne suffisent jamais. Les candidats non validés sont
conservés dans l'audit avec leur raison ; ils ne doivent ni être joints pour une
analyse ni alimenter un graphique comparatif.

---

# Bio-ORACLE

Mots-clés : Bio-ORACLE, scenario, SSP, variable, griddap, couche, surface, depth_layer

Bio-ORACLE fournit des variables environnementales globales à des coordonnées. La jointure se fait par point géographique puis par scénario et couche.

Colonnes utiles :
- `latitude`
- `longitude`
- `variable`
- `scenario`
- `depth_layer`
- `dataset_id`

Règle pratique :
- utiliser `latitude` / `longitude` comme base ;
- choisir explicitement le scénario et la couche de profondeur ;
- conserver une colonne de comparaison présent vs futur si plusieurs scénarios sont extraits ;
- documenter la résolution spatiale si l'analyse repose sur un point unique.

Ne pas faire :
- ne pas traiter Bio-ORACLE comme une CTD de station ;
- ne pas remplacer une profondeur spécifique par une couche de surface sans le dire ;
- ne pas comparer deux scénarios sans conserver l'identifiant du dataset.

---

# OGSL

Mots-clés : OGSL, stationID, cruiseID, CTD régionale, profondeur, température, salinité, oxygène

OGSL sert à contextualiser avec des profils régionaux du golfe du Saint-Laurent.

Colonnes utiles :
- `stationID`
- `cruiseID`
- `cast_number`
- `time`
- `latitude`
- `longitude`
- `PRES`
- `TE90`
- `PSAL`
- `OXYM`

Règle pratique :
- joindre par station ou mission si la clé existe ;
- sinon, utiliser temps + coordonnées + profondeur ;
- conserver les noms ERDDAP exacts dans la table source ;
- ajouter des alias seulement si cela aide une jointure en aval.

---

# Comment joindre EcoTaxa et EcoPart, puis vérifier la qualité ?

Mots-clés : EcoTaxa, EcoPart, profile_id, volume échantillonné, bins de profondeur, concentration

EcoTaxa décrit les objets individuels. EcoPart décrit les profils agrégés et le volume échantillonné. La jointure habituelle passe par `profile_id` puis par profondeur.

Colonnes utiles :
- EcoTaxa : `object_id`, `profile_id`, `obj_depth_min`, `obj_depth_max`, `object_depth_min`, `object_depth_max`
- EcoPart : `Profile`, `Depth [m]`, `Sampled volume [L]`

Règle pratique :
- utiliser `profile_id` comme première clé ;
- rapprocher les profondeurs ensuite ;
- conserver le delta de profondeur dans la sortie ;
- si `Sampled volume [L]` manque, la concentration n'est pas calculable.

---

# Colonnes de qualité à exposer

Mots-clés : match_status, delta, provenance, traçabilité

Colonnes recommandées pour toute jointure :
- `match_status`
- `source_dataset_id`
- `time_delta_min`
- `depth_delta_m`
- `distance_km`
- `join_rule`

Ces colonnes permettent de filtrer rapidement les lignes fiables et de rejeter les matches ambiguës.

---

# Règle de sortie

Mots-clés : sortie, table, dérivée, jointe, traçable

La sortie doit être une table dérivée lisible par pandas, avec :
- les colonnes brutes ;
- les alias de jointure ;
- les indicateurs de qualité ;
- aucune interprétation biologique.

Si le match est incertain, il faut le signaler explicitement plutôt que le masquer.
