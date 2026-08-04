# Cache EcoPart persistant pour les démonstrations

## Objectif

Réduire le temps et la fragilité de la démonstration filet–UVP en réutilisant
localement les correspondances EcoTaxa → EcoPart déjà résolues et les exports
EcoPart TSV déjà téléchargés. La récupération distante ne doit intervenir que
si aucune entrée locale compatible n'existe.

Le périmètre initial couvre les 23 projets présents dans le cache EcoTaxa,
dont les campagnes UVP6 2024 utilisées par la démo filet–UVP (14844, 14859,
17498 et 18084). Les correspondances sont déterminées par la route serveur
EcoPart `filt_proj`, qui est une lecture légère et autoritaire ; elle ne crée
pas de tâche d'export.

## Constat de départ

Le runtime dispose déjà de trois caches partiels :

- un cache mémoire puis de session, avec TTL, pour la résolution
  EcoTaxa → EcoPart ;
- un cache de résultats scientifiques pour les jointures finalisées ;
- des TSV téléchargés écrits sous `/tmp/copepod_downloads`.

Le dernier emplacement est éphémère et n'est pas indexé. Après un redémarrage,
l'agent peut donc connaître une correspondance sans pouvoir réemployer son TSV
EcoPart, et doit refaire un export coûteux.

## Décision

Créer un dépôt de cache EcoPart local dédié, par défaut sous
`data/ecopart_cache/`, composé de :

- `manifest.sqlite` : index persistant et interrogeable ;
- `files/<sha256>.tsv` : contenu TSV immuable, dédupliqué par empreinte ;
- un script de préchauffage explicite, jamais exécuté implicitement par un
  échange utilisateur.

Le manifest comporte deux familles d'entrées :

1. les correspondances `ecotaxa_project_id → ecopart_project_id`, avec la
   méthode de résolution, l'horodatage, le statut (résolue, introuvable,
   erreur transitoire) et une durée de validité ;
2. les exports TSV, avec l'empreinte SHA-256, les projets EcoTaxa/EcoPart
   connus, les profils, le schéma, le nombre de lignes, la date d'import et la
   provenance (`remote_export` ou `local_import`).

Un TSV n'est importé que s'il est lisible et contient les colonnes minimales
EcoPart `Profile`, `Depth [m]` et `Sampled volume [L]`. Le contenu et le
schéma sont indexés sans modification scientifique des valeurs. Les fichiers
de tests, les exports partiels et les fichiers sans métadonnée de projet sont
conservés uniquement comme `local_import`; ils sont éligibles à une jointure
locale par profil, mais ne peuvent pas être annoncés comme un export officiel
du projet ni satisfaire seuls une demande de comparaison certifiée.

## Flux d'exécution

```text
Préparation explicite
  TSV existant valide ───────┐
                            ├─> import + empreinte + index persistant
  EcoTaxa en cache ─> filt_proj ─> index des correspondances

Démo filet–UVP
  EcoTaxa sélectionné ─> correspondance persistante ─> TSV compatible ?
                                                    │
                                    oui ───────────┘─> session + jointure locale
                                    non ─────────────> dry-run + confirmation
                                                          └> export distant,
                                                             import immédiat
```

La compatibilité d'un TSV requiert le projet EcoPart lorsque celui-ci est
connu, puis un recouvrement de profils avec la sélection EcoTaxa. La clé de
jointure scientifique existante (`sample_id`, `depth_bin`) et l'audit CTD de
la comparaison filet–UVP restent inchangés.

## Interfaces et intégration

- Un module `core/ecopart_cache.py` centralise le schéma SQLite, l'import,
  la recherche de TSV et les résolutions persistantes. Il ne contacte jamais
  EcoPart.
- `tools/ecopart_sources.py` consulte ce module avant le cache de session et
  avant tout export. Il copie le DataFrame trouvé dans la session actuelle,
  avec des métadonnées `cache_hit`, `cache_path`, `content_sha256` et
  `provenance`.
- Après chaque export EcoPart réussi, le TSV est importé dans le dépôt durable
  avant d'être rendu téléchargeable. `/tmp/copepod_downloads` reste un artefact
  de livraison de courte durée, pas la source du cache.
- Un script `scripts/warmup_ecopart_demo_cache.py` importe les TSV existants
  depuis des chemins explicitement fournis et préchauffe les correspondances
  des projets du cache EcoTaxa. Son mode par défaut est dry-run ; un argument
  explicite active les requêtes légères de résolution. Il produit un bilan sans
  identifiants ni contenu de données.

## Fraîcheur, invalidation et sécurité

- Les correspondances positives ont un TTL configurable (par défaut 30 jours)
  et les erreurs transitoires un TTL court. Une correspondance expirée est
  revalidée par `filt_proj`, sans exporter de TSV.
- Les TSV sont immuables. Une même empreinte n'est stockée qu'une fois ; un
  nouvel export crée une nouvelle entrée plutôt qu'écraser le précédent.
- La sélection prend la copie la plus récente qui passe la compatibilité de
  projet et de profils. Si plusieurs candidats sont équivalents, l'ordre est
  déterministe : provenance officielle, date d'import, puis empreinte.
- Le contenu de `data/ecopart_cache/`, comme les autres données de démonstration,
  reste ignoré par Git. Le code, le schéma et les scripts peuvent être committés
  sans données scientifiques ni secrets.
- Toute absence de TSV compatible conserve la confirmation existante avant un
  export distant ; le cache ne contourne pas CT-AG-06.

## Vérification

- import idempotent : un même fichier ne produit qu'une seule copie ;
- rejet lisible d'un TSV sans colonnes minimales ;
- conservation de la provenance `local_import` vs `remote_export` ;
- résolution persistante disponible après redémarrage, puis expiration et
  revalidation ;
- priorité d'un TSV compatible au lieu d'appeler `start_export` ;
- repli vers le dry-run et la confirmation lorsqu'il n'existe aucun TSV ;
- non-régression des tests EcoPart existants et du scénario filet–UVP.
