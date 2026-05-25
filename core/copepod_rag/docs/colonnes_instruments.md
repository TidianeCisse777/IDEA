# colonnes_instruments.md
# Colonnes exhaustives des exports EcoTaxa par instrument
# Source officielle : Picheral & Mériguet 2025, https://doi.org/10.5281/zenodo.14704251
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Comment identifier l'instrument depuis un fichier EcoTaxa ?

Mots-clés : instrument, acq_instrument, UVP5, UVP6, ZooScan, FlowCam, LOKI, acq_id, préfixe instrument

Colonne `acq_instrument` dans le header du TSV :
- `uvp5` → UVP5
- `uvp6` → UVP6
- `zooscan` → ZooScan
- `flowcam` → FlowCam

Si la colonne est absente, vérifier le préfixe de `acq_id` :
- commence par `uvp5` ou `sn0` → UVP5
- commence par `zooscan` → ZooScan
- commence par `flowcam` → FlowCam

Toutes les colonnes de mesure objet (`object_*`) sont identiques entre UVP5, UVP6, ZooScan et FlowCam — seules les colonnes `sample_*` et `acq_*` diffèrent par instrument.

---

# Que signifient les colonnes sample_* dans un export UVP5 ?

Mots-clés : UVP5, sample_id, sample_profileid, sample_cruise, sample_stationid, sample_bottomdepth, sample_ctdrosettefilename, météo, yoyo

Source : Picheral & Mériguet 2025 — feuille UVP5

| Colonne | Description | Unité |
|---------|-------------|-------|
| `sample_id` | Nom du sample (profil ou série temporelle) | texte |
| `sample_profileid` | Nom du dossier brut de la séquence `[HDRYYYYMMDDHHMMSS]` | texte |
| `sample_cruise` | Nom de la campagne | texte |
| `sample_ship` | Nom du navire | texte |
| `sample_stationid` | Nom de la station | texte |
| `sample_bottomdepth` | Profondeur du fond à la position d'échantillonnage | m |
| `sample_ctdrosettefilename` | Nom du fichier CTD associé | texte |
| `sample_dn` | Flag jour/nuit | code |
| `sample_yoyo` | Type de sample : D=descente, Y=yoyo, H=autre | code |
| `sample_winddir` | Direction du vent | degrés |
| `sample_windspeed` | Vitesse du vent | nœuds |
| `sample_seastate` | État de la mer | échelle Beaufort |
| `sample_nebuloussness` | Nébulosité | octa |
| `sample_comment` | Commentaire | texte |
| `sample_barcode` | Code-barre du sample | texte |

---

# Que signifient les colonnes acq_* dans un export UVP5 ?

Mots-clés : UVP5, acq_id, acq_sn, acq_volimage, acq_pixel, calibration, seuil segmentation, gain, shutter, volume image

Source : Picheral & Mériguet 2025 — feuille UVP5

| Colonne | Description | Unité |
|---------|-------------|-------|
| `acq_id` | uvp5 + sample_id | texte |
| `acq_sn` | sn + numéro de série UVP5 | texte |
| `acq_instrument` | `uvp5` | texte |
| `acq_volimage` | Volume imagé par image | L |
| `acq_pixel` | **Dimension d'un pixel dans le plan imagé — clé pour conversion mm** | mm |
| `acq_aa` | Facteur de calibration Aa | — |
| `acq_exp` | Facteur de calibration Exp | — |
| `acq_threshold` | Seuil de segmentation niveaux de gris (0–255) | — |
| `acq_smbase` | Taille minimale pour comptage/mesure | pixel² |
| `acq_smzoo` | Taille minimale pour sauvegarde de la vignette | pixel² |
| `acq_gain` | Gain | — |
| `acq_shutterspeed` | Code obturateur UVP5SD | — |
| `acq_exposure` | Durée obturateur UVP5HD + 60 | µs |
| `acq_erase_border_blob` | Flag objets touchant les bords (0=non, 1=oui) | booléen |
| `acq_choice` | Image complète [0] ou vignette [1] si objet > smzoo | booléen |
| `acq_ratio` | Ratio d'agrandissement de la vignette | — |

