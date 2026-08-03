# sources_en_ligne.md
# Sources en ligne autorisées pour l'assistant copépodes
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Quelle source utiliser pour quelle question ?

Mots-clés : sources en ligne, EcoTaxa, EcoPart, Amundsen CTD, OGSL, Bio-ORACLE, données labo, Mode En Ligne

| Question du chercheur | Source à utiliser |
|---|---|
| "Je veux les annotations taxonomiques de ma campagne" | EcoTaxa |
| "Je veux les objets individuels et la morphométrie image" | EcoTaxa |
| "Je veux les profils UVP avec CTD et volume échantillonné" | EcoPart |
| "Je veux calculer une concentration à partir d'objets EcoTaxa" | EcoTaxa + EcoPart |
| "Je veux une CTD officielle de campagne" | CTD externe, priorité Amundsen ERDDAP si disponible |
| "Je veux mes données de comptage filet, lipides ou biomasse" | Données labo, fichier local |
| "Je veux contextualiser avec des données régionales du golfe du Saint-Laurent" | OGSL |
| "Je veux extraire des conditions environnementales actuelles ou futures à des coordonnées" | Bio-ORACLE |

**Règle générale :**
- Les sources en ligne ne sont jamais appelées silencieusement.
- Le Mode En Ligne doit être activé pour la session dans l'UI, puis la source doit être explicitement demandée par l'utilisateur.
- Quand l'extraction réussit, l'agent écrit un CSV dérivé dans le dossier `static/<user>/<session>/uploads/` afin que le fichier puisse être relu comme un upload normal.
- Si une source n'est pas activée, l'agent travaille avec les fichiers chargés et le RAG local.
- Les IDs de projets ou datasets sont découverts dynamiquement ou fournis par l'utilisateur ; ils ne sont pas des constantes système.

---

# EcoTaxa : cache partagé puis export ciblé

Mots-clés : EcoTaxa, cache partagé EcoTaxa, métadonnées échantillon, profils, casts, annotations taxonomiques, objets individuels, morphométrie, export ciblé

**Ce que contient le cache partagé :** métadonnées de projet, sample, profil/cast,
station, position, date, profondeur enveloppe, instrument, volume et champs libres
utiles à la sélection. Il est commun à tous les utilisateurs du dépôt : aucun
mot de passe EcoTaxa n'est requis pour l'explorer.

**Ce qui exige un export EcoTaxa :** objets individuels, taxons/annotations,
morphométrie image, valeurs par profondeur ou toute analyse à grain objet. Le
cache prépare alors la sélection exacte ; l'export est confirmé séparément et
son résultat doit être audité.

**Niveau :** cache = sample/profil ; export = objet individuel.

**Workflow recommandé :**
1. explorer ou filtrer le cache partagé ;
2. vérifier les champs directs de sample/profil disponibles ;
3. si la demande exige le grain objet, proposer l'export de cette sélection ;
4. après confirmation, inspecter colonnes, validation, profondeur, taxon et
   morphométrie dans l'export ;
5. travailler sur une copie ou table dérivée.

**Limites :**
- EcoTaxa ne fournit pas nécessairement le volume échantillonné ;
- poids, lipides et biomasse ne sont pas garantis dans les exports ;
- les annotations automatiques ne remplacent pas une validation humaine.

---

# Comment accéder à EcoPart ?

Mots-clés : EcoPart, profils UVP, bins de profondeur, volume échantillonné, particules, CTD, concentration, jointure

**Ce que ça contient :** profils UVP agrégés par bin de profondeur, variables environnementales associées, volume échantillonné, particules et biovolume par classes de taille.

**Niveau :** profil + profondeur, pas objet individuel.

**Accès :** compte requis selon les datasets ; souvent mêmes identifiants que les services EcoTaxa/EcoPart.

**Usage principal :**
- récupérer `Sampled volume [L]` ;
- rapprocher objets EcoTaxa et volume par `profile_id` + profondeur ;
- calculer des concentrations quand la jointure est valide.

**Limite :** EcoPart ne décrit pas les taxons individuels. Il doit être joint avec EcoTaxa pour les analyses taxonomiques objet-level.

---

# Comment accéder à une CTD externe ?

Mots-clés : CTD, CTD externe, Amundsen, Amudnsen, données environnementales, variables environnementales, donne env, enrichis CTD, Amundsen ERDDAP, température, salinité, oxygène, fluorescence, nitrate, cast, station, profondeur

