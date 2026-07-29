# Task 5 — Documentation et E2E du parcours filet↔UVP↔EcoPart

## Résultat

Le parcours utilisateur est maintenant documenté et couvert comme une chaîne
guidée :

1. sous-sélection filet persistée sous le nom exact retourné ;
2. audit position/temps/fichier CTD ;
3. sélection exportable limitée aux lignes `join_eligible=True` dont
   `ctd_filename_match_status="matched"` ;
4. dry-run puis confirmation de l'export EcoTaxa multi-projets ;
5. dry-run puis confirmation EcoPart, partitionnée par projet ;
6. jointure locale certifiée par projet + profil UVP ;
7. analyses uniquement depuis `df_net_uvp_ecopart`.

Aucune implémentation `core/` ou `tools/` des Tasks 1–4 n'a été modifiée.

## Changements

- `tests/test_net_uvp_pipeline_e2e.py`
  - remplace le bridge démo manuel `spatial_only` par un audit certifié avec
    projets et profils explicites ;
  - vérifie qu'une ligne `spatial_only` n'atteint ni la table objet finale ni
    les métriques ;
  - vérifie qu'un audit sans match CTD produit une table finale vide ;
  - calcule ensuite la table sample-profondeur canonique et les métriques de
    comparaison sur les seules lignes certifiées.
- `tests/test_agent_factory.py`
  - ajoute le contrat du scénario live attendu : nom persistant exact, guidage
    après mauvais nom, sélection certifiée exacte, deux confirmations, jointure
    finale et arrêt avant export sans CTD certifié.
- `agents/skills/net_uvp_abundance_comparison.md`
  - version 2.1.0 ;
  - remplace le bridge pandas manuel par le parcours guidé et
    `join_net_uvp_enriched` ;
  - réserve les calculs à la table canonique finale ;
  - rend distinctes les confirmations EcoTaxa et EcoPart.
- `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`
  - documente le parcours audit → export → EcoPart → jointure → analyses ;
  - ajoute le scénario live attendu, y compris la récupération après nom de
    table erroné et l'arrêt sans export.
- `TOOLS.md`
  - inventaire régénéré à 68 tools obligatoires / 71 avec SQL ;
  - documente `find_uvp_matches_for_net_table` et le tool local
    `join_net_uvp_enriched`.

## TDD

### RED

Commande :

```bash
pytest tests/test_net_uvp_pipeline_e2e.py tests/test_agent_factory.py -k 'certified or net_uvp' -v
```

Résultat initial :

- 1 succès ;
- 3 échecs :
  - l'ancien E2E consommait cinq lignes `spatial_only` ;
  - les fichiers démo et le contrat `copepod_count` étaient périmés ;
  - le guidage live certifié n'était pas présent.

### GREEN ciblé

Même commande après mise à jour :

```text
4 passed, 113 deselected
```

Contrôles complémentaires :

```text
pytest tests/test_tool_catalog.py tests/test_tool_exposure.py \
  -k 'join_net_uvp or exact_mandatory_tool_count'
3 passed, 67 deselected

pytest tests/test_active_skill_reuse_contract.py tests/test_skill_tool.py
16 passed, 1 warning

python scripts/dev/generate_tools_doc.py --check
Inventaire des tools synchronisé

git diff --check
succès
```

## Matrice prescrite et baseline

Commande :

```bash
pytest -q tests/test_net_uvp_comparison.py tests/test_ctd_filename_match.py \
  tests/test_copepod_sources.py tests/test_ecopart_sources.py \
  tests/test_enrichment_workflows_integration.py \
  tests/test_net_uvp_pipeline_e2e.py tests/test_tool_catalog.py \
  tests/test_tool_exposure.py tests/test_agent_factory.py
```

Résultat :

```text
326 passed, 25 failed, 5 warnings
```

Les cinq échecs de baseline consignés dans les rapports Tasks 1 et 3 sont
toujours présents :

1. `test_ecotaxa_skill_uses_live_project_listing`
2. `test_ecotaxa_skill_routes_preview_without_export`
3. `test_ecotaxa_navigation_tools_require_skill_load_in_description`
4. `test_object_read_tools_require_skill_load_in_description`
5. `test_ecotaxa_cache_contract_exposes_sample_metadata_envelopes_and_coverage`

La sixième dérive déjà consignée dans Task 3 reste présente :