---

# Que signifient les colonnes process_* dans un export UVP5 ?

Mots-clés : UVP5, process_id, Zooprocess, process_pixel, process_calibration, process_upper, process_gamma, process_esdmin, process_esdmax

Source : Picheral & Mériguet 2025 — feuille UVP5

| Colonne | Description |
|---------|-------------|
| `process_id` | zooprocess + sample_id |
| `process_software` | Version Zooprocess |
| `process_date` | Date du traitement `[YYYYMMDD]` |
| `process_time` | Heure du traitement `[HHMMSS]` |
| `process_first_img` | Première image du profil |
| `process_last_img` | Dernière image du profil |
| `process_pixel` | Dimension pixel dans le plan imagé | mm |
| `process_upper` | Seuil de segmentation |
| `process_gamma` | Valeur gamma pour les vignettes EcoTaxa |
| `process_esdmin` | Taille minimale objet | mm |
| `process_esdmax` | Taille maximale objet | mm |
| `process_calibration` | Date/heure calibration UVP5 `[YYYYMMDD_HHMM]` |

---

# Que signifient les colonnes object_* de métadonnées et annotation ?

Mots-clés : object_id, object_lat, object_lon, object_date, object_time, object_depth_min, object_depth_max, annotation, taxon, hierarchy

Ces colonnes sont communes à UVP5, UVP6 et ZooScan.
Source : Picheral & Mériguet 2025

| Colonne | Description | Unité |
|---------|-------------|-------|
| `object_id` | acq_id + numéro objet dans l'image traitée | texte |
| `object_lat` | Latitude d'échantillonnage | degrés décimaux |
| `object_lon` | Longitude d'échantillonnage | degrés décimaux |
| `object_date` | Date UTC d'échantillonnage | YYYYMMDD |
| `object_time` | Heure UTC d'échantillonnage | HHMMSS |
| `object_depth_min` | Profondeur minimale d'échantillonnage | m |
| `object_depth_max` | Profondeur maximale d'échantillonnage | m |
| `object_annotation_status` | Statut EcoTaxa : V=validé, P=prédit, D=douteux, N=aucun | code |
| `object_annotation_category` | Taxon dans EcoTaxa (display_name) | texte |
| `object_annotation_hierarchy` | Lignée taxonomique dans EcoTaxa | texte |
| `object_annotation_person_name` | Nom de l'annotateur | texte |
| `object_annotation_date` | Date d'annotation | YYYYMMDD |
| `object_rawvig` | Date/heure et index des images brutes sources | texte |
| `object_lat_end` | Latitude fin (pour trait horizontal) | degrés |
| `object_lon_end` | Longitude fin (pour trait horizontal) | degrés |
| `complement_info` | Information complémentaire | texte |
| `object_link` | Lien vers site web défini par l'utilisateur | URL |

**Profondeur à utiliser :**
```python
object_depth = (object_depth_min + object_depth_max) / 2
```

---

# Que signifient les colonnes object_* de mesures morphométriques ?

Mots-clés : morphométrie, object_area, object_area_exc, object_feret, object_major, object_minor, object_esd, object_mean, object_cv, acq_pixel

Ces colonnes sont les mesures d'image. Unités en **pixels** sauf indication.
Clés pour le labo Maps marquées **★**.