**Routage sur une table chargée :** les formulations `CTD`, `Amundsen`,
`donne les données CTD`, `donne les données environnementales`, `ajoute les
variables environnementales` et `enrichis avec Amundsen` déclenchent directement
l'enrichissement canonique Amundsen. Si aucune variable n'est précisée, utiliser
les huit variables prises en charge : `PRES`, `TE90`, `PSAL`, `SIGT`, `OXYM`,
`pH`, `NTRA` et `FLOR`. Ne jamais simuler cette opération avec des colonnes vides.

**Ce que ça contient :** température, salinité, oxygène, fluorescence, nitrate et autres variables physico-chimiques mesurées indépendamment.

**Accès :** dépend du fournisseur. Certains datasets sont publics via ERDDAP ; d'autres nécessitent formulaire ou compte.

**Paramètres typiques :**
- fenêtre temporelle ;
- latitude/longitude ;
- profondeur ou pression ;
- variables (`temperature`, `salinity`, `oxygen`, `fluorescence`, `nitrate` ou alias).

**Règle de jointure :** sauf clé explicite, joindre par proximité date/heure + latitude/longitude + profondeur.

**Limite :** une CTD externe est une source distincte des capteurs associés à l'UVP. Ne pas mélanger les provenances sans métadonnées.

---

# Comment utiliser les données internes du labo ?

Mots-clés : données labo, fichier local, CSV, TSV, Excel, lipides, biomasse, comptage filet, structure inconnue

**Ce que ça contient :** comptages filet, mesures lipidiques, biomasse carbone, stades manuels ou autres mesures produites par le labo.

**Accès :** fichier local chargé par l'utilisateur.

**Règle :** ne jamais supposer les colonnes avant inspection.

Workflow :
1. inspecter le fichier ;
2. détecter séparateur, encodage, feuilles Excel si besoin ;
3. inférer les rôles sémantiques des colonnes ;
4. demander clarification si un rôle critique est ambigu ;
5. créer une table de travail dérivée pour nettoyage ou jointure.

---

# Comment utiliser OGSL ?

Mots-clés : OGSL, golfe du Saint-Laurent, source régionale, profils environnementaux, données complémentaires, CTD, ismerSgdeCtd

**Ce que ça contient :** profils CTD océanographiques du golfe du Saint-Laurent et de l'estuaire, multi-missions, accès via ERDDAP tabledap OGSL.

**Dataset principal :** `ismerSgdeCtd` — ERDDAP tabledap ISMER, couvre plusieurs missions et années.

**Endpoint ERDDAP :** `https://erddap.ogsl.ca/erddap/tabledap/ismerSgdeCtd`

**Accès :** public, sans credentials. Tool `fetch_remote_source_dataset(session_key, source_id="ogsl", parameters={...})`.

**Quand l'utiliser :**
- profils CTD régionaux du golfe du Saint-Laurent quand le CTD Amundsen ne couvre pas la zone ou la période ;
- contextualiser des observations avec température, salinité, oxygène, fluorescence régionaux ;
- comparaison inter-missions ou inter-années pour le golfe.

**Paramètres de fetch :**
```python
parameters={
    "period": {"start": "2013-06-01", "end": "2013-07-15"},  # ISO dates
    "station": "IML4",      # optionnel — filtre sur stationID
    "mission": "Mingan2013", # optionnel — filtre sur cruiseID
    "variables": ["TE90", "PSAL", "OXYM"],  # colonnes ERDDAP — voir liste ci-dessous
}
```

**Limites :**
- couverture temporelle et spatiale variable selon les missions disponibles ;
- résolution verticale dépend du dataset et de l'instrument ;
- priorité au CTD Amundsen officiel si la campagne est couverte.

**Métadonnées obligatoires si utilisé :**
- source OGSL, dataset `ismerSgdeCtd` ;
- cruiseID ou stationID ;
- période ;
- variables extraites ;
- chemin du CSV dérivé.

---

# Colonnes OGSL ismerSgdeCtd — noms ERDDAP et unités

Mots-clés : OGSL colonnes, ERDDAP variable names, TE90, PSAL, ASAL, OXYM, FLOR, NTRA, PRES, SIGT, TRB, TRAN, PHPH, PSAR, cruiseID, stationID, température salinité oxygène fluorescence nitrate turbidité pression densité pH PAR, ismerSgdeCtd colonnes unités, temperature salinity oxygen

**Variables océanographiques mesurées — noms ERDDAP exacts :**

