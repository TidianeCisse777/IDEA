# Scénario E2E — Archipel arctique canadien 2024 (leg4)

Exécution manuelle multi-tour réalisée le 14 juillet 2026 contre l'API locale de
l'agent (`thread_id: e2e-newzone-20260714`). Même méthode que le scénario
[baffin-2024](../baffin-2024/README.md), sur une **nouvelle zone** : projet
EcoTaxa 17498 (leg4), distinct de Baffin (leg3, projet 14859).

## Périmètre

- Zone : archipel arctique canadien (Barrow/Peel → nord de la baie de Baffin)
- Période : 8 septembre – 1er octobre 2024
- Projet EcoTaxa : 17498 (leg4)
- Samples : `17498000023` (RA76), `17498000061` (RA41), `17498000039` (RA25)
- Stations : RA76 (74.60 N / -93.71 W), RA41 (79.50 N / -73.02 W),
  RA25 (81.41 N / -64.23 W)
- Enrichissements : EcoPart 1100 et Amundsen CTD
- Analyse : abondances descriptives et relations avec température, salinité et
  pression, sans interprétation écologique

## Artefacts

- [Conversation et validations](conversation.md)
- [Défauts observés et priorités](DEFECTS_AND_PRIORITIES.md)
- [Rapport PDF final](rapport_abondances_copepodes_archipel_arctique_2024.pdf) (7 pages)
- [Profil vertical + relations environnementales](figures/8fb539cd78ca.png)
- [Diagramme température–salinité](figures/ba77f9dda90a.png)

## Résultat final

- Export EcoTaxa : 3 samples, **26 038 lignes**, 145 colonnes
- EcoPart 1100 : 26 038/26 038 lignes appariées, couverture 100 %, 216 colonnes
- Amundsen CTD : réussi du premier coup (contrairement à Baffin), 26 038/26 038
  lignes appariées, table finale 226 colonnes
- Table d'abondance canonique : 184 bins de 5 m, dont 130 à zéro, sélection
  stricte par nœud taxonomique `Copepoda`
- Corrélations descriptives (zéros inclus, 54 bins) : température Pearson
  -0,180 / Spearman -0,207 ; salinité -0,306 / -0,326 ; pression -0,181 / -0,321
- Une figure validée (profil vertical + trois relations environnementales)

## But de ce scénario

Reproduire la méthode Baffin sur une zone neuve **et** éprouver en conditions
réelles les contrats scientifiques récemment fusionnés. Bilan des contrats :

| Contrat | Comportement observé | Verdict |
|---|---|---|
| Taxonomie stricte (nœud Copepoda) | Sélection par hiérarchie, pas de libellé littéral | ✅ tient |
| Table sample–profondeur canonique | Bins 5 m, zéros conservés ; **refuse** les valeurs env. contradictoires par bin | ✅ tient |
| Provenance d'enrichissement | EcoPart + Amundsen appariés à 100 %, colonnes résolues sans intervention | ✅ tient |
| Graph contracts | Figure §9 validée ; rendu §10 **bloqué** faute de `graph_contract` | ✅ tient |

## Correctif de code apporté pendant le scénario

Ajout du tool `list_ecotaxa_project_samples(project_id)` (lecture seule du cache
`samples_cache`) qui liste les samples d'un projet avec leur `sample_id`
numérique et leur label. Motif : aucun tool exposé au LLM ne faisait le pont
label (`am_leg4_RA76_1`) → `sample_id` numérique (`17498000023`), ce qui bloquait
l'export. Règle de routage ajoutée au system prompt. Tests :
`tests/test_list_ecotaxa_project_samples.py` (2 verts).

## Limites connues

- Les corrélations sont descriptives et ne constituent pas des tests
  inférentiels.
- Le diagramme température–salinité et le PDF ont d'abord échoué (voir §10–§11),
  puis ont été **produits après correctifs** (persistance canonique + allow-list
  DOI du livrable). Les deux défauts sont corrigés et testés.
- Les cartes à bulles par strate (température, salinité) du scénario Baffin
  n'ont pas été reproduites ici.
