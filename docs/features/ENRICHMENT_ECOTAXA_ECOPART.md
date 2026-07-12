# Enrichissement EcoTaxa ↔ EcoPart

Comment l'agent enrichit des observations taxonomiques EcoTaxa avec les profils
particules/CTD EcoPart, et calcule ensuite les métriques d'abondance.

Code : `tools/ecopart_sources.py` (`_perform_enrichment`, `join_ecotaxa_ecopart`,
`enrich_ecotaxa_with_ecopart_remote`) · `core/ecopart_client.py`.
Routage : `agents/copepod_system_prompt.py` (section *EcoTaxa ↔ EcoPart enrichment*).
Skills : `agents/skills/ecotaxa_query.md`, `ecopart_query.md`, `environmental_join.md`,
`uvp_ecotaxa.md`, `uvp_ecopart.md`.
Tests : `tests/test_ecopart_sources.py` (unitaires) ·
`tests/test_enrichment_workflows_integration.py` (intégration, vraie data démo).

---

## Les 3 workflows

Tous convergent vers la **même jointure** `(sample_id, depth_bin)`. La seule
différence est *d'où vient le DataFrame EcoPart*. L'agent choisit le tool selon ce
qui est déjà en session — jamais en re-dérivant la donnée.

| # | Situation de départ | Tool | Remote ? |
|---|---|---|---|
| 1 | EcoTaxa **et** EcoPart déjà en session (2 fichiers, ou `query_ecotaxa` + `query_ecopart`) | `join_ecotaxa_ecopart` | non (jointure locale) |
| 2 | Fichier EcoTaxa chargé, EcoPart **pas** en session | `enrich_ecotaxa_with_ecopart_remote` | oui (télécharge EcoPart) |
| 3 | EcoTaxa exporté via `query_ecotaxa`, EcoPart pas en session | `enrich_ecotaxa_with_ecopart_remote` | oui (full remote) |

**Workflow 3 (full remote)** : `query_ecotaxa` pose la session sous la clé
`{thread}:ecotaxa` avec `meta.project_id`. `enrich_ecotaxa_with_ecopart_remote`
relit ce `project_id` et retrouve l'EcoPart correspondant sans qu'aucun ID EcoPart
ne soit fourni.

### Résolution automatique du projet EcoPart (workflows 2 & 3)

`enrich_ecotaxa_with_ecopart_remote` s'appelle **sans argument** par défaut. Ordre
de résolution :

1. `ecotaxa_project_id` / `ecopart_project_id` explicites si fournis ;
2. `meta.project_id` laissé par `query_ecotaxa` (workflow 3) ;
3. bbox depuis `object_lat` / `object_lon` → `searchsample` par zone → match par profil ;
4. labels de profil (`sample_profileid`, `sample_stationid`, `sample_station_name`,
   `sample_cruise`) → `search_samples` → match par `profile_id` (cas sans coordonnées).

Si tout échoue, le tool renvoie une erreur claire et l'agent demande alors un ID.
C'est une **opération lourde** (téléchargement) → confirmation requise (CT-AG-06).

---

## Clé de jointure et binning

- **sample_id** : côté EcoTaxa, la clé est choisie par **recouvrement réel** avec la
  colonne `Profile` d'EcoPart, parmi plusieurs candidats — `sample_id` brut,
  `sample_id`/`obj_orig_id` strippés du suffixe objet `_NNN`
  (`ips_007_899` → `ips_007`), ou un label de profil. Le candidat avec le plus de
  correspondances gagne, donc une seule ligne non-matchée ne fausse pas le choix.
  Les deux côtés sont convertis en chaîne → pas de mismatch int/str silencieux.
- **depth_bin** : bin de 5 m, `(object_depth_min // 5) * 5 + 2.5`. **Vérifié sur la
  vraie grille EcoPart** : les `Depth [m]` réels sont aux centres `2.5, 7.5, 12.5, …`
  espacés de 5 m, donc la formule retombe exactement dessus.

La sortie conserve une colonne **`depth_bin`** (centre du bin) — utilisée par les
templates de densité m5/m6. Chaque objet EcoTaxa reçoit les colonnes EcoPart de son
bin, préfixées `ecopart_` (`ecopart_Sampled volume [L]`, LPM, CTD), **préservées,
pas moyennées**.

---

## Calcul des métriques

- **m1–m3 (particules EcoPart)** : calculées **directement** sur `df_ecopart`
  (grille `Profile` × `Depth [m]`), pas besoin de jointure. Voir `uvp_ecopart.md`.
- **m5–m6 (abondance/densité copépodes EcoTaxa)** : sur la table jointe, via
  `depth_bin` + `ecopart_Sampled volume [L]`. Densité **par bin** :
  `groupby(sample_id, depth_bin)` → `nb objets du bin / volume du bin`, puis
  m5 = `(moyenne surface 0-50 m + moyenne fond max-50 m) / 2`. Voir `uvp_ecotaxa.md`.

> ⚠️ Ne **jamais** utiliser `sum(objets) / sum(volume)` global : c'est une autre
> métrique (densité volumique globale), pas m5, et elle fausse les classements.

---

## Conditions réelles & avertissements

L'enrichissement ne produit des valeurs que si les deux jeux sont de la **même
campagne** et que les objets tombent dans des bins **réellement couverts** par le
cast EcoPart. Deux cas vus sur les données démo :

- **Campagnes différentes** (EcoTaxa ArcticNet2013 + EcoPart Hawke Channel 2024) →
  aucun profil partagé → le tool renvoie « Aucune correspondance » et **ne stocke
  aucune table** de jointure.
- **Couverture partielle** : un cast qui démarre à 12.5 m laisse les objets plus
  hauts (bins 2.5/7.5) avec des colonnes EcoPart `NaN` — **jamais de volume
  inventé**.

Le message de jointure rapporte toujours le taux de match (« X matchées sur un bin
EcoPart »). **Règle de l'agent** : rapporter ce taux et avertir si 0 ou faible, et
ne pas présenter un enrichissement rempli de `NaN` (ni des métriques qui en
découlent) comme un succès. C'est un indicateur de qualité factuel, requis même
sous la règle de concision.

---

## Validation

```bash
# Suite d'intégration dédiée (3 workflows + binning + métriques + avertissements)
LANGCHAIN_TRACING_V2=false python -m pytest tests/test_enrichment_workflows_integration.py -v

# Tests unitaires de la jointure et du remote
LANGCHAIN_TRACING_V2=false python -m pytest tests/test_ecopart_sources.py -q
```
