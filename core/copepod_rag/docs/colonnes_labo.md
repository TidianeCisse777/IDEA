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
