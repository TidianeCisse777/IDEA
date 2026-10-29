# Charger les données réelles dans le warehouse v1

Un seul script enchaîne les chargeurs existants dans l'ordre de leurs dépendances, s'arrête au premier échec,
rejoue le déploiement et lance l'assurance qualité : [`scripts/load_warehouse.py`](../scripts/load_warehouse.py).
Aucune logique de chargement n'y est dupliquée.

## Prérequis

| Besoin | Où |
|---|---|
| warehouse v1 déployé (`--verify` → `PRÊT`) | [note de version](WAREHOUSE_RELEASE_V1.md) |
| `WAREHOUSE_POSTGRES_*` du propriétaire | `.env.warehouse` (modèle `example.warehouse.env`) |
| compte EcoTaxa : `ECOTAXA_USERNAME`, `ECOTAXA_PASSWORD` (EcoPart passe par ce compte, ou `ECOPART_TOKEN`) | `.env`, `.env.warehouse` ou secrets de l'environnement; jamais dans Git ni dans une commande |
| dépendances Python | `python -m pip install -r scripts/requirements-warehouse.txt` |
| client `psql`, accès réseau à EcoTaxa, EcoPart et à l'ERDDAP Amundsen | vérifiés par `--preflight` |
| FILET (facultatif) : les trois exports `…(taxonomy samples-data).csv`, `…(copepod abund&biomass-data).csv`, `…(copepod abund&biomass-metadata).csv` | dossier passé à `--filet-dir` |

## Lancer

```bash
python scripts/load_warehouse.py --preflight                      # tout vérifier, ne rien charger
python scripts/load_warehouse.py --project-id 149 --dry-run       # afficher le plan
python scripts/load_warehouse.py --project-id 149                 # premier essai sur un projet
python scripts/load_warehouse.py --all-projects --filet-dir ~/exports/filet
```

Ordre exécuté : échantillons EcoTaxa → objets EcoTaxa (qui datent les échantillons) → profils EcoPart liés →
profils CTD Amundsen → zones des profils CTD → FILET → appariements FILET–UVP → rejeu du déploiement (fiches de
catalogue des nouvelles versions, propriété, contexte MCP, version) → audit qualité en lecture seule.

**Reprise** : un échantillon déjà chargé est ignoré, les objets reprennent à la dernière page enregistrée
(`data/warehouse_staging/ecotaxa_objects_state.json`), EcoPart reprend sa découverte. Après un échec, corriger
puis relancer la même commande.

**Volume** : l'instance précédente comptait 23 projets, environ 6 000 échantillons et 15 millions d'objets. Le
chargement complet prend plusieurs heures; commencer par un projet.

## Après le chargement

```bash
python scripts/warehouse_user.py contract --dataset-key 149 --contract C1       # contrat d'accès par jeu
python scripts/deploy_warehouse_postgres.py --verify                            # PRÊT attendu
python scripts/audit_warehouse.py --qualify                                     # qualification complète (lourde)
```

Sans contrat posé, un compte limité par contrat ne voit pas ces données (refus par défaut). Les versions FILET qui
mélangent plusieurs contrats sont signalées par le rapport : les charger en une version par contrat.

## Vérifié avant le premier chargement réel

Les chargeurs ont été exécutés sans modification sur une v1 complète, avec EcoTaxa et l'ERDDAP simulés et les
fichiers EcoPart et FILET de test (`tests/test_loaders_v1.py`), en superuser et avec un propriétaire non-superuser,
puis contre le PostgreSQL 16.4 de l'image Docker PostGIS. Trois défauts qui auraient bloqué le premier lancement
ont été corrigés :

- **`COPY` direct dans une table protégée** (échantillons EcoTaxa, cinq tables EcoPart, ancien chargeur combiné) :
  PostgreSQL le refuse pour un propriétaire non-superuser. Copie dans une table temporaire puis `INSERT`.
- **`COPY ... FROM STDIN` dans un `psql -c` à plusieurs instructions** (objets EcoTaxa, CTD) : refusé par psql 16
  (`unexpected COPY_IN result`), quel que soit le rôle. Instructions passées en `-c` successifs.
- **Mauvaise base par défaut** : sans `--database-url`, les chargeurs EcoTaxa écrivaient dans la base `postgres`;
  EcoPart ignorait l'hôte et le port configurés. Tous lisent maintenant `WAREHOUSE_POSTGRES_*`.

Également ajoutés : le fichier de dépendances (`shapely` et `pandas` n'étaient déclarés nulle part), la fiche de
catalogue des versions chargées après le premier déploiement, et la commande `contract`.

**Non vérifié** : les vraies API (identifiants nécessaires), le volume réel, et le contenu des exports FILET.
