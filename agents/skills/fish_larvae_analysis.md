---
name: fish_larvae_analysis
version: 1.0.0
triggers:
  - Active table recognised as fish larvae / ichthyoplankton
forbidden_when:
  - Active table has another biological profile
requires:
  - "file:loaded"
next_tool: null
max_tokens: 900
---

# Analyse de larves de poissons

Une ligne CalCOFI correspond typiquement à un taxon × stade larvaire × trait
de filet. Préserver ce grain avant toute somme, moyenne ou carte.

## Colonnes centrales

- `scientific_name` et `common_name` : taxon observé.
- `larvae_stage` : préflexion, flexion ou postflexion. C'est un stade de
  développement, jamais un taxon.
- `larvae_stage_count` : nombre observé dans le matériel traité.
- `larvae_10m2` : abondance standardisée par 10 m².
- `larvae_1000m3` : abondance standardisée par 1 000 m³ seulement si numérique.
- `volume_sampled`, `tow_type`, `net_type`, `latitude`, `longitude`, `time` :
  contexte du trait.

## Règles d'analyse

1. Agréger des comptages seulement après avoir choisi le taxon, le stade, le
   trait et la période à comparer.
2. Ne jamais transformer une valeur d'abondance vide en zéro.
3. Ne pas comparer directement `larvae_10m2` et une métrique volumique sans une
   conversion explicitement justifiée par les champs disponibles.
4. Pour une carte, agréger au niveau du trait ou de la station avant de tracer
   des lignes taxon × stade superposées.
5. Les associations avec température, salinité ou Bio-ORACLE sont descriptives
   dans cette application ; ne pas les présenter comme une cause biologique.

## Réponse

Nommer le taxon, le ou les stades, le champ d'abondance et son unité. Signaler
les valeurs manquantes ou l'impossibilité de convertir une unité avant un
graphique ou une comparaison.