| Colonne | Description | Usage labo |
|---------|-------------|-----------|
| `object_area` | Surface de l'objet | pixel² | — |
| `object_area_exc` | Surface excluant les trous | pixel² | ★ taille réelle |
| `object_%area` | % surface avec trous | % | — |
| `object_feret` | **Diamètre de Feret — longueur max** | pixel | ★ proxy longueur prosome |
| `object_major` | Grand axe de l'ellipse ajustée | pixel | ★ longueur |
| `object_minor` | Petit axe de l'ellipse ajustée | pixel | — |
| `object_esd` | Diamètre équivalent sphérique : 2×√(area/π) | pixel | — |
| `object_elongation` | Indice d'élongation : major/minor | — | — |
| `object_width` | Largeur du rectangle englobant | pixel | — |
| `object_height` | Hauteur du rectangle englobant | pixel | — |
| `object_mean` | **Gris moyen — proxy opacité/contenu intestinal** | 0–255 | ★ état alimentaire |
| `object_stddev` | Écart-type des niveaux de gris | — | — |
| `object_median` | Médiane des niveaux de gris | 0–255 | — |
| `object_min` | Gris minimum (0=noir) | 0–255 | — |
| `object_max` | Gris maximum (255=blanc) | 0–255 | — |
| `object_cv` | Coeff. variation gris : 100×(stddev/mean) | % | — |
| `object_circ.` | Circularité : (4π×area)/perim² — 1=cercle parfait | — | — |
| `object_circex` | Circularité excluant trous | — | — |
| `object_fractal` | Dimension fractale du contour | — | — |
| `object_convarea` | Surface enveloppe convexe | pixel² | — |
| `object_convperim` | Périmètre enveloppe convexe | pixel | — |
| `object_perim.` | Longueur du contour externe | pixel | — |
| `object_angle` | Angle entre axe major et axe x de l'image | degrés | — |
| `object_intden` | Densité intégrée : area × mean | — | — |
| `object_skelarea` | Surface du squelette de l'objet | pixel² | — |
| `object_centroids` | Distance entre centroïde de masse et centroïde de gris | pixel | — |
| `object_symetrieh` | Indice de symétrie bilatérale horizontale | — | — |
| `object_symetriev` | Indice de symétrie bilatérale verticale | — | — |
| `object_histcum1` | Gris au 1er quartile de l'histogramme cumulé | 0–255 | — |
| `object_histcum2` | Gris au 2e quartile | 0–255 | — |
| `object_histcum3` | Gris au 3e quartile | 0–255 | — |
| `object_slope` | Pente de l'histogramme cumulé normalisé | — | — |
| `object_skew` | Asymétrie de l'histogramme de gris | — | — |
| `object_kurt` | Kurtosis de l'histogramme de gris | — | — |
| `object_thickr` | Ratio épaisseur max / épaisseur moy | — | — |
| `object_fcons` | Mesure de contraste (texture) | — | — |

**Conversion pixels → mm (obligatoire avant toute analyse) :**
```python
longueur_mm = object_feret * acq_pixel
Note : `acq_pixel` correspond à la dimension d'un pixel en mm dans les colonnes `acq_*`.
```

---

# Quelles colonnes instrumentales UVP5 sont généralement utiles dans une table d'analyse ?

Mots-clés : UVP5, table analyse, sample, process, acquisition, acq_pixel, acq_volimage, sample_profileid, CTD, calibration

Source : exports EcoTaxa UVP5 observés + Picheral & Mériguet 2025

Un export UVP5 suit généralement le schéma `object_*`, `sample_*`, `process_*`, `acq_*`. Les colonnes disponibles varient selon le traitement et le projet ; il faut donc profiler le TSV avant de créer une table clean.

Colonnes `sample_*` souvent utiles quand elles varient :
| Colonne | Description | Unité |
|---------|-------------|-------|
| `sample_id` | Identifiant du sample EcoTaxa | id |
| `sample_profileid` | Identifiant du profil ou dossier brut UVP5 | texte |
| `sample_ctdrosettefilename` | Nom du fichier CTD rosette associé | texte |
| `sample_windspeed` | Vitesse du vent | nœuds |
| `sample_nebuloussness` | Nébulosité | octa |
| `sample_comment` | Commentaire terrain ou traitement | texte |
| `sample_lat` | Latitude du sample | degrés décimaux |
| `sample_long` | Longitude du sample | degrés décimaux |

