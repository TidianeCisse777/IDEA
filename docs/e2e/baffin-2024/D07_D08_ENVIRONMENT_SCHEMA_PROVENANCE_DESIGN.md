# D07–D08 — Résolution de schéma et provenance des enrichissements

## Objectif

Garantir qu'un enrichissement environnemental résout ses colonnes avant tout
appel distant et qu'un enrichissement réussi conserve une provenance complète,
identique dans la réponse utilisateur et dans les métadonnées de session.

## Contrat de résolution du schéma

Ajouter un composant pur partagé dans `core/environment_resolver/` :

```python
resolve_environment_schema(
    dataframe: pd.DataFrame,
    *,
    latitude_column: str | None = None,
    longitude_column: str | None = None,
    time_column: str | None = None,
    depth_column: str | None = None,
    require_time: bool = True,
    require_depth: bool = False,
) -> ResolvedEnvironmentSchema
```

`ResolvedEnvironmentSchema` est une dataclass immuable et sérialisable avec :

- `latitude_column` ;
- `longitude_column` ;
- `time_column` ;
- `depth_column` facultative ;
- `resolution` par rôle (`explicit` ou `detected`).

Règles :

1. Un override explicite doit correspondre, sans sensibilité à la casse, à une
   colonne réelle. Sinon la résolution échoue immédiatement en nommant le rôle,
   l'override et les colonnes disponibles.
2. Sans override, chaque rôle utilise une liste d'alias ordonnée et partagée.
3. La priorité temporelle est exactement : `object_date`, `sampledatetime`, puis
   `time`, `date`, `sampling_date`, `deployment_datetime_start`,
   `yyyy-mm-dd hh:mm`, `datetime`.
4. Latitude et longitude sont toujours requises. Temps/profondeur suivent les
   options `require_*`.
5. Une colonne optionnelle non résolue vaut `None`; une colonne requise non
   résolue provoque un refus avant réseau.
6. L'objet résolu est calculé une seule fois et transmis au parsing, au matching,
   à la provenance et au rendu. Aucun composant aval ne redétecte les colonnes.

Le shell partagé `run_point_enrichment` devient le point d'intégration. Son
`EnrichmentOutcome` transporte le schéma résolu complet.

## Contrat de provenance

Ajouter un second composant pur partagé :

```python
build_enrichment_provenance(
    *,
    source: str,
    dataset_id: str,
    dataset_url: str,
    completed_at: datetime,
    parameters: dict,
    resolved_schema: ResolvedEnvironmentSchema,
    variables: list[str],
    coverage: dict,
) -> dict
```

L'objet retourné est JSON-sérialisable et contient obligatoirement :

- `source` ;
- `dataset_id` ;
- `dataset_url` absolue HTTP(S) ;
- `completed_at_utc` au format ISO-8601 avec fuseau UTC ;
- `parameters` réellement utilisés ;
- `resolved_columns` et leur mode de résolution ;
- `variables` demandées ;
- `coverage` avec au minimum `total_rows`, `matched_rows`, `match_rate` et les
  décomptes par statut.

Le constructeur refuse une source, un dataset ou une URL vide, une URL non
HTTP(S), une date sans fuseau, une couverture incohérente ou un taux différent
de `matched_rows / total_rows`. Les paramètres et variables ne sont pas
reconstruits depuis du texte après l'opération.

## Intégration Amundsen

L'enrichissement Amundsen :

1. résout le schéma avant `_fetch_amundsen_bbox` ;
2. réutilise ce schéma pendant tout le matching ;
3. construit la provenance avec le dataset `amundsen12713` et l'URL canonique
   ERDDAP ;
4. stocke exactement cet objet sous `meta["provenance"]` avec le dataframe
   enrichi ;
5. affiche un bloc `Provenance :` sérialisé et une ligne `Source :` cliquable ;
6. refuse de déclarer une réussite si la provenance ne passe pas sa validation.

Le message de méthode affiche aussi les colonnes résolues avant le résumé de
couverture. Aucun nom interne de tool n'est exposé à l'utilisateur.

## Tests et validation E2E

Les tests unitaires couvrent :

- détection `object_date` lorsqu'elle est la seule colonne temporelle ;
- priorité de `object_date` sur `sampledatetime`, puis fallback vers
  `sampledatetime` ;
- override absent refusé avant tout fetch ;
- sérialisation du schéma et des modes de résolution ;
- provenance Amundsen complète et identique entre réponse et métadonnées ;
- refus d'une provenance sans dataset, URL, date UTC ou couverture cohérente.

La validation curl utilise une table de fixture EcoTaxa–EcoPart avec
`object_date` uniquement. Un premier chat vérifie le plan/résultat enrichi et le
bloc de provenance. Un second chat impose l'override absent `sampledatetime` ;
les traces doivent confirmer qu'aucune requête ERDDAP n'a été lancée.

## Hors périmètre

Ce lot n'enregistre pas encore toutes les opérations dans un registre de rapport
et ne modifie pas le PDF. Il crée le contrat réutilisable que D09–D11 pourront
consommer. OGSL et Bio-ORACLE pourront migrer vers le même contrat dans un lot
ultérieur sans bloquer la correction Amundsen.
