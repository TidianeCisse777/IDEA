# Ingestion EcoPart et jointure EcoTaxa

## Périmètre et provenance

Le chargeur `scripts/populate_ecopart.py` interroge les projets EcoTaxa déjà
présents dans PostgreSQL. Il résout les liens avec `/searchsample?filt_proj=…`,
identifie **tous** les projets EcoPart représentés et vérifie les métadonnées
`/getsamplepopover/{id}`. Un ID explicitement indiqué dans le titre EcoTaxa est
également accepté après vérification de l'accès au projet EcoPart. Un nom de
campagne ressemblant ou une proximité géographique ne suffit pas.

Références examinées dans Git : `origin/main` au commit `475af5d`,
`core/ecopart_client.py`, `tools/ecopart_sources.py`,
`core/ecotaxa_ecopart_join.py`, ainsi que le correctif `7a7751f` de
normalisation des profondeurs et l'historique du client. L'archive locale
`../IDEA-archive-20260911` est absente. Aucun ancien runtime n'est réintroduit.

L'export serveur **RED / TSV** contient les particules en 15 classes et les
mesures environnementales par pas de 5 m, les résultats zooplancton `ZOO`
à leur propre grain, et les métadonnées. Ce contrat a été vérifié dans le
formulaire EcoPart réel. Il ne s'agit pas d'un téléchargement des images ni
strictement du format EcoPart appelé « RAW ».

## Exécution et reprise

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r scripts/requirements-ecopart.txt
.venv/bin/python scripts/populate_ecopart.py --discover-only
.venv/bin/python scripts/populate_ecopart.py
.venv/bin/python scripts/validate_ecopart_warehouse.py
```

Le chargeur lit les identifiants EcoTaxa/EcoPart de `.env`, et la connexion
warehouse de `.env`/`.env.warehouse`. Les valeurs ne sont ni affichées ni
écrites dans les manifestes. Par défaut, le warehouse local écoute sur 55432,
base `neolab_warehouse`, rôle `neolab`. `WAREHOUSE_DATABASE_URL` remplace cette
connexion si défini.

Les ZIP originaux, SHA-256, tâches serveur, preuves de résolution, inventaires
de samples et comptes rendus sont conservés dans `data/warehouse_ecopart/`,
ignoré par Git. Chaque projet est téléchargé une fois puis vérifié par son
empreinte. Une tâche connue peut être reprise. Les nouvelles tâches sont
identifiées à partir de la réponse, ou par différence dans la liste des tâches
et vérification stricte du filtre projet ; aucune sélection aveugle de la
« dernière tâche » du compte.

La migration additive `docs/warehouse_ecopart_migration.sql` s'applique avant
le chargement. Chaque projet est chargé dans une transaction PostgreSQL ; un
échec annule ses lignes. `warehouse.ecopart_project_import` marque la version
complète. Relancer réutilise cette version sans dupliquer bins ni liens.
Un changement du périmètre EcoTaxa d'une version déjà chargée est refusé pour
exiger une réconciliation explicite. Aucune source existante n'est supprimée.

Les erreurs sont consignées par projet ; les autres projets sont poursuivis.
Une découverte ou ingestion incomplète fait retourner un code non nul.

## Grains, unités et relations

- `warehouse.uvp_profile` : profil textuel dans un projet EcoPart et une version.
- `warehouse.uvp_bin` : profil × bin 5 m, volume en litres.
- `warehouse.ecopart_bin_source` : profondeur source et **toutes** les colonnes
  originales du bin, y compris biovolumes, classe ouverte >16,4 mm et CTD.
- `warehouse.uvp_particle` : concentrations fournies des classes de taille
  bornées, sans recalcul, en `# l-1`. Bornes exprimées en µm ; les biovolumes
  restent distincts dans les colonnes source. Aucun nombre entier de particules
  n'est déduit d'une concentration arrondie.
- `warehouse.ecopart_auxiliary_row` : lignes originales des résumés de
  métadonnées et exports `ZOO`, avec leur fichier et numéro de ligne.
- `warehouse.uvp_ecotaxa` : liaison exacte par `sample_orig_id` ou `profile_id`,
  limitée aux projets reliés par preuve serveur/titre. Toute ambiguïté est
  refusée. Aucune suppression heuristique de suffixe d'identifiant.
