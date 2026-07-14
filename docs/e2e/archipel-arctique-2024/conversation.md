# Conversation E2E — Archipel arctique canadien 2024 (leg4)

Ce journal conserve les inputs utilisateur, les outputs fonctionnels observés
et les décisions de validation. Les blocs techniques détaillés des appels de
tools ne sont pas reproduits ; leurs résultats et erreurs le sont. Exécution
multi-tour contre l'API locale de l'agent (`thread_id: e2e-newzone-20260714`).

## 1. Exploration des projets disponibles

**Input**

> Liste les projets EcoTaxa disponibles et les zones géographiques qu'ils couvrent, de façon synthétique et sans lancer d'export. Je veux choisir une zone d'étude autre que la baie de Baffin.

**Output**

| project_id | projet | bbox (S/W/N/E) | instrument | n_samples | période |
|---:|---|---|---|---:|---|
| 42 | UVP5 GREEN EDGE Ice Camp 2015 | 67.48 / -63.79 / 67.48 / -63.79 | UVP5SD | 19 | 2015-04-19 → 2015-06-21 |
| 14622 | LOKI_ArcticNet_2015 | 67.48 / -63.79 / 67.48 / -63.79 | Loki | 2 | 2015-04-22 → 2015-04-24 |
| 14844 | uvp6_sn000006hf_2024_am_leg2 | 67.27 / -64.37 / 68.14 / -59.02 | UVP6 | 5 | 2024-07-30 → 2024-08-06 |
| 14859 | uvp6_sn000006hf_2024_am_leg3 | 77.24 / -79.12 / 82.40 / -60.36 | UVP6 | 3 | 2024-08-14 → 2024-08-29 |
| 17498 | uvp6_sn000006hf_2024_am_leg4 | 73.74 / -93.71 / 81.41 / -64.23 | UVP6 | 64 | 2024-09-08 → 2024-10-01 |

Projet 2331 signalé comme accessible mais absent du cache local pour la couverture.

**Statut : validé.** Zone retenue : projet 17498 (leg4), distinct de Baffin (leg3, 14859).

## 2. Présentation des samples du projet 17498

**Input**

> Présente de façon synthétique les samples du projet EcoTaxa 17498 : identifiant, station si disponible, date, latitude, longitude et profondeur max. Ne lance aucun export. Propose ensuite trois samples représentatifs répartis géographiquement pour une étude ciblée.

**Output**

| sample_id | station | date_time | latitude | longitude | profondeur max |
|---|---|---:|---:|---:|---:|
| am_leg4_RA76_1 | RA76 | 20241001-020009 | 74.6024 | -93.7093 | 48.95 |
| am_leg4_RA41_1 | RA41 | 20240916-125350 | 79.4981 | -73.0212 | 173.82 |
| am_leg4_RA25_2 | RA25 | 20240908-145330 | 81.4133 | -64.2278 | 55.08 |

Trois samples représentatifs proposés, répartis du sud-ouest (RA76, Barrow/Peel)
au nord-est (RA25, nord de la baie de Baffin).

**Statut : validé.** Sélection retenue : RA76, RA41, RA25.

## 3. Sélection et plan d'export

**Input**

> Pour la suite, utilise les trois samples am_leg4_RA76_1, am_leg4_RA41_1 et am_leg4_RA25_2 du projet 17498. Prépare le plan d'export et d'enrichissement EcoPart + Amundsen, mais ne lance encore aucun export.

**Output — première tentative (refus)**

