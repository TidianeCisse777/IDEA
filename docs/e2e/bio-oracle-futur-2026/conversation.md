# Conversation E2E — Bio-ORACLE prospectif (planification d'expéditions)

Intention NeoLab : **anticiper l'évolution des conditions océaniques** (scénarios
climatiques SSP) pour justifier où et quand mener les futures expéditions
copépodes dans l'Arctique canadien. Couvre UC-G3 (enrichissement Bio-ORACLE
présent + scénarios futurs). Exécution multi-tour contre l'API locale
(`thread_id: e2e-biooracle-20260715`).

## 1. Exploration : variables, scénarios SSP, horizons

**Input**

> Je veux anticiper l'évolution des conditions océaniques pour planifier de futures expéditions copépodes dans l'Arctique canadien. Quelles données Bio-ORACLE : variables, scénarios SSP, horizons ? Sans requête lourde.

**Output**

- Variables : température, chlorophylle, salinité, oxygène, nitrate, fer dissous,
  PAR / atténuation lumineuse.
- Scénarios futurs : SSP1-1.9, SSP1-2.6, SSP2-4.5, SSP3-7.0, SSP4-6.0, SSP5-8.5.
- Horizons : baseline historique (2000–2018 / 2000–2020) ; futur SSP 2020–2100
  (décennies cibles type 2050, 2100).

**Statut : validé.** Panorama exploitable établi sans requête lourde.

## 2. Ancrage sur un fichier NeoLab conséquent

Pour ancrer la prospective sur des stations réelles (et non des points choisis à
la main), chargement d'un fichier NeoLab substantiel.

**Input**

> Charge data/demo/neolabs_taxonomy_2014_2020.tsv et inspecte : dimensions, période, stations distinctes, taxons, complétude des colonnes clés.

**Output**

- 7 093 lignes × 82 colonnes ; période 2014–2018 ; **125 stations distinctes** ;
  **199 taxons**.
- Complétude : latitude/longitude/date/profondeurs 100 %, abondance ind./m³
  93,8 %.

**Statut : validé.** Base réelle et conséquente pour la prospective.

## 3. Agrégation spatiale (surface homogène par zone)

Choix méthodologique : Bio-ORACLE est une grille climatique grossière (~0,05°) ;
à la surface, dans une même zone, la température et son delta futur sont
sensiblement homogènes. Interroger 125 points individuels n'apporte quasi rien de
plus que quelques centroïdes — pour bien plus de coût. On agrège d'abord.

**Input**

> Agrège les 125 stations en grappes (lat au degré, lon au 2 degrés) : centroïde, n_stations, abondance moyenne. run_pandas local, pas de réseau.

**Output** (7,5 s, local)

| centroïde | n_stations | abondance moy. (ind./m³) |
|---|---:|---:|
| (71.47, -91.99) | 37 | 8,60 |
| (68.77, -80.84) | 34 | 162,78 |
| (69.17, -100.70) | 27 | 84,03 |
| (68.49, -103.43) | 27 | 42,32 |

**Statut : validé.** 125 stations → 4 grappes.

## 4. Couplage présent vs futur (SSP5-8.5 2050)

**Input**

> Couple ces 4 centroïdes avec Bio-ORACLE température de surface, baseline et SSP5-8.5 2050 ; donne le delta par centroïde.

**Output** (30 s, 2 requêtes Bio-ORACLE)

| centroïde | baseline °C | SSP5-8.5 2050 °C | Δ °C |
|---|---:|---:|---:|
| (71.47, -91.99) | -1,144 | -0,045 | **+1,098** |
| (68.77, -80.84) | -0,428 | +0,804 | **+1,232** |
| (69.17, -100.70) | -0,825 | +0,343 | **+1,168** |
| (68.49, -103.43) | -0,528 | +0,646 | **+1,174** |

Les 4 grappes passent du négatif au voisinage / au-dessus de 0 °C d'ici 2050
(franchissement du seuil de gel). Réchauffement max à (68,77 N / -80,84 W).
Note : l'horizon 2100 renvoie 404 sur Bio-ORACLE (seul 2050 disponible ici).

**Statut : validé.** Analyse descriptive, sans interprétation écologique.

## 5. Carte de priorisation des futures expéditions

**Input**

> Carte à bulles : position = lon/lat sur l'Arctique canadien, couleur = réchauffement projeté 2050, taille = abondance copépodes.

**Output**

Carte NorthPolarStereo, 4 grappes, couleur = Δ 2050, taille = abondance,
barre de couleur + légende de taille. Le contrat graphique a d'abord **bloqué**
la 1ʳᵉ tentative (`size mapping must use abundance_ind_L`) ; l'agent a corrigé et
la 2ᵉ est passée. Lecture : la grappe (68,77 N / -80,84 W) cumule la plus forte
abondance (162 ind./m³) et le plus fort réchauffement (+1,23 °C) → priorité.

**Statut : validé.** Voir `figures/74f5bcad37a2.png` (version initiale) puis
`figures/58fdbc42c2ba.png` (**version finale, zones nommées** : Lancaster Sound,
Hudson Complex, Queen Maud E, Queen Maud W).

---

## Note outillage — driver observable

Le driver `scripts/dev/e2e_turn.py` a été réécrit pour **streamer chaque étape**
(appel d'outil + résultat, avec timestamp et temps écoulé) au lieu de n'imprimer
que la réponse finale. Motivation : une première tentative en point par point sur
125 stations tournait > 6 min sans aucun retour visible. Avec l'agrégation + le
driver observable, chaque tour est passé à 8–30 s avec progression visible.
