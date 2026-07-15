# Conversation E2E — Baie de Baffin 2024

Ce journal conserve les inputs utilisateur, les outputs fonctionnels observés
et les décisions de validation. Les blocs techniques détaillés des appels de
tools ne sont pas reproduits ; leurs résultats et erreurs le sont.

## 1. Exploration

**Input**

> Explore les données disponibles dans la baie de Baffin en 2024.

**Output**

- 62 samples trouvés dans 3 projets : 17498 (56), 14853 (3), 14859 (3).
- Instrument : UVP6.
- Sélection mémorisée :
  `selection_baie_de_baffin_2024_01_01_2024_12_31`.
- Source : EcoTaxa.

**Statut : validé.**

## 2. Découpage géographique exploratoire

**Input**

> Découpe la zone en secteurs géographiques simples et propose un secteur pour poursuivre l’étude.

**Output**

Trois secteurs proposés, dont « Centre du plateau » recommandé. Le découpage
n'était pas calculé depuis une table complète de coordonnées.

**Statut : non retenu.** La zone baie de Baffin 2024 était déjà suffisante.

## 3. Présentation des samples

**Input**

> Présente les samples disponibles pour cette étude, de façon synthétique et sans lancer d’export.

**Output**

- 62 samples, 3 projets, UVP6.
- Répartition : 17498 (56), 14853 (3), 14859 (3).
- Aucun export lancé.

**Statut : validé.**

## 4. Sélection et préparation des opérations

**Input**

> Pour la suite, utilise les trois samples du projet 14859, exporte-les et enrichis-les avec Amundsen et EcoPart.

**Output**

| sample | station | date | latitude | longitude |
|---|---|---|---:|---:|
| 14859000001 | RA09 | 2024-08-22 | 82.399 | -60.847 |
| 14859000002 | RA18 | 2024-08-29 | 81.940 | -60.357 |
| 14859000003 | RA02 | 2024-08-14 | 77.241 | -79.121 |

Plan d'export préparé. EcoPart et Amundsen laissés en attente de la présence du
dataset EcoTaxa en session.

**Statut : validé comme plan.**

## 5. Export EcoTaxa

**Input**

> Confirme et lance uniquement l’export des trois samples du projet 14859.

**Output**

- Export réussi : 3 650 lignes, 145 colonnes.
- Dataset persistant chargé en session.
- Export sans filtre taxonomique Copepoda explicite.

**Statut : validé.**

## 6. Enrichissements EcoPart et Amundsen

**Input**

> Enrichis ces données avec EcoPart et Amundsen.

**Output**

- EcoPart 1064 : réussite, 3 650/3 650 lignes appariées, 216 colonnes.
- Amundsen : échec, colonne `sampledatetime` absente.

**Statut : partiel.** EcoPart validé, Amundsen à corriger.

## 7. Correction Amundsen

**Input**

> Corrige la colonne de temps et relance uniquement l’enrichissement Amundsen sur les données déjà enrichies avec EcoPart.

**Output**

- Colonnes utilisées : `object_lat`, `object_lon`, `object_date`,
  `object_depth_min`.
- 3 650/3 650 lignes appariées.
- Table finale : `df_amundsen_enriched_e0e05e03797d`.

**Statut : validé.**

## 8. Audit de la table finale

**Input**

> Fais un audit des données présentes dans la table finale enrichie, sans interprétation écologique.

**Output**

- Dimensions : 3 650 lignes, 226 colonnes.
- 3 samples et 3 650 `object_id` uniques.
- Coordonnées, dates, profondeurs, volume EcoPart, température et pression :
  100 % complets.
- Salinité : 3 649/3 650 valeurs, soit 99,97 %.
- Profondeur : 3,39–525,79 m.
- Température : -1,529–0,445 °C.
- Salinité : 28,317–34,532 PSU.
- Pression : 3–516 dbar.

**Statut : validé.**

## 9. Première analyse d'abondance

**Input**

> Explore et analyse les abondances : calcule l’abondance par litre et par mètre cube, établis les profils verticaux, puis décris leur variation avec les données environnementales disponibles. Reste descriptif, sans interprétation écologique.

**Output**

Un premier graphique a été généré, mais sans tableau numérique complet. Un
indicateur `m5` non demandé a été introduit et les axes du panneau
environnemental étaient incorrectement partagés.

**Statut : non retenu.**

## 10. Table d'abondance initiale

**Input**

> Commence par calculer et présenter un tableau des abondances de copépodes par sample et par tranche de profondeur, en ind./L et ind./m³. Explique précisément le calcul et ne génère pas encore de graphique.

**Output**

- `n_cop_objects` : nombre d'objets par sample et bin.
- ind./L = nombre d'objets / volume EcoPart en litres.
- ind./m³ = ind./L × 1 000.
- RA18 absent car le filtre cherchait littéralement `copepod`.

**Statut : non retenu, filtre taxonomique incomplet.**

## 11. Audit du filtre taxonomique

**Input**

> Vérifie le filtre taxonomique utilisé et explique pourquoi le sample RA18 est absent du tableau.

**Output**

RA18 contient 88 objets validés, dont `Calanoida`, mais aucune annotation ne
contenait littéralement `copepod`. Calanoida avait donc été exclu à tort.

**Statut : diagnostic validé.**

## 12. Recalcul taxonomique élargi

**Input**