L'agent a refusé : il réclamait les `sample_id` **numériques** et ne pouvait pas
les déduire des labels `am_leg4_RA*`. Diagnostic : aucun tool exposé au LLM ne
faisait le pont label → `sample_id` numérique (les tools de présentation
montrent le label, l'export exige le numéro). Le refus était correct au regard
de la règle « pas de valeur inventée ».

**Correctif apporté**

Ajout du tool `list_ecotaxa_project_samples(project_id)` (lecture seule du cache
`samples_cache`) qui liste chaque sample avec son `sample_id` numérique, son
label, sa station et ses coordonnées. Règle de routage ajoutée au system prompt :
résoudre les `sample_id` numériques via ce tool avant tout export, sans jamais
en inventer. Tests TDD : `tests/test_list_ecotaxa_project_samples.py` (2 verts).

**Output — seconde tentative (validée)**

L'agent a résolu lui-même les IDs via le nouveau tool, puis produit le plan :

| project_id | nb_samples | sample_ids |
|---:|---:|---|
| 17498 | 3 | 17498000023, 17498000039, 17498000061 |

- EcoPart : projet associé **1100** (`uvp6_sn000006hf_2024_am_leg4`).
- Amundsen : enrichissement prévu après export, sans lancement.

**Statut : validé.** Correctif d'outillage confirmé de bout en bout.

## 4. Export EcoTaxa

**Input**

> Confirme et lance uniquement l'export EcoTaxa des trois samples 17498000023, 17498000039 et 17498000061 du projet 17498.

**Output**

- Export réussi : **26 038 lignes, 145 colonnes** (volume nettement supérieur au
  scénario Baffin, 3 650 lignes).
- Dataset persistant chargé en session.

**Statut : validé (voir §6).**

## 5. Enrichissements EcoPart et Amundsen

**Input**

> Enrichis ces données EcoTaxa avec EcoPart (projet 1100) puis avec Amundsen CTD.

**Output**

| enrichissement | lignes appariées | couverture | nb colonnes |
|---|---:|---:|---:|
| EcoPart 1100 | 26 038 / 26 038 | 100 % | 216 |
| Amundsen CTD | 26 038 / 26 038 | 100 % | 226 |

À la différence du scénario Baffin (échec initial Amundsen sur `sampledatetime`
absente), l'enrichissement Amundsen a réussi du premier coup : le résolveur de
schéma déterministe a apparié les colonnes temporelles sans intervention.

**Statut : validé.**

## 6. Audit de la table finale

**Input**

> Fais un audit de la table finale enrichie, sans interprétation écologique : dimensions, samples et object_id uniques, complétude des colonnes clés, plages min–max.

**Output — première tentative (non retenue)**

L'agent a audité une table à **216 colonnes** et n'a trouvé ni température, ni
salinité, ni pression (« non trouvée », NA). Il avait audité la table EcoPart
(216 col) au lieu de la table finale Amundsen (226 col) — le piège du `df` nu
contre lequel le system prompt met déjà en garde.

**Input (correction)**

> L'audit portait sur la table à 216 colonnes (EcoPart), pas sur la finale à 226 (Amundsen). Reprends sur la table finale Amundsen avec la variable de session exacte.

**Output — seconde tentative (validée)**

| indicateur | valeur |
|---|---:|
| dimensions | 26 038 lignes × 226 colonnes |
| samples uniques | 3 |
| `object_id` uniques | 26 038 |
| profondeur (min–max) | 2,5 – 582,5 m |

| variable | colonne réelle | complétude | min | max |
|---|---|---:|---:|---:|
| température | `amundsen_te90_degC` | 100 % | -1,572 | 0,585 °C |
| salinité | `amundsen_psal_psu` | 100 % | 29,027 | 34,685 PSU |
| pression | `amundsen_pres_dbar` | 100 % | 3 | 572 dbar |
| volume EcoPart | `ecopart_Sampled volume [L]` | 100 % | 21,12 | 147,2 L |

**Statut : validé après correction.** Défaut observé : sélection implicite du
mauvais dataframe (`df` nu) au premier audit.

## 7. Table d'abondance par sample et profondeur

**Input**

> Calcule et présente un tableau des abondances de copépodes par sample et par tranche de 5 m, en ind./L et ind./m³. Sélectionne les copépodes strictement via la hiérarchie taxonomique (nœud Copepoda), pas par un libellé littéral. Explique le calcul, pas de graphique.

**Output**

- Table canonique sample–profondeur : une ligne par `sample_id × depth_bin`,
  **184 bins** dont **130 à zéro** (zéros conservés), 3 samples.
- Sélection stricte via le nœud taxonomique `Copepoda` (hiérarchie EcoTaxa),
  pas de filtre littéral `copepod`.
- Calcul : `ind./L = copepod_count / sampled_volume_L` ;
  `ind./m³ = ind./L × 1000`. Colonnes canoniques `copepod_count`,
  `sampled_volume_L`, `abundance_ind_L`, `abundance_ind_m3`.

**Statut : validé.** Contrats exercés en réel : taxonomie stricte + table
sample–profondeur canonique.

## 8. Corrélations abondance–environnement (zéros inclus)

**Input**

> Corrélations descriptives entre abondance (ind./L) et température, salinité, pression au niveau sample–profondeur, tous les bins (zéros inclus), une mesure env. par bin. Pearson, Spearman, n de bins.

**Output — première tentative (non retenue)**

Colonnes environnementales « non trouvées » : la table canonique bâtie au §7 ne
portait que l'abondance, pas les colonnes Amundsen. Même famille de défaut qu'au
§6 : l'analyse s'appuyait sur une table qui ne contenait pas les variables visées.

**Input (correction)**

> Reconstruis la table canonique en y intégrant, par bin (moyenne sample × bin), `amundsen_te90_degC`, `amundsen_psal_psu`, `amundsen_pres_dbar`, puis corrèle.

**Output — seconde tentative (validée)**

| variable | colonne | n bins | Pearson r | Spearman ρ |
|---|---|---:|---:|---:|
| température | `amundsen_te90_degC` | 54 | -0,1795 | -0,2065 |
| salinité | `amundsen_psal_psu` | 54 | -0,3058 | -0,3264 |
| pression | `amundsen_pres_dbar` | 54 | -0,1813 | -0,3209 |

**Statut : exploratoire, validé après correction.** Corrélations descriptives,
non inférentielles. Défaut observé : colonnes env. absentes de la table
canonique tant qu'elles n'y sont pas explicitement portées.

## 9. Profil vertical + relations environnementales

**Input**

> Figure combinant un profil vertical d'abondance (ind./L) par station (profondeur inversée) et trois nuages de points abondance–température, –salinité, –pression. Axes indépendants, abondance normale, seule la profondeur inversée.

**Output**

Figure générée : profil vertical avec profondeur inversée (0 en haut, 175 m en
bas), trois panneaux environnementaux à axes indépendants, abondance non
inversée. Le contrat de graphique (`vertical_profile` + `environment_relationships`)
a laissé passer la figure — axes indépendants et inversions conformes.

**Statut : validé.** Voir `figures/8fb539cd78ca.png`. Contrat graphique exercé
en réel.

## 10. Diagramme température–salinité — non retenu

**Input**

> Diagramme température–salinité au niveau sample–profondeur : X = salinité, Y = température, taille = ind./L, couleur = profondeur, distinction par station, cercles vides pour les zéros.

**Output**

Non produit après plusieurs tentatives. Deux causes réelles, toutes deux
attribuables aux contrats qui **tiennent** :

1. **Contrat sample–profondeur** : la reconstruction canonique portant la
   salinité comme colonne stable a été refusée — `amundsen_psal_psu` présente
   des valeurs contradictoires dans un même bin (`am_leg4_RA25_2`, 2,5 m). Le
   contrat refuse d'écraser silencieusement des valeurs env. divergentes ; il
   faut agréger (moyenne par bin) en amont.
2. **Contrat graphique** : un rendu tenté sans `graph_contract` explicite a été
   bloqué avant affichage.

Une fois l'agrégation demandée, l'agent n'a pas su assembler en session une
table portant à la fois `abundance_ind_L`, les colonnes CTD moyennées, une
station exploitable et une profondeur cohérente : les tables intermédiaires
(canonique du §8) ne sont pas persistées comme variables réutilisables entre
tours.

**Statut : non retenu.** Défaut de workflow : intermédiaires non persistés +
absence de colonne station/profondeur propre dans la table active. Les deux
contrats invoqués ont correctement bloqué les raccourcis incorrects.

## 11. Clôture PDF — bloquée par le manifeste

**Input**

> Clôture l'étude avec un rapport PDF : contexte, samples, export, enrichissements, audit, abondances, corrélations, figure validée, limites. Sources réellement utilisées uniquement, sans DOI.

**Output**

PDF non produit après trois tentatives, chacune butant sur une exigence
différente du manifeste de traçabilité :

1. Manifeste sans les **DOI attendus** par l'exporteur → refus.
2. Contexte d'étude incomplet (`objective`, `geographic_scope`,
   `temporal_scope`, `taxonomic_scope`, `selection_criteria` manquants) → refus.
3. Contexte complété et sources déclarées par URL : le **bloc de références
   auto-injecté a réintroduit des DOI** EcoTaxa/EcoPart, aussitôt rejetés comme
   non déclarés → refus.

**Statut : non retenu / bloqué.** Défaut réel : tension interne du manifeste du
livrable — il exige/auto-injecte des DOI d'un côté et les rejette de l'autre
selon le registre de sources. Contrairement à Baffin (projet 14859 sans DOI
enregistré, PDF finalement produit), les projets 17498 / EcoPart 1100 ont des
DOI au registre, ce qui déclenche la contradiction. À corriger côté
`deliverable_tool` / manifeste.