Colonnes `process_*` souvent utiles pour traçabilité et calibration :
| Colonne | Description | Unité |
|---------|-------------|-------|
| `process_id` | Identifiant du traitement Zooprocess | id |
| `process_software` | Version ou nom du logiciel de traitement | texte |
| `process_date` | Date du traitement image | date |
| `process_time` | Heure du traitement image | heure |
| `process_first_img` | Première image traitée | index/image |
| `process_last_img` | Dernière image traitée | index/image |
| `process_pressure_gain` | Paramètre de gain/correction pression | paramètre |
| `process_calibration` | Calibration UVP utilisée | texte |
| `process_pixel` | Dimension pixel utilisée au traitement | mm |
| `process_upper` | Seuil ou paramètre supérieur de segmentation | paramètre |
| `process_gamma` | Gamma appliqué aux vignettes ou au traitement | paramètre |
| `process_esdmin` | ESD minimum retenu | mm |
| `process_esdmax` | ESD maximum retenu | mm |

Colonnes `acq_*` souvent utiles :
| Colonne | Description | Unité |
|---------|-------------|-------|
| `acq_id` | Identifiant de l'acquisition UVP5 | id |
| `acq_sn` | Numéro de série UVP5 | texte |
| `acq_volimage` | Volume imagé par image | L |
| `acq_aa` | Facteur de calibration Aa | — |
| `acq_exp` | Facteur de calibration Exp | — |
| `acq_pixel` | Dimension d'un pixel dans le plan imagé | mm |

Colonnes utiles pour analyses UVP5 :
- `acq_pixel` : obligatoire pour convertir les tailles en mm
- `acq_volimage` : utile pour interpréter le volume par image, mais pas suffisant seul pour une concentration robuste
- `sample_profileid` : regroupe les objets par profil UVP5
- `sample_ctdrosettefilename` : point d'entrée possible vers les données CTD

---

# Quelles colonnes UVP5 peuvent être retirées car vides ou constantes ?

Mots-clés : UVP5, nettoyage colonnes, nulles, constantes, sparse, métadonnées globales, object_link, complement_info, acq_instrument

Source : profils null/constance observés sur exports EcoTaxa UVP5

Règle : les colonnes toujours nulles, constantes, ou très sparse avec une seule valeur non nulle peuvent être retirées de la table d'analyse. Elles doivent plutôt être conservées comme métadonnées globales si elles décrivent le dataset.

Colonnes souvent nulles selon les exports :
```text
object_link
complement_info
sample_dataportal_descriptor
sample_barcode
acq_exposure
classif_auto_id
classif_auto_score
classif_auto_when
object_sunpos
```

Colonnes souvent constantes à déplacer en métadonnées si elles ne varient pas :
```text
object_annotation_status
object_xmg5
object_ymg5
object_compentropy
object_compmean
object_compslope
object_compm1
object_compm2
object_compm3
object_tag
sample_cruise
sample_ship
sample_stationid
sample_bottomdepth
sample_dn
sample_winddir
sample_seastate
sample_yoyo
acq_instrument
acq_file_description
acq_tasktype
acq_disktype
acq_shutterspeed
acq_gain
acq_threshold
acq_smbase
acq_smzoo
acq_erase_border_blob
acq_choice
acq_ratio
```

Interprétation RAG :
- Si une question porte sur le dataset complet, les constantes décrivent le contexte global.
- Si une question porte sur des différences entre objets, ces colonnes ne doivent pas être proposées comme variables explicatives.
- Si `object_annotation_status` est constant car l'export a déjà été filtré sur les annotations validées, il peut être retiré de la table clean mais conservé en métadonnée.

---

# Quelles colonnes morphométriques UVP5 sont variables et souvent conservées ?

Mots-clés : UVP5, morphométrie variable, taille, forme, intensité, texture, symétrie, ratios, object_feret, object_area_exc

Source : exports EcoTaxa UVP5 observés + Picheral & Mériguet 2025

Les colonnes ci-dessous sont des candidates fréquentes pour une table d'analyse. Elles doivent être conservées si elles existent dans le TSV et si elles varient. Les unités sont en pixels sauf indication contraire.

