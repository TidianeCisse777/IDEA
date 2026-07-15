# Scénario E2E — Baie de Baffin 2024

Exécution manuelle multi-tour réalisée le 14 juillet 2026 contre l'API locale de
l'agent (`chat_id: e2e-baffin-scientific-20260714`).

## Périmètre

- Zone : baie de Baffin
- Période : 2024
- Projet EcoTaxa : 14859
- Samples : `14859000001`, `14859000002`, `14859000003`
- Stations : RA09, RA18, RA02
- Enrichissements : EcoPart 1064 et Amundsen CTD
- Analyse : abondances descriptives et relations avec température, salinité et
  pression, sans interprétation écologique

## Artefacts

- [Conversation et validations](conversation.md)
- [Défauts observés et priorités](DEFECTS_AND_PRIORITIES.md)
- [Rapport PDF final](rapport_abondances_copepodes_baie_baffin_2024.pdf)
- [Profils et relations environnementales](figures/d4dfa42be8ea.png)
- [Carte à bulles — température](figures/1601c1e416e3.png)
- [Carte à bulles — salinité](figures/83520de95d2a.png)
- [Diagramme température–salinité](figures/bfd0b2c04141.png)

## Résultat final

- Export EcoTaxa : 3 samples, 3 650 lignes, 145 colonnes
- EcoPart : 3 650/3 650 lignes appariées, couverture 100 %, 216 colonnes
- Amundsen : première tentative échouée (`sampledatetime` absente), seconde
  tentative réussie avec `object_date`, 3 650/3 650 lignes appariées
- Table finale : 3 650 lignes, 226 colonnes
- PDF : 13 pages, quatre figures validées

## Limites connues

- La sélection taxonomique corrigée repose sur une liste explicite de libellés
  et non sur une hiérarchie taxonomique formellement résolue.
- RA18 a présenté une incohérence entre deux calculs successifs ; les résultats
  restent exploratoires.
- Les corrélations sont descriptives et ne constituent pas des tests
  inférentiels.
- Les cartes représentent seulement trois stations et n'utilisent aucune
  interpolation spatiale.
- Le PDF contient encore une phrase générique indiquant que les nombres bruts
  ne sont pas documentés, alors que les valeurs exactes figurent dans les
  méthodes et le journal des opérations.
