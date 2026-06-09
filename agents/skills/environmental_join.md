---
name: environmental_join
description: Guides pandas joins between zooplankton tables and environmental sources such as CTD, Bio-ORACLE, or OGSL, preserving raw columns and choosing join keys explicitly. Use when the user asks how to join zooplancton with CTD, Bio-ORACLE, OGSL, station, cast, time, latitude/longitude, or depth data, or when a join strategy must be planned for environmental datasets.
---

# Environmental joins

Tu viens d'aborder une jointure entre zooplancton et source environnementale.

---

## Règle d'usage

- Utilise ce skill quand l'utilisateur veut joindre du zooplancton avec une CTD, Bio-ORACLE, OGSL, EcoTaxa, EcoPart, ou toute autre source environnementale.
- Traite toujours les colonnes brutes comme source de vérité.
- Ajoute des alias seulement en plus des colonnes d'origine, jamais à la place.

---

## Objectif

Produire une table de jointure traçable avec une règle de match explicite, des clés stables, et des indicateurs de qualité.

---

## Clés de jointure usuelles

- `station_id`
- `cast_id` ou `cast_number`
- `profile_id`
- `time`
- `latitude`
- `longitude`
- `depth` ou `Pres`

---

## Règles de base

1. Identifie la source environnementale avant d'écrire la jointure.
2. Choisis la clé la plus stable disponible.
3. Préserve les colonnes sources brutes.
4. Ajoute uniquement des alias de jointure non destructifs.
5. Documente la qualité du match avec `*_match_status` et des deltas.
6. Si une clé indispensable manque, demande-la au lieu d'inventer un match.

---

## Motifs pandas

- Match exact sur méta:
  - `merge(..., on=[...], how="left")`
- Match temporel proche:
  - `sort_values(...)` puis `merge_asof(..., direction="nearest")`
- Match de profondeur:
  - calculer `abs(depth_source - depth_target)` puis garder le minimum par groupe
- Match par point spatial:
  - utiliser `latitude` / `longitude` puis filtrer par scénario, variable ou couche

---

## Par source

- CTD verticale: joindre par station, cast, temps, puis profondeur ou pression.
- Bio-ORACLE: joindre par latitude, longitude, variable, scénario et `depth_layer`.
- OGSL: joindre par station ou mission, puis temps et profondeur.
- EcoTaxa + EcoPart: joindre par `profile_id` puis bin de profondeur.

---

## Sortie attendue

- Une table propre avec une ligne par observation et par match.
- Des colonnes de qualité comme `match_status`, `time_delta`, `depth_delta`, `distance_km`.
- Un résumé court des lignes matchées et non matchées.

---

## Interdits

- Ne pas inventer des valeurs manquantes.
- Ne pas mélanger profondeur exacte et couche de surface sans le dire.
- Ne pas supprimer les colonnes brutes.
- Ne pas interpréter biologiquement la jointure.
