# Reprise — démonstrations IDEA

Ce document permet de reprendre la préparation des démonstrations sans relire
la conversation de travail.

## État au 4 août 2026

- Branche publiée : `main`.
- Dernier correctif : `520d590` — clarification de la couverture et de la
  provenance de l'enrichissement Amundsen.
- Correctifs de routage externe et de rendu de graphes : `104901c`.
- Flux Filet–UVP certifié et documentation des scénarios : `a17938b`.
- Les quatre parcours et leurs prompts de référence sont dans
  [DEMO_SCENARIOS.md](DEMO_SCENARIOS.md).

## État des quatre scénarios

| Scénario | État | Reprise nécessaire |
|---|---|---|
| Campagne NeoLabs 2018 | Prêt | Non |
| Station 24 et environnement | Prêt | Non |
| Filet et UVP 2024 | Calculs et graphiques validés | Oui : rejouer dans une conversation OpenWebUI neuve, car la conversation existante contient aussi du diagnostic Beaufort/Amundsen. |
| EcoTaxa en baie de Baffin 2024 | Prêt | Non |

Le scénario Filet–UVP doit être rejoué selon ses dix tours dans
`docs/DEMO_SCENARIOS.md`. Les résultats attendus restent descriptifs : 395
prélèvements ont une correspondance UVP certifiée, mais seulement 2 disposent
d'une abondance filet exploitable. Les graphiques de comparaison doivent donc
annoncer explicitement `n = 2` et ne pas être présentés comme une conclusion
de campagne.

## Correctifs à préserver

- Une demande explicite de source externe prime sur le contexte d'un fichier
  local déjà chargé.
- La génération de graphes reste libre : le contrôle conserve l'isolation du
  bac à sable et l'exigence d'une figure Matplotlib, sans imposer un contrat
  graphique exhaustif.
- Le module Python standard `time` est autorisé dans le bac à sable graphique.
- Les champs d'acquisition `acq_*` ne sont pas une preuve d'enrichissement
  Amundsen ; seuls `amundsen_match_status` et la provenance canonique le sont.
- La synthèse de couverture Amundsen sépare le nombre de lignes du nombre de
  casts ou d'identifiants sources.

## Vérification déjà exécutée

```bash
pytest -q tests/test_source_prompt_contract.py tests/test_amundsen_sources.py \
  tests/test_source_scope.py tests/test_data_tools.py tests/test_code_sandbox.py
```

Résultat : `206 passed, 1 warning`.

## Demain

1. Ouvrir une nouvelle conversation OpenWebUI pour « Filet et UVP 2024 ».
2. Rejouer les dix demandes du scénario et conserver uniquement les cartes et
   graphiques indiqués dans la documentation.
3. Vérifier que chaque visuel annonce sa normalisation, son grain de jointure
   (station, heure et tranche de profondeur) et sa couverture réelle.

En cas de blocage reproductible, utiliser `$diagnose`. Pour vérifier une
séquence de routage ou d'appels dans une conversation, utiliser le skill
`langsmith-trace-audit`.