| Famille | Colonnes |
|---------|----------|
| Taille | `object_area`, `object_area_exc`, `object_esd`, `object_feret`, `object_major`, `object_minor`, `object_width`, `object_height` |
| Position image | `object_x`, `object_y`, `object_xm`, `object_ym`, `object_bx`, `object_by`, `object_xstart`, `object_ystart` |
| Forme | `object_perim.`, `object_angle`, `object_circ.`, `object_fractal`, `object_elongation`, `object_convperim`, `object_convarea`, `object_circex` |
| Intensité | `object_mean`, `object_stddev`, `object_mode`, `object_min`, `object_max`, `object_intden`, `object_median`, `object_range`, `object_cv` |
| Texture | `object_skew`, `object_kurt`, `object_slope`, `object_histcum1`, `object_histcum2`, `object_histcum3`, `object_fcons`, `object_sr` |
| Symétrie | `object_symetrieh`, `object_symetriev`, `object_symetriehc`, `object_symetrievc` |
| Ratios dérivés | `object_perimareaexc`, `object_feretareaexc`, `object_perimferet`, `object_perimmajor`, `object_cdexc`, `object_kurt_mean`, `object_skew_mean`, `object_convperim_perim`, `object_convarea_area`, `object_symetrieh_area`, `object_symetriev_area`, `object_median_mean`, `object_median_mean_range`, `object_skeleton_area` |
| Classes de gris normalisées | `object_nb1`, `object_nb2`, `object_nb3`, `object_nb1_area`, `object_nb2_area`, `object_nb3_area`, `object_nb1_range`, `object_nb2_range`, `object_nb3_range` |

Colonnes prioritaires pour une analyse copépodes :
- longueur : `object_feret`, `object_major`
- largeur : `object_minor`
- taille équivalente : `object_esd`
- surface réelle image : `object_area_exc`
- forme : `object_elongation`, `object_circ.`
- opacité/contraste : `object_mean`, `object_stddev`, `object_cv`

Conversion recommandée :
```python
length_mm = object_feret * acq_pixel
area_mm2 = object_area_exc * (acq_pixel ** 2)
```

---

# Quelles sont les différences principales entre UVP6 et UVP5 ?

Mots-clés : UVP6, UVP5, différences instrument, sample_sampletype, sample_integrationtime, argoid, object_vig_left_position

Source : Picheral & Mériguet 2025 — feuille UVP6

Colonnes `sample_*` et `acq_*` légèrement différentes. Les colonnes `object_*` de mesure sont identiques à UVP5, **sauf** :
- Absent en UVP6 : `object_bx`, `object_by`, `object_xstart`, `object_ystart`, `object_xmg5`, `object_ymg5`, `object_nb1/2/3`, `object_comp*`, `object_sym*` (certains)
- Ajouté en UVP6 : `object_vig_left_position`, `object_vig_top_position`

Nouvelles colonnes `sample_*` spécifiques UVP6 :
| Colonne | Description |
|---------|-------------|
| `sample_sampletype` | P=pression, T=série temporelle |
| `sample_integrationtime` | Temps d'intégration pour sampletype=T | s |
| `sample_argoid` | ID du vecteur/plateforme hébergeant l'UVP6 |
| `sample_sampledatetime` | Date/heure première image `[YYYYMMDD-HHMMSS]` |

Nouvelle colonne `acq_*` : `acq_instrument` = `uvp6`

---

# Quelles colonnes sample_* sont spécifiques aux exports ZooScan ?

Mots-clés : ZooScan, sample_tow_nb, sample_net_type, sample_tot_vol, sample_net_mesh, sample_zmax, sample_zmin, acq_scan_resolution

Source : Picheral & Mériguet 2025 — feuille ZooScan

Le ZooScan traite des **échantillons de filet** — les colonnes sample_* contiennent donc les métadonnées du trait de filet.