| Colonne ERDDAP | Nom complet | Unité | CF standard_name |
|---|---|---|---|
| `TE90` | Temperature (ITS-90) | °C | `sea_water_temperature` |
| `PSAL` | Practical Salinity | PSU | `sea_water_practical_salinity` |
| `ASAL` | Absolute Salinity (TEOS-10) | g/kg | `sea_water_absolute_salinity` |
| `PRES` | Sea Pressure | dbar | `sea_water_pressure_due_to_sea_water` |
| `OXYM` | Dissolved Oxygen | µM | `mole_concentration_of_dissolved_molecular_oxygen_in_sea_water` |
| `FLOR` | Chl-a fluorescence | mg m⁻³ | `mass_concentration_of_chlorophyll_a_in_sea_water` |
| `NTRA` | Nitrate (NO₃-N) | mmol m⁻³ | `mole_concentration_of_nitrate_in_sea_water` |
| `SIGT` | Sigma-T (densité) | kg m⁻³ | `sea_water_sigma_t` |
| `PHPH` | pH | unités pH | — |
| `PSAR` | PAR sous-marin | µeinsteins s⁻¹ m⁻² | `downwelling_photosynthetic_photon_flux_in_sea_water` |
| `TRAN` | Transmission lumineuse | % | — |
| `TRB` | Turbidité | NTU | `sea_water_turbidity` |

**Colonnes de métadonnées :**

| Colonne | Description |
|---|---|
| `cruiseID` | Identifiant de la mission (ex. `2013_06 Mingan`) |
| `cruise_start_date` | Date de début de mission |
| `cruise_end_date` | Date de fin de mission |
| `cruise_chief_scientist` | Chef de mission |
| `platform_name` | Nom du navire ou plateforme |
| `instrument` | Modèle de l'instrument CTD |
| `stationID` | Identifiant de la station |
| `cast_number` | Identifiant du cast (descente) |
| `time` | Horodatage ISO (UTC) |
| `latitude` | Latitude (degrés N) |
| `longitude` | Longitude (degrés E) |

**Point critique :** les noms de variables OGSL/ERDDAP (`TE90`, `PSAL`, `OXYM`) sont différents des noms courants (`temperature`, `salinity`, `oxygen`). Toujours utiliser les noms ERDDAP exacts dans les requêtes et les graphiques.

---

# Comment utiliser Bio-ORACLE ?

Mots-clés : Bio-ORACLE, environnement, conditions futures, scénario, SSP, thetao, so, no3, o2, chl, ERDDAP griddap, coordonnées, raster, extraction

**Ce que ça contient :** variables environnementales marines à l'échelle globale — température, salinité, oxygène, nitrate, chlorophylle — pour des périodes historiques (2000–2019) et des projections futures (2020–2100) sous plusieurs scénarios SSP.

**Endpoint ERDDAP :** `https://erddap.bio-oracle.org/erddap/griddap/`

**Accès :** public, sans credentials. Tool `fetch_remote_source_dataset(session_key, source_id="bio_oracle", parameters={...})`.

**Usage :**
- extraire des conditions environnementales à des coordonnées précises ou dans une zone ;
- coupler des données de copépodes avec des variables environnementales actuelles ou futures ;
- préparer des graphiques couplés zooplancton/environnement ou des cartes de conditions SSP.

**Bio-ORACLE ne sert pas à :**
- valider un taxon ou confirmer une observation de copépode ;
- interpréter biologiquement un résultat ;
- remplacer un profil CTD de campagne (résolution spatiale ~5 arcmin ≈ 9 km).

**Paramètres de fetch :**
```python
parameters={
    "variable": "thetao",           # nom ERDDAP exact (voir liste ci-dessous)
    "variables": ["thetao"],        # même variable en liste
    "scenario": "SSP245",           # SSP119, SSP126, SSP245, SSP370, SSP460, SSP585
    "period": {"start": 2041, "end": 2060},  # années ou dates ISO
    "latitude": 50.0,               # point unique — résolution ~5 arcmin
    "longitude": -66.0,
}
```

**Limites :**
- résolution spatiale ~5 arcmin (~9 km) — insuffisante pour l'échelle d'une station unique ;
- scénarios futurs couvrent 2020–2100 ; données historiques couvrent 2000–2019 ;
- extraction sur un seul point (lat/lon), pas de moyenne zonale native dans le tool.

**Métadonnées obligatoires si utilisé :**
- variable, scénario, période, coordonnées ;
- dataset ID Bio-ORACLE (`thetao_ssp245_2020_2100_depthmax`) ;
- résolution spatiale et temporelle ;
- chemin du CSV dérivé.

---

# Variables Bio-ORACLE — noms ERDDAP, scénarios disponibles, profondeurs

Mots-clés : Bio-ORACLE variables, thetao, so, no3, o2, chl, phyc, sws, SSP126, SSP245, SSP370, SSP585, depthmax, depthmean, depthsurf, baseline, scénario futur, température salinité nitrate oxygène chlorophylle, ERDDAP griddap variable name, ocean temperature salinity chlorophyll future scenario

