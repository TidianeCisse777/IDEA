# colonnes_sources.md
# Colonnes des sources de données — EcoTaxa / EcoPart / Amundsen
# Basé sur exports réels : EcoTaxa projets 1165 (UVP5) et 2331 (LOKI), EcoPart projet 105
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Comment les sources EcoTaxa, EcoPart et Amundsen s'articulent-elles ?

Trois sources de données distinctes, complémentaires :

```
Instrument (UVP5, LOKI, ZooScan)
        ↓
    [EcoPart]   — particules agrégées + CTD + volume échantillonné (niveau profil/bin)
        ↓
    [EcoTaxa]   — classification taxonomique (niveau objet/vignette individuelle)

    [Amundsen]  — CTD officielle navire (température, salinité, O2, nutrients)
```

**Règle fondamentale :**
- EcoTaxa = objets individuels avec taxon, pas de volume échantillonné
- EcoPart = profils agrégés avec volume, pas d'objets individuels
- Pour calculer une concentration → jointure EcoTaxa + EcoPart obligatoire
- Amundsen = référence physico-chimique officielle, indépendante du UVP

---

# Quelles colonnes identifiants et position contient EcoTaxa 1165 ?

**Source :** export EcoTaxa projet `1165` | **Confiance :** observé sur exports réels

⚠️ Ce projet utilise le préfixe `obj_*` pour les métadonnées objet — différent du préfixe `object_*` du projet LOKI 2331. Ne pas homogénéiser.

```
1165 : object_id  +  obj_*  +  fre_*  +  txo_*
2331 : object_id  +  object_*
```

| Colonne | Définition | Unité |
|---------|------------|-------|
| `object_id` | Identifiant interne EcoTaxa de l'objet | id |
| `sample_id` | Identifiant d'échantillon EcoTaxa | id |
| `obj_orig_id` | ID original instrument, ex. `ips_007_899` — **clé de jointure EcoPart** | texte |
| `obj_objdate` | Date de l'acquisition | date |
| `obj_objtime` | Heure de l'acquisition | time |
| `obj_latitude` | Latitude de l'objet | degrés |
| `obj_longitude` | Longitude de l'objet | degrés |
| `obj_depth_min` | Profondeur minimum de l'objet | m |
| `obj_depth_max` | Profondeur maximum de l'objet | m |
| `txo_display_name` | Taxon affiché par EcoTaxa | texte |

**Profondeur de l'objet à calculer :**
```python
object_depth = (obj_depth_min + obj_depth_max) / 2
```
Ne jamais utiliser `obj_depth_min` seul comme profondeur.

---

# Quelles colonnes de morphométrie fre_* contient EcoTaxa 1165 ?

**Source :** export EcoTaxa projet `1165` | **Confiance :** observé sur exports réels

Colonnes de mesures de forme — unités en **pixels**, conversion en mm obligatoire.

| Colonne | Définition |
|---------|------------|
| `fre_area` | Aire de l'objet |
| `fre_major` | Grand axe de l'ellipse |
| `fre_minor` | Petit axe de l'ellipse |
| `fre_feret` | Diamètre de Feret — longueur maximale — **proxy longueur prosome** |
| `fre_esd` | Diamètre équivalent sphérique |
| `fre_width` | Largeur de la vignette |
| `fre_height` | Hauteur de la vignette |

**Conversion pixels → mm :**
```python
longueur_mm = fre_feret * acq_pixel
```
`acq_pixel` dans les métadonnées du projet ou du sample.

⚠️ `fre_*` = morphométrie image uniquement. Pas de poids, lipides ou biomasse.

---

# Quelles colonnes d'annotation taxonomique contient EcoTaxa 2331 LOKI ?

**Source :** export EcoTaxa projet `2331` | **Usage :** taxonomie et stades des copépodes | **Confiance :** observé

Schéma différent du projet UVP5 — noms de colonnes distincts.

