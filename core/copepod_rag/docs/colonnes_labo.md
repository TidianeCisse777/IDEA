# colonnes_labo.md
# Colonnes des fichiers de données labo — lipides, biomasse, variables dérivées
# Sources : analyses biochimiques labo Maps + features image LOKI + variables calculées
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Quelles colonnes retrouve-t-on typiquement dans un fichier de lipides labo ?

⚠️ **Règle fondamentale : les noms de colonnes dans ce document sont des noms TYPIQUES, pas des noms garantis.**
Les fichiers labo ont une structure inconnue jusqu'à l'inspection. Toujours appeler `inspect_file(path)` en premier pour découvrir les vrais noms de colonnes. Utiliser ce document pour comprendre la signification des colonnes trouvées — pas pour les nommer à l'avance.

**Workflow obligatoire :**
```
1. inspect_file(path)                → vrais noms de colonnes du fichier
2. query_copepod_knowledge_base(...) → comprendre ce que ces colonnes signifient
3. Travailler avec les vrais noms    → jamais avec les noms documentés ici
```

Les fichiers labo (CSV ou Excel uploadés par l'utilisateur) contiennent des mesures biochimiques produites sur des individus ou des fractions d'échantillons. Leur structure est découverte à la volée via `data.inspect`.

**Colonnes d'identifiant fréquentes :**

| Colonne typique | Définition | Notes |
|-----------------|------------|-------|
| `sample_id` | Identifiant de l'échantillon | Peut se lier à EcoTaxa ou EcoPart |
| `station` | Station d'échantillonnage | Correspondance possible avec Amundsen |
| `depth_m` / `depth` | Profondeur de collecte | m |
| `date` / `collection_date` | Date de collecte | Format variable |
| `species` / `taxon` | Espèce ou groupe analysé | Nom labo, pas forcément WoRMS |
| `stage` | Stade de développement (CV, AF, CIV…) | Code labo |
| `sex` | Sexe si discriminé | F / M / — |
| `n_individuals` | Nombre d'individus dans l'échantillon | Fréquent pour pooled samples |
| `replicate` | Numéro de réplica | pour analyses en triplicata |

---

# Quelles colonnes de lipides totaux et biochimie retrouve-t-on dans les fichiers labo ?

**Lipides totaux :**

| Colonne typique | Unité | Définition |
|-----------------|-------|------------|
| `total_lipids_mg_ind` | mg ind⁻¹ | Lipides totaux par individu |
| `total_lipids_ug_ind` | µg ind⁻¹ | Lipides totaux (petites espèces) |
| `lipid_content_pct_dw` | % poids sec | Lipides / poids sec |
| `dry_weight_mg` | mg | Poids sec individuel |
| `wet_weight_mg` | mg | Poids humide individuel |
| `ash_free_dry_weight_mg` | mg | AFDW — poids sec sans cendres |

**Classes de lipides :**

| Colonne typique | Unité | Définition |
|-----------------|-------|------------|
| `wax_esters_pct` | % lipides totaux | Wax esters (WE) — stockage long terme chez *Calanus* en diapause |
| `triacylglycerols_pct` | % lipides totaux | TAG — stockage court terme, énergie mobilisable rapidement |
| `phospholipids_pct` | % lipides totaux | Phospholipides — membranes cellulaires |
| `sterols_pct` | % lipides totaux | Stérols structuraux |
| `free_fatty_acids_pct` | % lipides totaux | AGL — lipides dégradés ou en transit |

---

# Quelles colonnes d'acides gras retrouve-t-on dans les fichiers labo ?

Les acides gras (fatty acids, FA) sont exprimés en pourcentage des acides gras totaux ou en µg par individu. Ce sont des marqueurs trophiques clés.

| Colonne typique | Notation | Signification trophique |
|-----------------|----------|------------------------|
| `dha_pct` / `22_6n3_pct` | 22:6(n-3) | DHA — acide gras essentiel, qualité nutritive, marqueur diatomées/dinoflagellés |
| `epa_pct` / `20_5n3_pct` | 20:5(n-3) | EPA — acide gras essentiel, marqueur diatomées |
| `fa_16_1n7_pct` | 16:1(n-7) | Marqueur diatomes — régime herbivore printanier |
| `fa_18_1n9_pct` | 18:1(n-9) | Marqueur omnivorie / carnivorie / bactéries |
| `fa_18_1n7_pct` | 18:1(n-7) | Marqueur bactéries |
| `fa_20_1n9_pct` | 20:1(n-9) | Composant des wax esters chez *Calanus* |
| `fa_22_1n11_pct` | 22:1(n-11) | Composant des wax esters chez *Calanus* |
| `dha_epa_ratio` | — | Ratio DHA/EPA — indicateur qualité nourriture |

**Règle de lecture trophique :**
- 16:1(n-7) élevé → régime herbivore (diatomes dominantes)
- 18:1(n-9) élevé → régime omnivore ou carnivore
- 20:1(n-9) + 22:1(n-11) élevés → copépode en diapause active (accumulation wax esters)

---

# Quelles colonnes de biomasse carbone retrouve-t-on dans les fichiers labo ?

La biomasse carbone est la variable centrale pour quantifier la contribution des copépodes au cycle du carbone.

| Colonne typique | Unité | Définition |
|-----------------|-------|------------|
| `carbon_biomass_ugC_ind` | µgC ind⁻¹ | Carbone par individu |
| `carbon_biomass_mgC_m3` | mgC m⁻³ | Carbone par volume d'eau — nécessite concentration |
| `carbon_biomass_gCO2_m3` | g CO2 m⁻³ | Biomasse exprimée en équivalent CO2 volumique |
| `carbon_content_pct_dw` | % poids sec | Carbone / poids sec |
| `nitrogen_content_pct_dw` | % poids sec | Azote — pour ratio C:N |
| `cn_ratio` | — | Ratio carbone:azote — indicateur condition nutritionnelle |

**Conversion µgC → g CO2 :**
```python
# 1 mol C = 12 g C → 1 mol CO2 = 44 g CO2
# facteur de conversion : 44/12 ≈ 3.667
gCO2_m3 = ugC_per_ind * concentration_ind_m3 * 1e-6 * (44/12)
```

**Précaution :** la colonne `carbon_biomass_gCO2_m3` implique que la concentration (ind m⁻³) a déjà été calculée et jointe. Si elle vient d'un fichier labo seul, vérifier si c'est une valeur par individu ou par volume d'eau.

---

# Quelles colonnes de features lipidiques image retrouve-t-on dans LOKI (EcoTaxa 2331) ?

Le LOKI image des copépodes avec leur sac lipidique visible. Des features sont calculées depuis l'image pour estimer la condition lipidique sans analyse biochimique.

**Colonnes LOKI spécifiques (observées dans les exports EcoTaxa 2331) :**

| Colonne | Définition | Unité |
|---------|------------|-------|
| `object_mean` / `fre_mean_grey` | Gris moyen de l'objet — proxy opacité | 0–255 |
| `fre_area` | Surface totale de l'objet | pixel² |
| `fre_area_exc` | Surface excluant les trous (prosome compact) | pixel² |
| `fre_feret` | Diamètre de Feret — longueur maximale — proxy longueur prosome | pixel |
| `fre_major` | Grand axe ellipse — proxy longueur corps | pixel |
| `fre_minor` | Petit axe ellipse — proxy largeur | pixel |
| `fre_esd` | Diamètre équivalent sphérique | pixel |

**Variables dérivées lipidiques calculées depuis les features LOKI :**

| Variable dérivée | Calcul | Signification |
|-----------------|--------|---------------|
| `lipid_sac_area_px` | Détection zone claire interne (sac lipidique) | pixel² |
| `prosome_area_px` | Surface du prosome = `fre_area_exc` | pixel² |
| `lipid_fullness` | `lipid_sac_area_px / prosome_area_px` | 0–1, proxy condition lipidique |
| `prosome_length_mm` | `fre_feret * acq_pixel` | mm |
| `esd_mm` | `fre_esd * acq_pixel` | mm |

**Interprétation lipid fullness :**
- > 0.5 → individu en bonne condition, probablement en diapause ou pré-diapause
- 0.2–0.5 → condition intermédiaire
- < 0.2 → individu maigre, post-diapause ou environnement pauvre

⚠️ `lipid_fullness` est un proxy non-invasif. La corrélation avec les wax esters biochimiques n'est pas parfaite — toujours indiquer la méthode dans le livrable.

---

# Comment calculer la concentration en copépodes (ind m⁻³) depuis EcoTaxa + EcoPart ?

La concentration est une variable **dérivée** — elle n'existe dans aucune source brute. Elle nécessite la jointure EcoTaxa + EcoPart.

**Formule :**
```python
# Pour un bin de profondeur
concentration_ind_m3 = (n_objects_taxon / sampled_volume_L) * 1000
# Facteur 1000 : conversion L → m³
```

**Variables requises :**
- `n_objects_taxon` — nombre d'objets annotés avec le taxon cible dans le bin (EcoTaxa)
- `sampled_volume_L` — `Sampled volume [L]` du bin EcoPart correspondant (EcoPart)
- Jointure validée : `obj_orig_id` → `profile_id` = `Profile` + `object_depth` ≈ `Depth [m]`

**Colonnes créées après calcul :**

| Colonne créée | Unité | Définition |
|---------------|-------|------------|
| `concentration_ind_m3` | ind m⁻³ | Concentration volumique du taxon |
| `concentration_ind_m2` | ind m⁻² | Concentration intégrée sur la colonne d'eau |
| `biomass_mgC_m3` | mgC m⁻³ | Biomasse carbone volumique (si carbone individuel connu) |
| `biomass_gCO2_m3` | g CO2 m⁻³ | Biomasse en équivalent CO2 volumique |

---

# Quelles sont les précautions pour les fichiers labo uploadés par l'utilisateur ?

Les fichiers labo ont une structure inconnue avant inspection. Règles à appliquer systématiquement :

| Situation | Règle |
|-----------|-------|
| Structure inconnue | Toujours appeler `inspect_file` avant tout traitement |
| Unités non indiquées | Demander confirmation à l'utilisateur avant calcul |
| Colonnes lipides en µg/ind vs mg/ind | Vérifier l'ordre de grandeur — µg pour petites espèces, mg pour *C. hyperboreus* |
| `carbon_biomass_gCO2_m3` sans concentration | La valeur est par individu ou par échantillon — clarifier avant d'interpréter |
| Noms d'espèces non standardisés | Vérifier la correspondance avec WoRMS avant de croiser avec EcoTaxa |
| Plusieurs réplicats | Ne pas moyenner sans vérifier l'homogénéité |
| Valeurs manquantes dans lipides | Signaler comme lacune — ne pas imputer |

*Sources : labo Maps (Université Laval) — données internes, non publiées sauf indication contraire*
*Dernière mise à jour : mai 2026*

---

# Quelles colonnes de contexte contient la source Taxonomie NeoLab (filets zooplancton, 2010-2025) ?

Mots-clés : NeoLab, taxonomie, SAMPLE_ID, ANALYSIS_ID, ANALYSIS_CONTRACT, filet, V-Tow, O-Tow, NET_MESH_SIZE, DEPTH_CALC_NET_FILTERED_VOL, FLOWMETER_CALC_VOL, station, deployment, zooplancton, copépode

Source labo NeoLab : campagnes filets 2010–2025 (contrats "Legacy Labo Fortier" et autres — KEBABB et DFO-D. Côté exclus). Chaque ligne = une combinaison analyse × taxon. Fichiers : `IDEA Taxonomy Zooplankton Abundances Data`, `IDEA Taxonomy Samples and Analyses Data`, et le fichier combiné avec biomasse.

**Colonnes de contexte d'échantillonnage :**

| Colonne | Type | Unité | Description |
|---------|------|-------|-------------|
| `SAMPLE_ID` | int | — | Identifiant unique de l'échantillon |
| `ANALYSIS_ID` | int | — | Identifiant unique de l'analyse |
| `ANALYSIS_CONTRACT` | varchar | — | Contrat d'analyse (ex. Legacy Labo Fortier) |
| `STATION_NAME` | varchar | — | Nom/identifiant de la station (ex. `350`) |
| `DEPLOYMENT_DATE_START` | date | — | Date de début de déploiement |
| `DEPLOYMENT_TIME_START` | time | — | Heure de début de déploiement |
| `CAST_NUMBER` | varchar | — | Numéro de cast / ordre du trait |
| `GEAR` | varchar | — | Engin de prélèvement (ex. `4x1m2`) |
| `TOW_TYPE` | varchar | — | Type de trait : `V-Tow` (vertical) ou `O-Tow` (oblique) |
| `NET_MESH_SIZE` | int | µm | Taille de maille du filet |
| `SAMPLING_NET_ID` | longtext | — | Inventaire des filets associés (colonne calculée) |
| `MIN_SAMPLE_DEPTH` | decimal | m | Profondeur minimale prélevée |
| `MAX_SAMPLE_DEPTH` | decimal | m | Profondeur maximale prélevée |
| `DEPTH_CALC_NET_FILTERED_VOL` | decimal | m³ | Volume filtré estimé par profondeur — V-Tow uniquement |
| `FLOWMETER_CALC_VOL` | decimal | m³ | Volume filtré estimé par débitmètre — V-Tow et O-Tow |

**Colonnes taxonomiques :**

| Colonne | Description |
|---------|-------------|
| `ZOOPLANKTON_CATEGORY` | Catégorie large : `copepod`, `non-copepod`, `fish`, `egg-like` |
| `TAXON_ID` | Identifiant taxonomique (ex. `Calanus glacialis`, `Calanus spp.`) |
| `KINGDOM`, `PHYLUM`, `CLASS`, `ORDER`, `FAMILY` | Classification Linné jusqu'à la famille |
| `TAXON_LIFE_DEVELOPMENT_STAGE` | Stade de développement : `Copepodid`, `Nauplius`, etc. |
| `TAXON_SIZE_CATEGORY` | Catégorie de taille optionnelle (peut être NULL) |

**Règle :** `DEPTH_CALC_NET_FILTERED_VOL` est NULL pour les O-Tow ou si MIN/MAX profondeurs sont absentes. `FLOWMETER_CALC_VOL` est NULL si le débitmètre n'était pas opérationnel. Vérifier la disponibilité des deux volumes avant toute normalisation.

---

# Liste exhaustive des colonnes d'abondance et biomasse par stade — source Taxonomie NeoLab (fichier combiné)

Mots-clés : abondance stade, biomasse stade, C1, C2, C3, C4, C5, adulte mâle M, adulte femelle F, COP_NS, COPEPODID, N1, N2, N3, N4, N5, N6, NAUP_NS, NAUPLIUS, ALL_STAGES, ind./m3, µg C m-3, Large Fract, Small Fract, fraction taille, copépodite, nauplius, sample abund, depth vol, flowmeter vol

Le fichier combiné (copepod abund & biomass) expose 93 colonnes. Toutes les colonnes d'abondance et de biomasse sont `is_computed=1` (déjà normalisées).

**Colonnes de contexte (1–21) — identiques aux deux fichiers :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 1 | `SAMPLE_ID` | Identifiant de l'échantillon | — |
| 2 | `ANALYSIS_ID` | Identifiant de l'analyse | — |
| 3 | `ANALYSIS_CONTRACT` | Contrat d'analyse | — |
| 4 | `STATION_NAME` | Nom de la station | — |
| 5 | `DEPLOYMENT_DATE_START` | Date de déploiement | — |
| 6 | `DEPLOYMENT_TIME_START` | Heure de déploiement | — |
| 7 | `CAST_NUMBER` | Numéro de cast | — |
| 8 | `GEAR` | Engin (ex. 4x1m2) | — |
| 9 | `TOW_TYPE` | V-Tow ou O-Tow | — |
| 10 | `NET_MESH_SIZE` | Taille de maille | µm |
| 11 | `SAMPLING_NET_ID` | Identifiants filets (calculé) | — |
| 12 | `MIN_SAMPLE_DEPTH` | Profondeur minimale | m |
| 13 | `MAX_SAMPLE_DEPTH` | Profondeur maximale | m |
| 14 | `DEPTH_CALC_NET_FILTERED_VOL` | Volume depth — V-Tow uniquement | m³ |
| 15 | `FLOWMETER_CALC_VOL` | Volume flowmeter — V-Tow et O-Tow | m³ |
| 16 | `TAXON_ID` | Espèce / taxon (ex. Calanus glacialis) | — |
| 17 | `KINGDOM` | Règne | — |
| 18 | `PHYLUM` | Embranchement | — |
| 19 | `CLASS` | Classe | — |
| 20 | `ORDER` | Ordre | — |
| 21 | `FAMILY` | Famille | — |

**Copépodite C1 (colonnes 22–26) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 22 | `C1_SAMPLE_ABUND (nbr of ind.)` | Comptage brut C1 dans l'échantillon | ind |
| 23 | `C1_ABUND (ind./m3 depth vol.)` | Abondance C1, normalisée par volume depth | ind m⁻³ |
| 24 | `C1_ABUND (ind./m3 flowmeter vol.)` | Abondance C1, normalisée par volume flowmeter | ind m⁻³ |
| 25 | `C1_BIOMASS (µg C m-3 depth vol.)` | Biomasse C1, volume depth | µg C m⁻³ |
| 26 | `C1_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse C1, volume flowmeter | µg C m⁻³ |

**Copépodite C2 (colonnes 27–31) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 27 | `C2_SAMPLE_ABUND (nbr of ind.)` | Comptage brut C2 | ind |
| 28 | `C2_ABUND (ind./m3 depth vol.)` | Abondance C2, volume depth | ind m⁻³ |
| 29 | `C2_ABUND (ind./m3 flowmeter vol.)` | Abondance C2, volume flowmeter | ind m⁻³ |
| 30 | `C2_BIOMASS (µg C m-3 depth vol.)` | Biomasse C2, volume depth | µg C m⁻³ |
| 31 | `C2_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse C2, volume flowmeter | µg C m⁻³ |

**Copépodite C3 (colonnes 32–36) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 32 | `C3_SAMPLE_ABUND (nbr of ind.)` | Comptage brut C3 | ind |
| 33 | `C3_ABUND (ind./m3 depth vol.)` | Abondance C3, volume depth | ind m⁻³ |
| 34 | `C3_ABUND (ind./m3 flowmeter vol.)` | Abondance C3, volume flowmeter | ind m⁻³ |
| 35 | `C3_BIOMASS (µg C m-3 depth vol.)` | Biomasse C3, volume depth | µg C m⁻³ |
| 36 | `C3_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse C3, volume flowmeter | µg C m⁻³ |

**Copépodite C4 (colonnes 37–41) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 37 | `C4_SAMPLE_ABUND (nbr of ind.)` | Comptage brut C4 | ind |
| 38 | `C4_ABUND (ind./m3 depth vol.)` | Abondance C4, volume depth | ind m⁻³ |
| 39 | `C4_ABUND (ind./m3 flowmeter vol.)` | Abondance C4, volume flowmeter | ind m⁻³ |
| 40 | `C4_BIOMASS (µg C m-3 depth vol.)` | Biomasse C4, volume depth | µg C m⁻³ |
| 41 | `C4_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse C4, volume flowmeter | µg C m⁻³ |

**Copépodite C5 (colonnes 42–46) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 42 | `C5_SAMPLE_ABUND (nbr of ind.)` | Comptage brut C5 | ind |
| 43 | `C5_ABUND (ind./m3 depth vol.)` | Abondance C5, volume depth | ind m⁻³ |
| 44 | `C5_ABUND (ind./m3 flowmeter vol.)` | Abondance C5, volume flowmeter | ind m⁻³ |
| 45 | `C5_BIOMASS (µg C m-3 depth vol.)` | Biomasse C5, volume depth | µg C m⁻³ |
| 46 | `C5_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse C5, volume flowmeter | µg C m⁻³ |

**Adulte mâle M (colonnes 47–51) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 47 | `M_SAMPLE_ABUND (nbr of ind.)` | Comptage brut mâle adulte | ind |
| 48 | `M_ABUND (ind./m3 depth vol.)` | Abondance mâle, volume depth | ind m⁻³ |
| 49 | `M_ABUND (ind./m3 flowmeter vol.)` | Abondance mâle, volume flowmeter | ind m⁻³ |
| 50 | `M_BIOMASS (µg C m-3 depth vol.)` | Biomasse mâle, volume depth | µg C m⁻³ |
| 51 | `M_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse mâle, volume flowmeter | µg C m⁻³ |

**Adulte femelle F (colonnes 52–56) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 52 | `F_SAMPLE_ABUND (nbr of ind.)` | Comptage brut femelle adulte | ind |
| 53 | `F_ABUND (ind./m3 depth vol.)` | Abondance femelle, volume depth | ind m⁻³ |
| 54 | `F_ABUND (ind./m3 flowmeter vol.)` | Abondance femelle, volume flowmeter | ind m⁻³ |
| 55 | `F_BIOMASS (µg C m-3 depth vol.)` | Biomasse femelle, volume depth | µg C m⁻³ |
| 56 | `F_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse femelle, volume flowmeter | µg C m⁻³ |

**Copépodite stade non spécifié COP_NS (colonnes 57–61) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 57 | `COP_NS_SAMPLE_ABUND (nbr of ind.)` | Comptage brut copépodite non spécifié | ind |
| 58 | `COP_NS_ABUND (ind./m3 depth vol.)` | Abondance COP_NS, volume depth | ind m⁻³ |
| 59 | `COP_NS_ABUND (ind./m3 flowmeter vol.)` | Abondance COP_NS, volume flowmeter | ind m⁻³ |
| 60 | `COP_NS_BIOMASS (µg C m-3 depth vol.)` | Biomasse COP_NS, volume depth | µg C m⁻³ |
| 61 | `COP_NS_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse COP_NS, volume flowmeter | µg C m⁻³ |

**Copépodites agrégés COPEPODID = C1+C2+C3+C4+C5+M+F+COP_NS (colonnes 62–66) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 62 | `COPEPODID_SAMPLE_ABUND (nbr of ind.)` | Somme comptages copépodites | ind |
| 63 | `COPEPODID_ABUND (ind./m3 depth vol.)` | Abondance copépodites agrégés, volume depth | ind m⁻³ |
| 64 | `COPEPODID_ABUND (ind./m3 flowmeter vol.)` | Abondance copépodites agrégés, volume flowmeter | ind m⁻³ |
| 65 | `COPEPODID_BIOMASS (µg C m-3 depth vol.)` | Biomasse copépodites agrégés, volume depth | µg C m⁻³ |
| 66 | `COPEPODID_BIOMASS (µg C m-3 flowmeter vol.)` | Biomasse copépodites agrégés, volume flowmeter | µg C m⁻³ |

**Nauplius N1 (colonnes 67–69) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 67 | `N1_SAMPLE_ABUND (nbr of ind.)` | Comptage brut N1 | ind |
| 68 | `N1_ABUND (ind./m3 depth vol.)` | Abondance N1, volume depth | ind m⁻³ |
| 69 | `N1_ABUND (ind./m3 flowmeter vol.)` | Abondance N1, volume flowmeter | ind m⁻³ |

**Nauplius N2 (colonnes 70–72) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 70 | `N2_SAMPLE_ABUND (nbr of ind.)` | Comptage brut N2 | ind |
| 71 | `N2_ABUND (ind./m3 depth vol.)` | Abondance N2, volume depth | ind m⁻³ |
| 72 | `N2_ABUND (ind./m3 flowmeter vol.)` | Abondance N2, volume flowmeter | ind m⁻³ |

**Nauplius N3 (colonnes 73–75) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 73 | `N3_SAMPLE_ABUND (nbr of ind.)` | Comptage brut N3 | ind |
| 74 | `N3_ABUND (ind./m3 depth vol.)` | Abondance N3, volume depth | ind m⁻³ |
| 75 | `N3_ABUND (ind./m3 flowmeter vol.)` | Abondance N3, volume flowmeter | ind m⁻³ |

**Nauplius N4 (colonnes 76–78) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 76 | `N4_SAMPLE_ABUND (nbr of ind.)` | Comptage brut N4 | ind |
| 77 | `N4_ABUND (ind./m3 depth vol.)` | Abondance N4, volume depth | ind m⁻³ |
| 78 | `N4_ABUND (ind./m3 flowmeter vol.)` | Abondance N4, volume flowmeter | ind m⁻³ |

**Nauplius N5 (colonnes 79–81) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 79 | `N5_SAMPLE_ABUND (nbr of ind.)` | Comptage brut N5 | ind |
| 80 | `N5_ABUND (ind./m3 depth vol.)` | Abondance N5, volume depth | ind m⁻³ |
| 81 | `N5_ABUND (ind./m3 flowmeter vol.)` | Abondance N5, volume flowmeter | ind m⁻³ |

**Nauplius N6 (colonnes 82–84) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 82 | `N6_SAMPLE_ABUND (nbr of ind.)` | Comptage brut N6 | ind |
| 83 | `N6_ABUND (ind./m3 depth vol.)` | Abondance N6, volume depth | ind m⁻³ |
| 84 | `N6_ABUND (ind./m3 flowmeter vol.)` | Abondance N6, volume flowmeter | ind m⁻³ |

**Nauplius stade non spécifié NAUP_NS (colonnes 85–87) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 85 | `NAUP_NS_SAMPLE_ABUND (nbr of ind.)` | Comptage brut nauplius non spécifié | ind |
| 86 | `NAUP_NS_ABUND (ind./m3 depth vol.)` | Abondance NAUP_NS, volume depth | ind m⁻³ |
| 87 | `NAUP_NS_ABUND (ind./m3 flowmeter vol.)` | Abondance NAUP_NS, volume flowmeter | ind m⁻³ |

**Nauplii agrégés NAUPLIUS = N1+N2+N3+N4+N5+N6+NAUP_NS (colonnes 88–90) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 88 | `NAUPLIUS_SAMPLE_ABUND (nbr of ind.)` | Somme comptages nauplii | ind |
| 89 | `NAUPLIUS_ABUND (ind./m3 depth vol.)` | Abondance nauplii agrégés, volume depth | ind m⁻³ |
| 90 | `NAUPLIUS_ABUND (ind./m3 flowmeter vol.)` | Abondance nauplii agrégés, volume flowmeter | ind m⁻³ |

**Tous stades confondus ALL_STAGES = COPEPODID + NAUPLIUS (colonnes 91–93) :**

| # | Colonne | Description | Unité |
|---|---------|-------------|-------|
| 91 | `ALL_STAGES_SAMPLE_ABUND (nbr of ind.)` | Comptage total tous stades | ind |
| 92 | `ALL_STAGES_ABUND (ind./m3 depth vol.)` | Abondance totale, volume depth | ind m⁻³ |
| 93 | `ALL_STAGES_ABUND (ind./m3 flowmeter vol.)` | Abondance totale, volume flowmeter | ind m⁻³ |

*Note : les nauplii n'ont pas de colonnes biomasse dans ce fichier. Seuls les stades copépodites (C1–C5, M, F, COP_NS, COPEPODID) ont des colonnes `BIOMASS`.*

**Dans le fichier abondances seul (Zooplankton Abundances Data), colonnes supplémentaires :**

| Colonne | Description | Unité |
|---------|-------------|-------|
| `ZOOPLANKTON_CATEGORY` | `copepod`, `non-copepod`, `fish`, `egg-like` | — |
| `TAXON_LIFE_DEVELOPMENT_STAGE` | Stade de vie (Copepodid, Nauplius, etc.) | — |
| `TAXON_SIZE_CATEGORY` | Catégorie de taille (peut être NULL) | — |
| `Large Fract (ind./m3 depth vol)` | Fraction Grande (>1 mm), volume depth | ind m⁻³ |
| `Small Fract (ind./m3 depth vol)` | Fraction Petite (<1 mm), volume depth | ind m⁻³ |
| `Total abundance (ind./m3 depth vol)` | Large + Small, volume depth | ind m⁻³ |
| `DEPTH_CALC_VOL` | Volume filtré estimé par profondeur | m³ |
| `Large Fract (ind./m3 flowmeter vol)` | Fraction Grande (>1 mm), volume flowmeter | ind m⁻³ |
| `Small Fract (ind./m3 flowmeter vol)` | Fraction Petite (<1 mm), volume flowmeter | ind m⁻³ |
| `Total abundance (ind./m3 flowmeter vol)` | Large + Small, volume flowmeter | ind m⁻³ |
| `FLOWMETER_CALC_VOL` | Volume filtré estimé par débitmètre | m³ |

**Règle :** ne pas recalculer les colonnes normalisées depuis `SAMPLE_ABUND` sans vérifier quelle colonne de volume a été utilisée — depth et flowmeter donnent des valeurs différentes et ne sont pas interchangeables.