**Variables principales disponibles (noms ERDDAP exacts) :**

| Variable ERDDAP | Description | Unité | Scénarios disponibles |
|---|---|---|---|
| `thetao` | Température potentielle de l'eau de mer | °C | baseline, SSP119, SSP126, SSP245, SSP370, SSP460, SSP585 |
| `so` | Salinité pratique | PSU | baseline, SSP119, SSP126, SSP245, SSP370, SSP585 |
| `no3` | Concentration en nitrate (NO₃) | mmol m⁻³ | baseline, SSP126, SSP245, SSP370 |
| `o2` | Oxygène dissous | mmol m⁻³ | baseline, SSP126, SSP245 |
| `chl` | Concentration en chlorophylle-a | mg m⁻³ | baseline (pas de scénario futur direct) |
| `phyc` | Carbone phytoplanctonique | mmol m⁻³ | SSP126 |
| `sws` | Vitesse de l'onde de surface | m s⁻¹ | SSP126, SSP245 |

**Variantes de profondeur (suffixe dans le nom du dataset) :**

| Suffixe | Description |
|---|---|
| `depthmax` | Variable à la profondeur maximale de la colonne |
| `depthmean` | Moyenne sur la colonne d'eau |
| `depthsurf` | Surface (0–10 m) |
| `depthmin` | Valeur minimale dans la colonne |

**Convention de nommage des datasets Bio-ORACLE :**
```
{variable}_{scenario}_{start_year}_{end_year}_{depth_layer}
```
Exemples :
- `thetao_baseline_2000_2019_depthmax` — température historique, profondeur max
- `thetao_ssp245_2020_2100_depthmax` — température SSP2-4.5, projections 2020–2100
- `so_ssp126_2020_2100_depthmean` — salinité SSP1-2.6, moyenne colonne

**Scénarios SSP — description courte :**

| Scénario | Description |
|---|---|
| `SSP119` | Très bas — émissions quasi nulles après 2020 |
| `SSP126` | Bas — neutralité carbone vers 2050 |
| `SSP245` | Intermédiaire — politiques actuelles maintenues |
| `SSP370` | Élevé — pas de nouvelles politiques climatiques |
| `SSP460` | Intermédiaire-haut |
| `SSP585` | Très élevé — dépendance maximale aux combustibles fossiles |

**Colonnes du CSV extrait :**

| Colonne | Description |
|---|---|
| `time` | Date/heure (UTC) |
| `latitude` | Latitude du point (degrés N) |
| `longitude` | Longitude du point (degrés E) |
| `{variable}_{depth_suffix}` | Valeur de la variable (ex. `thetao_max`) |

**Point critique :** la colonne de valeur dans le CSV a un suffixe ajouté par Bio-ORACLE (`_max`, `_mean`, `_surf`). Toujours inspecter le CSV extrait avant de nommer les axes.

---

# Quelles sources sont exclues du prompt cible ?

Mots-clés : sources exclues, OBIS, CMEMS, dette documentaire, prompt cible, source non autorisée

Le prompt cible autorise EcoTaxa, EcoPart, CTD externe, OGSL, Bio-ORACLE et fichiers labo.

OBIS et CMEMS peuvent apparaître dans d'anciennes specs, notes ou scénarios historiques, mais ne sont pas des sources autorisées dans le prompt cible actuel.

Règle :
- ne pas implémenter de requête OBIS/CMEMS sans décision explicite de réintégration ;
- si un ancien scénario mentionne OBIS/CMEMS, le traiter comme dette documentaire à réviser ;
- proposer OGSL, Bio-ORACLE, CTD externe ou RAG local selon la question.

---

# Quels sont les pièges courants avec les sources en ligne ?

Mots-clés : pièges sources, credentials, Mode En Ligne, hardcode, source activée, données brutes, métadonnées

| Piège | Règle |
|---|---|
| Appeler une source sans consentement | Exiger Mode En Ligne activé pour cette source |
| Hardcoder un project_id | Découvrir dynamiquement ou utiliser l'ID fourni par l'utilisateur |
| Exposer un credential | Ne jamais afficher token, mot de passe, cookie ou `.env` |
| Écraser les données brutes | Toujours créer une table dérivée |
| Mélanger sources sans méthode | Documenter jointure, filtres, unités et limites |
| Confondre absence de donnée et absence biologique | Présenter comme limite technique, pas conclusion scientifique |
| Répondre avec une source non autorisée | Bloquer ou proposer une source autorisée |

_Dernière mise à jour : mai 2026_