| Colonne | Définition |
|---------|------------|
| `object_id` | Identifiant EcoTaxa |
| `object_lat` | Latitude objet |
| `object_lon` | Longitude objet |
| `object_date` | Date objet |
| `object_time` | Heure objet |
| `object_depth_min` | Profondeur minimum |
| `object_depth_max` | Profondeur maximum |
| `object_annotation_status` | Statut annotation : `V` = validé, `P` = prédit |
| `object_annotation_category` | **Taxon annoté — champ principal** |
| `object_annotation_hierarchy` | Hiérarchie taxonomique complète |
| `sample_id` | Identifiant échantillon |
| `sample_profileid` | Identifiant de profil |
| `sample_cruise` | Campagne |
| `sample_ship` | Navire |
| `sample_stationid` | Station |
| `classif_auto_name` | Classification automatique proposée |
| `classif_auto_score` | Score de confiance (0–1) |

⚠️ Pas de colonnes morphométrie dans LOKI — pas de taille individuelle, poids, lipides.
⚠️ Seul `object_annotation_status = V` (validé) est fiable pour les analyses.

**Différence clé UVP5 vs LOKI :**
- UVP5 (proj. 1165) : taxon dans `txo_display_name`
- LOKI (proj. 2331) : taxon dans `object_annotation_category`

---

# Quelles colonnes de profil et CTD contient EcoPart 105 ?

**Source :** export EcoPart `uvp5_sn008_ips_amundsen_2018` | **Confiance :** observé

EcoPart travaille au niveau **profil + bin de profondeur**. Pas d'objets individuels.

| Colonne | Définition | Unité |
|---------|------------|-------|
| `Profile` | Identifiant du profil UVP, ex. `ips_007` — **clé de jointure EcoTaxa** | texte |
| `Rawfilename` | Nom du fichier source UVP | texte |
| `yyyy-mm-dd hh:mm` | Date/heure du profil | datetime |
| `Project` | Nom du projet EcoPart | texte |
| `Depth [m]` | Profondeur du bin | m |
| `Sampled volume [L]` | Volume d'eau échantillonné — **obligatoire pour concentration** | L |
| `temperature [degc]` | Température du bin (capteur UVP) | degC |
| `practical salinity [psu]` | Salinité pratique | psu |
| `oxygen [umol kg-1]` | Oxygène dissous massique | µmol kg⁻¹ |
| `oxygen [ml l-1]` | Oxygène dissous volumique | ml l⁻¹ |
| `chloro fluo [mg chl m-3]` | Fluorescence chlorophylle | mg chl m⁻³ |
| `nitrate [umol l-1]` | Nitrate | µmol l⁻¹ |
| `pressure [db]` | Pression | db |
| `LPM (...) [# l-1]` | Concentration particules par classe de taille | # l⁻¹ |
| `LPM biovolume (...) [mm3 l-1]` | Biovolume particules par classe de taille | mm³ l⁻¹ |
| `qc flag` | Indicateur qualité | code |

⚠️ `temperature [degc]` d'EcoPart ≠ `TE90` d'Amundsen — deux capteurs distincts.

---

# Comment joindre EcoTaxa 1165 avec EcoPart 105 ?

Pour calculer une concentration de zooplancton (ind m⁻³), il faut joindre les deux sources.

**Clés de jointure :**
```
EcoTaxa  obj_orig_id  →  extraire profile_id  →  EcoPart Profile
EcoTaxa  object_depth →  matcher              →  EcoPart Depth [m]
```

**Étapes concrètes :**
1. Extraire `profile_id` depuis `obj_orig_id` : enlever le suffixe numérique
   ```python
   # ex. "ips_007_899" → "ips_007"
   profile_id = "_".join(obj_orig_id.split("_")[:-1])
   ```
2. Joindre `profile_id` (EcoTaxa) = `Profile` (EcoPart)
3. Calculer `object_depth = (obj_depth_min + obj_depth_max) / 2`
4. Matcher au bin EcoPart le plus proche — tolérance recommandée : **±5 m**
5. Récupérer `Sampled volume [L]` du bin matché

**Colonnes créées par le script de jointure (absentes des sources brutes) :**