- `warehouse.uvp_object_bin` : objet × bin, selon
  `floor(object_depth_min / 5) * 5`. Bornes semi-ouvertes `[min, max[` ; la même
  règle normalise les profondeurs EcoPart. Un objet sans bin reste dans EcoTaxa
  et dans la vue d'objets avec un bin NULL.
- `warehouse.uvp_ctd` : uniquement les liens transitifs issus des correspondances
  EcoTaxa–CTD déjà acceptées, avec provenance. Les mesures CTD contenues dans
  EcoPart restent identifiables comme source EcoPart.

Les membres ZIP portant le même nom ne sont dédupliqués que si leurs octets
sont identiques ; leurs noms sont consignés dans le rapport. Un doublon de
bin entre fichiers distincts ou de contenu différent provoque un échec.
Les exports `ZOO` ne sont jamais concaténés aux bins particulaires `PAR`.

## Abondances et dénominateurs

Les abondances dérivées sont `n_objets / volume_L × 1000`. Elles sont séparées
par projet EcoTaxa dans `annotation_policy` :
`all_loaded_objects:ecotaxa_project=ID`. Deux projets EcoTaxa qui réutilisent
le même projet EcoPart ne sont donc pas additionnés implicitement.

Les statuts d'annotation n'étaient pas chargés dans les objets EcoTaxa présents
au début de cette ingestion. Ces valeurs concernent **tous les objets chargés**,
pas exclusivement les objets validés. Les exports `ZOO` fournis par EcoPart
utilisent les vignettes validées et ne constituent pas le même estimateur.

`taxon_key` distingue `ecotaxa:id:…`, `ecotaxa:name:…` et le marqueur local
`warehouse:unclassified`. Le marqueur et les noms ne sont pas présentés comme
des identifiants taxonomiques officiels. Aucun mapping FILET n'est créé.

La table `warehouse.uvp_taxon_abundance` stocke les comptes positifs. La vue
`explore.uvp_taxon_abundance` représente également les zéros pour chaque taxon
observé dans le profil et le projet EcoTaxa, sur **tous les bins de ce profil**.
Le volume de bins sans objet participe ainsi au dénominateur. Pour un taxon
absent de tout un profil, partir de `explore.ecopart_bins` et faire un LEFT JOIN
avec les comptes ; la vue ne crée pas un univers taxonomique global implicite.

```sql
SELECT profile_id, taxon_key, annotation_policy,
       SUM(n_objects_taxon) AS n,
       SUM(sampled_volume_l) AS volume_l,
       SUM(n_objects_taxon) / SUM(sampled_volume_l) * 1000 AS ind_m3
FROM explore.uvp_taxon_abundance
WHERE annotation_policy = 'all_loaded_objects:ecotaxa_project=5149'
GROUP BY profile_id, taxon_key, annotation_policy;
```

Les vues `explore.ecopart_bins`, `explore.ecopart_source_metadata` et
`explore.ecopart_supplied_zooplankton` exposent les contenus EcoPart natifs.
Les vues UVP historiques sont alimentées ; `uvp_projects` prend les relations
multiples en compte et `uvp_objects` limite les liens au profil/version courant
de la ligne pour éviter une multiplication entre versions.

## Validation

```bash
uv pip install --python .venv/bin/python pytest pandas
ECOPART_INTEGRATION_TESTS=1 .venv/bin/python -m pytest -q \
  tests/test_populate_ecopart.py tests/test_warehouse_schema.py
```

Les tests PostgreSQL créent puis suppriment une base temporaire dédiée. Ils
vérifient les limites de bins, les zéros, les non-appariés, la reprise et le
rollback. Le validateur réel compare chaque bin chargé au ZIP original,
audit les clés/profondeurs/cardinalités, la conservation des comptes et les
liens CTD, puis écrit `data/warehouse_ecopart/validation.json`.

Les résultats chiffrés de l'exécution réelle sont consignés dans
`WAREHOUSE_ECOTAXA_QA.md` et `ROADMAP.md`. Une validation SQL n'est pas une
validation conversationnelle IDEA ni une interprétation scientifique.
