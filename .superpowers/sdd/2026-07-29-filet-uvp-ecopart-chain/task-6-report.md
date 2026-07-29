# Task 6 — Dérogation exploratoire après indisponibilité CTD

## Résultat

La chaîne filet ↔ UVP conserve le parcours certifié existant et ajoute une
dérogation strictement opt-in lorsque la validation Amundsen CTD échoue parce
que la source est indisponible.

- `allow_unverified_ctd` vaut `False` par défaut sur l'audit et la jointure.
- Une réponse CTD vide est un `no_match`, pas une indisponibilité.
- Un `no_match` ne publie aucune sélection exploratoire et ne devient jamais
  jointable, même avec l'opt-in.
- Une exception de source avec opt-in publie une sélection exploratoire tout en
  laissant `join_eligible=False`.
- La sélection, l'audit et la jointure finale conservent
  `ctd_verification="unavailable"` et `exploratory=True`.
- La jointure exige à la fois l'argument opt-in et la preuve persistée dans les
  métadonnées de l'audit.
- Le prompt impose d'annoncer le CTD non vérifié, de s'arrêter, puis d'attendre
  une nouvelle confirmation explicite avant l'appel opt-in.

## Fichiers modifiés

- `tools/copepod_sources.py`
  - argument opt-in sur la recherche et la jointure;
  - distinction exécutable entre source indisponible et absence de match;
  - sélection exploratoire persistée et auditée;
  - garde de provenance avant la jointure;
  - statut exploratoire conservé dans le DataFrame final et ses métadonnées.
- `core/net_uvp_comparison.py`
  - jointure exploratoire uniquement pour les lignes explicitement marquées
    `unavailable` + `exploratory`, avec opt-in;
  - parcours `join_eligible=True` inchangé;
  - refus implicite de tous les autres statuts.
- `agents/copepod_system_prompt.py`
  - confirmation explicite obligatoire après l'annonce d'indisponibilité;
  - exception limitée à la source indisponible et interdite au `no match`.
- `tests/test_copepod_sources.py`
- `tests/test_net_uvp_comparison.py`
- `tests/test_agent_factory.py`

Les documents Task 5 n'ont pas été modifiés par cette tâche.

## TDD

RED observé avant implémentation :

```text
5 failed, 1 passed, 223 deselected
```

Les échecs correspondaient aux capacités absentes : argument opt-in dans le
cœur, sélection exploratoire, garde de jointure et consigne du prompt.

GREEN ciblé après implémentation :

```text
6 passed, 223 deselected
```

## Vérifications

Commandes vertes :

```bash
pytest -q tests/test_net_uvp_comparison.py tests/test_net_uvp_pipeline_e2e.py
# 19 passed

pytest -q tests/test_copepod_sources.py -k 'net_uvp or audit_ or certified_selection'
# 16 passed

pytest -q \
  tests/test_agent_factory.py::test_system_prompt_requires_the_strict_net_uvp_match_route \
  tests/test_agent_factory.py::test_system_prompt_requires_confirmation_for_unavailable_ctd_override \
  tests/test_agent_factory.py::test_net_uvp_live_guidance_uses_the_certified_selection_and_final_join
# 3 passed
```

La suite complète `tests/test_copepod_sources.py` donne `91 passed, 5 failed`.
Les cinq échecs sont hors Task 6 et concernent les contrats Task 5 déjà présents
dans le worktree : contenu des skills EcoTaxa/navigation et description du
cache `samples_cache`. Les tests audit/jointure Task 6 et le pipeline filet ↔
UVP sont verts.