| Colonne créée | Définition |
|---------------|------------|
| `profile_id` | Extrait de `obj_orig_id` |
| `object_depth` | Midpoint `obj_depth_min` / `obj_depth_max` |
| `ecopart_depth` | Profondeur du bin EcoPart matché |
| `depth_delta_m` | Différence absolue de profondeur |
| `depth_match_quality` | `within_5m_bin` / `outside_ecopart_sample_range` |

---

# Quelles colonnes physico-chimiques contient la CTD Amundsen ?

**Datasets Amundsen confirmés :**
| Dataset | Contenu | Accès |
|---------|---------|-------|
| `ca-cioos_ccin-12713` | CTD officielle | ERDDAP direct |
| `ca-cioos_ccin-12447` | Navigation GPS | ERDDAP direct |
| `ca-cioos_ccin-13248` | Scientific Event Log | on-demand via formulaire |

| Colonne | Définition | Unité |
|---------|------------|-------|
| `platform_name` | Nom du navire | texte |
| `cruise_name` | Nom de la campagne | texte |
| `cruise_number` | Numéro de campagne | texte/int |
| `cast_number` | Numéro de cast CTD | int |
| `station` | Station d'échantillonnage | texte |
| `time` / `time (UTC)` | Heure initiale du cast | UTC |
| `latitude` | Latitude initiale | degrees_north |
| `longitude` | Longitude initiale | degrees_east |
| `depth` | Profondeur | m |
| `PRES` | Pression | decibars |
| `TE90` | Température ITS-90 | degC |
| `PSAL` | Salinité pratique | PSU |
| `OXYM` | Oxygène dissous | µM |
| `FLOR` | Fluorescence chlorophylle-a | µg/L |
| `NTRA` | Nitrate NO3-N | mmol/m³ |

**Équivalences langage naturel → colonne Amundsen :**
```
"température"           → TE90
"salinité"              → PSAL
"oxygène"               → OXYM
"fluorescence" / "chla" → FLOR
"nitrate"               → NTRA
```

**Jointure EcoPart → Amundsen — validée sur profil test :**
```
EcoPart Profile     = ips_007        →  Amundsen cast_number = 7, station = 1
EcoPart time        = 2018-07-16 13:54:01
Amundsen time       = 2018-07-16T13:57:04Z  (delta = 3.07 min)
EcoPart lat/lon     = 68.3094 / -60.3926
Amundsen lat/lon    = 68.3096 / -60.3925  (delta < 0.001°)
delta profondeur médian = 0.227 m / max = 0.484 m
```
La liaison se fait par proximité **date/heure + lat/lon + profondeur** — pas par clé directe.
Validée sur `ips_007` ; à généraliser aux autres profils par la même logique.

---

# Quels sont les pièges courants avec EcoTaxa, EcoPart et Amundsen ?

| Piège | Source | Règle |
|-------|--------|-------|
| Calculer concentration depuis EcoTaxa seul | EcoTaxa | `Sampled volume [L]` est dans EcoPart — jointure obligatoire |
| Utiliser `obj_depth_min` comme profondeur | EcoTaxa UVP5 | Toujours utiliser le midpoint `(min + max) / 2` |
| Chercher taxon dans `txo_display_name` sur un fichier LOKI | EcoTaxa LOKI | LOKI utilise `object_annotation_category` |
| Faire confiance à `classif_auto_score` sans vérifier | EcoTaxa | Seul `object_annotation_status = V` est fiable |
| Confondre température EcoPart et Amundsen | EcoPart/Amundsen | Deux capteurs distincts — ne pas mélanger |
| Joindre EcoPart → Amundsen par clé directe | EcoPart/Amundsen | Pas de clé directe — jointure par proximité date/heure + lat/lon. Validée sur `ips_007` ↔ `cast_number=7`. À généraliser aux autres profils. |

*Basé sur exports réels : EcoTaxa projets 1165 et 2331, EcoPart projet 105, Amundsen ERDDAP*
*Jointure EcoPart↔Amundsen validée sur profil ips_007 — à généraliser*
*Dernière mise à jour : mai 2026*