- `test_all_data_source_tools_have_explicit_visibility_decisions` attend 55
  métadonnées source, alors que le catalogue courant en contient 56.

Les 19 autres échecs viennent de contrats préexistants de
`tests/test_agent_factory.py` contre l'état courant du kernel, des skills et du
middleware (routage EcoTaxa, textes legacy de skills, graph writer et budget du
prompt). Ils ne touchent pas la chaîne Task 5. Le contrôle du budget confirme
que le prompt à `HEAD` était déjà à 11 473 tokens pour une attente historique de
3 500 ; aucun changement du prompt permanent n'est inclus dans cette tâche.

## Scénario live attendu

La trace de recette doit observer :

1. `run_pandas` renvoie `Persistence: persisted=true` et un nom dérivé ;
2. un premier audit avec un faux nom est bloqué et liste ce nom disponible ;
3. l'agent réessaie immédiatement avec le nom exact ;
4. si aucune ligne n'est à la fois `join_eligible=True` et CTD `matched`, la
   réponse annonce la non-comparabilité et aucun appel
   `export_ecotaxa_samples` ou EcoPart ne suit ;
5. sinon les deux plans confirmés précèdent la jointure locale et les analyses.

## Correctif de revue 1/5

Deux défauts confirmés par la revue ont été corrigés sans modifier le
comportement exploratoire de Task 6.

### Clé projet conservée

- `join_certified_net_uvp_enriched` conserve déjà `export_project_id` après la
  jointure `(projet, profil)`.
- `build_canonical_sample_depth` ajoute maintenant automatiquement
  `export_project_id` à sa clé quand la colonne est présente. Le grain devient
  alors `(export_project_id, sample_id, depth_bin)`.
- Le skill groupe les densités et fusionne le bridge sur
  `(export_project_id, uvp_profile_str)`, jamais sur le profil seul.
- L'E2E force une collision : projets 10 et 20, même `shared-profile` et même
  `shared-cast_1`. Deux cibles canoniques et deux stations distinctes survivent.

### Porte CTD indépendante

- Le helper certifié exige toujours `join_eligible=True`.
- Si une preuve CTD explicite existe, elle doit aussi être certifiée :
  `ctd_verification="verified"`, ou son équivalent filename historique.
- `no_match` et `unavailable` sont refusés sans opt-in, même si une fixture
  contradictoire force `join_eligible=True`.
- Le wrapper persistant couvre séparément `join_eligible=False`, `no_match` et
  `unavailable`, et vérifie qu'aucune table finale n'est créée.
- Les gardes de provenance du wrapper restent des tests distincts
  (source d'audit, table filet liée, fingerprint et origine EcoPart).
- L'exception Task 6 reste inchangée : seul
  `allow_unverified_ctd=True` avec `ctd_verification="unavailable"` et
  `exploratory=True` peut emprunter le chemin exploratoire confirmé.

### TDD du correctif

RED :

```text
E2E collision/protection core : 3 échecs attendus, 1 succès
Wrapper persistant CTD : 2 échecs attendus ; garde join_eligible déjà verte
Contrat du skill projet+profil : 1 échec attendu
```

GREEN minimal :

```text
E2E collision/protection core : 4 passed
Wrapper persistant CTD : 3 passed
Contrat du skill projet+profil : 1 passed
```

La suite historique `tests/test_copepod_sample_depth.py` conserve deux échecs
préexistants : elle attend encore la colonne legacy `copepod_count`, tandis que
le contrat runtime courant renvoie `target_count`. Les huit autres tests de ce
module passent, y compris les validations de clés et de volumes.

### Vérification du correctif

```text
tests/test_net_uvp_comparison.py + tests/test_net_uvp_pipeline_e2e.py
23 passed

tests/test_copepod_sources.py -k 'net_uvp or audit_ or join_net_uvp_enriched'
16 passed, 83 deselected, 4 warnings

tests/test_agent_factory.py -k 'certified or net_uvp'
2 passed

tests/test_copepod_sample_depth.py hors les deux attentes copepod_count legacy
11 passed, 2 deselected

ruff check (core et E2E touchés)
All checks passed
```

La matrice prescrite complète après correctif donne :

```text
339 passed, 25 failed, 5 warnings
```

Les 25 échecs sont les mêmes contrats hors périmètre déjà classifiés dans le
rapport initial ; aucun échec Task 5 ou Task 6 n'est ajouté.
