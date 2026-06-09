# Skill: bio_oracle_query

Tu viens d'appeler `query_bio_oracle` ou `couple_zooplankton_bio_oracle`.
Les données Bio-ORACLE sont maintenant extraites ou couplées dans la session.

---

## Règle de routage

- Pour voir les datasets ou variables disponibles, appelle `list_bio_oracle_datasets`.
- Pour un aperçu rapide d'un point, appelle `preview_bio_oracle_point`.
- Pour charger, exporter, télécharger ou comparer des scénarios Bio-ORACLE, appelle `query_bio_oracle`.
- Pour coupler des lignes zooplancton avec Bio-ORACLE, appelle `couple_zooplankton_bio_oracle`.

---

## Paramètres clés

| Paramètre | Rôle |
|---|---|
| `latitude` | Latitude du point |
| `longitude` | Longitude du point |
| `variable` | Variable Bio-ORACLE demandée |
| `scenario` | Scénario SSP ou `baseline` |
| `depth_layer` | Couche choisie explicitement par l'utilisateur |

---

## Après le chargement

1. Inclure le lien de téléchargement fourni par le tool.
2. Présenter les résultats comme une table de comparaison, pas comme une interprétation écologique.
3. Si l'utilisateur n'a pas donné `scenario` ou `depth_layer`, demander une clarification.

---

## Limites

- Bio-ORACLE est une source environnementale, pas une source de taxonomie.
- La profondeur doit être choisie explicitement par l'utilisateur.
- L'interprétation appartient au chercheur — tu peux seulement fournir les données et les comparaisons.