| Colonne | Description | Unité |
|---------|-------------|-------|
| `sample_id` | Nom du sample | texte |
| `sample_ship` | Navire | texte |
| `sample_program` | Nom du programme/campagne | texte |
| `sample_stationid` | Station | texte |
| `sample_bottomdepth` | Profondeur du fond | m |
| `sample_scan_operator` | Opérateur du scan | texte |
| `sample_tow_nb` | Nombre de traits dans le bocal | # |
| `sample_tow_type` | Type de déploiement : 1=oblique, 2=horizontal, 3=vertical, 0=autre | code |
| `sample_net_type` | Modèle de filet | texte |
| `sample_tot_vol` | Volume total filtré | m³ |
| `sample_net_mesh` | Maille du filet | µm |
| `sample_zmax` | Profondeur minimale d'échantillonnage | m |
| `sample_zmin` | Profondeur maximale d'échantillonnage | m |
| `sample_net_surf` | Surface de la gueule du filet | m² |
| `sample_comment` | Commentaires | texte |
| `sample_duration` | Durée du trait | minutes |
| `sample_ship_speed` | Vitesse du navire pendant le trait | nœuds |
| `sample_cable_length` | Longueur de câble | m |
| `sample_cable_angle` | Angle du câble | degrés |
| `sample_tot_vol_qc` | QC volume : 1=flowmètre, 2=calculé, 3=estimé | code |
| `sample_depth_qc` | QC profondeur : 1=capteur, 2=calculé, 3=estimé | code |
| `sample_sample_qc` | QC 4 chiffres : étanchéité/richesse/conditionnement/perturbateurs | code |

**Colonnes acq_* ZooScan spécifiques :**
| Colonne | Description |
|---------|-------------|
| `acq_instrument` | `zooscan` (numéro de série) |
| `acq_min_mesh` | Maille minimale fraction tamisée | µm |
| `acq_max_mesh` | Maille maximale fraction tamisée | µm |
| `acq_sub_part` | Facteur de sous-échantillonnage |
| `acq_scan_resolution` | Résolution du scan | dpi |
| `acq_pixel` | **Dimension pixel — obligatoire pour conversion mm** | mm |

---

# Quels sont les pièges courants dans les colonnes EcoTaxa ?

Mots-clés : pièges EcoTaxa, profondeur midpoint, acq_pixel, object_area_exc, annotation validée, taxon, object_feret, object_random_value

| Piège | Règle |
|-------|-------|
| Utiliser `object_depth_min` seul | Toujours `(object_depth_min + object_depth_max) / 2` |
| Convertir pixels sans `acq_pixel` | Jamais. `acq_pixel` est obligatoire |
| Confondre `object_area` et `object_area_exc` | Pour taille réelle : `object_area_exc` (exclut trous) |
| Utiliser annotations `P` ou `D` | Seul `object_annotation_status = V` (validé) est fiable |
| Chercher le taxon dans `txo_display_name` | Ce nom existe dans certains projets — le nom officiel est `object_annotation_category` |
| Confondre `object_feret` (longueur max) et `object_major` (axe ellipse) | Pour longueur prosome : `object_feret` est le plus robuste |
| `object_mean` = opacité = contenu intestinal | Valeur haute = objet sombre = plein (nourri). Valeur basse = transparent = vide |
| Utiliser une colonne constante comme variable | La déplacer en métadonnée globale du dataset |
| Oublier qu'un export peut déjà être filtré sur les annotations validées | Si `object_annotation_status` est constant, le documenter comme filtre d'export |
| Traiter `object_random_value` comme donnée scientifique | C'est une valeur interne EcoTaxa, à ignorer pour l'analyse |

*Source : Picheral M. & Mériguet Z. (2025). Description of the metadata and data issued from Zooprocess and UVPapp applications. https://doi.org/10.5281/zenodo.14704251*
*Observations génériques ajoutées à partir de profils null/constance d'exports EcoTaxa UVP5, mai 2026*
*Dernière mise à jour : mai 2026*