> Recalcule les abondances en incluant Copepoda et tous ses descendants taxonomiques, notamment Calanoida, puis présente le tableau corrigé pour les trois samples.

**Output**

Le filtre a été élargi manuellement à Copepoda, Calanoida, Heterorhabdidae,
Paraeuchaeta, Metridia, Calanus et quelques libellés associés. Les trois stations
apparaissent, mais le bin RA02 à 512 m était dupliqué et la sélection ne reposait
pas sur une hiérarchie taxonomique formelle.

**Statut : exploratoire avec limites.**

## 13. Corrélations sur les seuls bins positifs

**Input**

> Utilise les données environnementales pour analyser les corrélations avec l’abondance des copépodes. Fais une analyse descriptive au niveau sample–profondeur, sans interprétation écologique.

**Output**

23 couples sample–profondeur positifs. Les bins sans copépode avaient été
exclus, créant un biais de sélection.

**Statut : non retenu.**

## 14. Corrélations incluant les zéros

**Input**

> Recalcule les corrélations avec tous les bins échantillonnés, en attribuant une abondance nulle aux bins sans copépode. Utilise une seule mesure environnementale par sample et profondeur.

**Output**

| variable | Pearson | Spearman | n bins |
|---|---:|---:|---:|
| température | -0,0771 | -0,0647 | 137 |
| salinité | -0,2357 | -0,1402 | 136 |
| pression | -0,1680 | -0,0881 | 137 |

Une incohérence persistait pour RA18, présenté avec dix bins à zéro alors qu'un
Calanoida avait été trouvé auparavant.

**Statut : exploratoire, limite RA18 documentée.**

## 15. Profils et relations environnementales — première version

**Input**

> Génère un profil vertical des abondances par station et des graphiques montrant leur relation avec la température, la salinité et la pression.

**Output**

Les quatre panneaux partageaient par erreur leur axe vertical, mélangeant
profondeur et abondance.

**Statut : non retenu.**

## 16. Profils et relations environnementales — version corrigée

**Input**

> Régénère ces graphiques avec des axes indépendants. Inverse uniquement l’axe de profondeur du profil vertical et conserve un axe d’abondance normal pour les trois relations environnementales.

**Output**

Figure corrigée avec axes indépendants, profondeur inversée uniquement sur le
profil et trois nuages de points environnementaux.

**Statut : validé.** Voir `figures/d4dfa42be8ea.png`.

## 17. Premières cartes à bulles

**Input**

> Crée des cartes à bulles par tranche de profondeur. Place les stations selon leurs coordonnées, représente l’abondance en ind./L par la taille des points et la température par leur couleur. Produis une seconde figure équivalente pour la salinité, sans interpolation spatiale.

**Output**

Une seule carte de température a été produite, avec des profondeurs individuelles
et un panneau profond superposé, sans légende de taille suffisante.

**Statut : non retenu.**

## 18. Carte de température corrigée

**Input**

> Refais uniquement la carte de température avec trois strates : 0–50 m, 50–200 m et plus de 200 m. Agrège une valeur par station et strate, garde la même étendue géographique et les mêmes échelles dans les trois panneaux, ajoute une légende de taille et affiche les abondances nulles par des cercles vides. N’effectue aucune interpolation.

**Output**

Trois strates fixes, une valeur moyenne par station et strate, emprise et
échelles communes, bulles vides pour les zéros, aucune interpolation.

**Statut : validé.** Voir `figures/1601c1e416e3.png`.

## 19. Carte de salinité

**Input**

> Produis maintenant la carte équivalente avec la salinité comme couleur, en conservant strictement les mêmes strates, l’emprise et l’échelle de taille des bulles.

**Output**

Carte directement comparable à la carte de température avec couleur = salinité.

**Statut : validé.** Voir `figures/83520de95d2a.png`.

## 20. Diagramme température–salinité

**Input**

> Crée un diagramme température–salinité au niveau sample–profondeur. Représente l’abondance en ind./L par la taille des points, la profondeur par leur couleur et distingue les stations. Affiche les abondances nulles avec des cercles vides.

**Output**

- X : salinité ; Y : température.
- Taille : abondance en ind./L.
- Couleur : profondeur.
- Contour : station.
- Cercle vide : abondance nulle.

**Statut : validé.** Voir `figures/bfd0b2c04141.png`.

## 21. Clôture PDF

**Input**

> Clôture cette étude avec un rapport PDF détaillé. Reprends le contexte baie de Baffin 2024, les trois samples du projet 14859, l’export, les enrichissements EcoPart et Amundsen avec leur couverture, l’audit, les analyses d’abondance et de corrélation, et uniquement les graphiques validés. Documente aussi les limites, les incohérences et les tentatives non retenues. Cite uniquement les sources réellement utilisées.

**Output**

Première génération refusée par le manifeste à cause de DOI non déclarés.

**Statut : échec documenté.**

## 22. PDF sans DOI non déclarés

**Input**

> Régénère le rapport sans DOI. Utilise uniquement les URLs des projets EcoTaxa et EcoPart effectivement utilisés et la source Amundsen réellement utilisée, toutes déclarées dans le manifeste de traçabilité. N’ajoute aucune autre référence.

**Output**

PDF généré, puis corrigé pour intégrer les couvertures exactes et l'échec initial
Amundsen. Contrôle final : 13 pages A4, quatre figures validées, 533 853 octets.

**Statut : livré.** Voir
`rapport_abondances_copepodes_baie_baffin_2024.pdf`.
