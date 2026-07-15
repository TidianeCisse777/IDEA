# Défauts observés — Cartes de samples (fichier TSV) 2026

Parcours 100 % fichier local. La chaîne carte était cassée pour toute demande
non-abondance, ce qui déclenchait de l'invention de données et une dérive vers
EcoTaxa malgré un périmètre explicite « fichier TSV seulement ».

## P1 — Bloquants

### D-CL1 · Aucun `kind` de carte valide pour les positions/comptages (CORRIGÉ)
- **Symptôme** : les demandes « positions des échantillons », « couleur = nombre
  de taxons », « taille = nombre de samples » n'avaient aucun `graph_contract`
  valide. Le LLM émettait `kind:"map"` ou `kind:"scatter"` →
  `validate_graph_contract` renvoyait `unsupported kind: map` → le prof lisait
  « le type de carte géographique n'est pas supporté ici ». Intermittent : ça
  passait quand le LLM copiait le template `abundance_environment_map`, échouait
  sinon — **sur la même machine** (donc sans rapport avec le réseau/cartopy).
- **Correctif** : nouveau `kind:"station_map"` dans `core/graph_contracts.py` —
  `position=longitude_latitude` obligatoire sur GeoAxes cartopy ; `size`/`color`
  **optionnels** et sur **variable libre** (`sample_count`, `n_taxa`…) ; légendes
  vérifiées seulement si présentes et cohérentes avec leur encodage.
  `abundance_environment_map` reste strict pour les vraies cartes d'abondance.
- **Routage** : `agents/skills/graph_planner.md` + `graph_writer.md` distinguent
  `station_map` vs `abundance_environment_map` et **interdisent** `kind:"map"` /
  `kind:"scatter"`.
- **Tests** : `tests/test_graph_contracts.py` (5 cas `station_map` : positions
  seules, size/color libres, GeoAxes obligatoire, artiste position manquant,
  légende couleur incohérente). Vérifié end-to-end via le vrai `run_graph` sur
  `data/demo/neolabs_taxonomy_2014_2020.tsv` (positions + couleur=`n_taxa`).

### D-CL2 · Invention d'une colonne `abundance_ind_L` (CORRIGÉ)
- **Symptôme** : pour satisfaire le contrat, le LLM renommait un comptage en
  abondance — ex. `point_df["abundance_ind_L"] = point_df["sample_count"]`
  (transcript l.194, l.269), `abundance_ind_L = nombre de taxons` (l.1744).
  Violation directe de « pas de valeur inventée ».
- **Correctif** : `station_map` supprime l'incitation (plus besoin de faux
  `abundance_ind_L`) + règle explicite dans `graph_writer.md` : « Never rename a
  count or a richness to `abundance_ind_L` to satisfy the contract ».

## P1 — Bloquant (comportemental, CORRIGÉ)

### D-CL3 · Périmètre « fichier TSV seulement » non tenu (CORRIGÉ)
- **Symptôme** : malgré trois consignes explicites du prof, l'agent appelle
  `find_ecotaxa_samples_in_region` / `summarize_ecotaxa_samples` (transcript
  l.1135, 1947) et **code en dur des coordonnées EcoTaxa** dans `plot_df`
  (l.1213-1218, 1266-1271, 1992-1998) pour tracer une carte — alors que le
  fichier TSV contient déjà `latitude`/`longitude`/`sample_id`. Cause amont : la
  règle de prompt « pour une zone nommée, par défaut interroge EcoTaxa » tirait
  vers EcoTaxa même avec un fichier chargé.
- **Correctif** : trois règles dures dans `agents/copepod_system_prompt.py` :
  1. **Loaded-file scope precedence** — quand un fichier est chargé et que la
     question porte dessus, router vers `get_zone_info` + `filter_dataframe_by_zone`
     (point-in-polygon sur le df, `tools/geo_tools.py`) puis `run_pandas`/`run_graph` ;
     jamais un outil EcoTaxa ; jamais de coordonnées/ids externes codés en dur.
  2. **Explicit source restriction = hard lock** — après « utilise seulement le
     fichier / n'utilise pas EcoTaxa », les sources externes sont interdites pour
     tous les tours suivants.
  3. Prime explicitement sur la règle « default to EcoTaxa for named zones ».
- **Vérification** : la construction de l'agent + le chargement du prompt passent
  (`tests/test_agent_factory.py`). La validation comportementale complète demande
  un run LLM live (voir README, scénario rejouable).
- **Déploiement** : `python scripts/dev/push_prompt.py` requis (prod tire le
  prompt du Hub LangSmith ; fallback fichier local en dev).

## P3 — Mineurs (CORRIGÉ)

### D-CL4 · Esquive de questions triviales (CORRIGÉ)
- **Symptôme** : à « quel est le nom du fichier ? » (l.1885) l'agent recharge un
  skill au lieu de répondre le nom du fichier chargé en session ; idem « ajoute
  la côte » traité comme ambigu jusqu'à l'abandon du prof.
- **Correctif** : règle « Answer session-metadata questions directly » dans
  `agents/copepod_system_prompt.py` — nom de fichier / colonnes / nombre de lignes
  répondus directement depuis `ACTIVE DATASET STATE` ou un `run_pandas`, sans
  `load_skill` ni question de clarification.

## Portabilité (transverse)

### D-CL5 · Cartes cartopy cassées sur installation neuve (CORRIGÉ)
- **Symptôme** : sur une machine sans cache Natural Earth (clone/Docker neuf,
  ou réseau bloqué), toute carte à côtes échoue (`URLError` sur
  `naturalearth.s3.amazonaws.com`). Le `AdaptiveScaler` des singletons
  `cfeature.LAND/OCEAN/COASTLINE` choisit `10m` au zoom régional → download.
- **Correctif** : fonds `110m` + `50m` vendorés sous `assets/cartopy`, enregistrés
  via `core.cartography.configure_offline_cartopy`, + garde-fou bornant toute
  échelle (`10m`/`auto`) à la plus fine échelle vendorée. Tests :
  `tests/test_cartography.py` (rendu hors-ligne, downloader bloqué).
