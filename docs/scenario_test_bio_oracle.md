# Scénario de test — Bio-ORACLE par station

Vérifie que l'agent route correctement entre `couple_zooplankton_bio_oracle`
(une valeur par station) et `query_bio_oracle_zones` (une valeur par zone agrégée),
après les garde-fous ajoutés à `tools/bio_oracle_sources.py` et la règle anti-broadcast
dans `agents/copepod_system_prompt.py`.

## Pré-requis

- Agent démarré (`./start.sh` ou `docker compose up`).
- System prompt LangSmith à jour (révision ≥ `a2b6528f`).
- Fichier démo présent : `data/demo/zooplankton_demo_stations.tsv` (20 stations, lat 60.5°–81.4°N).

## Critère de réussite global

Pour chaque table renvoyée par l'agent, **les valeurs Bio-ORACLE doivent varier entre
stations** dès que les coordonnées sont distinctes. Si on voit la même valeur sur
plusieurs lignes avec des lat/lon différentes → régression.

---

## Étape 1 — charger le fichier

> Charge `data/demo/zooplankton_demo_stations.tsv`.

Attendu : `load_file`, 100 lignes × 11 colonnes, mention des colonnes `station`,
`latitude`, `longitude`, `date`, `taxon`, `abundance_ind_per_m3`.

---

## Étape 2 — couplage baseline (cas nominal)

> Pour chaque station du fichier, donne la température Bio-ORACLE en scénario
> baseline, couche surface.

Attendu :
- L'agent demande confirmation (>10 lignes, opération lourde CT-AG-06).
- Sur `oui` : appel **`couple_zooplankton_bio_oracle`** avec une entrée par ligne.
- Table renvoyée : **valeurs de température distinctes** selon les latitudes
  (les stations à 81°N doivent être plus froides que celles à 60°N).

Anti-pattern à rejeter :
- Appel à `query_bio_oracle_zones` avec une seule zone (« Arctique ») suivi
  d'un broadcast `df['temperature'] = <scalar>` dans `run_pandas`.

---

## Étape 3 — comparaison baseline vs SSP5-8.5

> Compare maintenant la température baseline avec SSP5-8.5 (surface) pour les
> mêmes stations.

Attendu :
- Deuxième appel `couple_zooplankton_bio_oracle` (scenario SSP5-8.5).
- Table à 3 colonnes nouvelles : `temperature_baseline`, `temperature_ssp5_8_5`,
  `delta`. Le delta doit varier d'une station à l'autre.

---

## Étape 4 — bascule explicite vers les zones (cas nominal `query_bio_oracle_zones`)

> Compare maintenant la température SSP5-8.5 entre la mer du Labrador, la baie
> d'Hudson et la mer de Beaufort.

Attendu :
- Appel **`query_bio_oracle_zones`** avec `zones=["Mer du Labrador", "Baie d'Hudson", "Mer de Beaufort"]`.
- ⚠ Le tool ajoutera un warning en tête de réponse (puisqu'une table multi-stations
  est en session), pointant vers `couple_zooplankton_bio_oracle`. **L'agent doit
  reconnaître que la question est bien par-zone et garder la réponse zones**, en
  expliquant qu'il s'agit de valeurs agrégées par zone, pas par station.

---

## Étape 5 — piège anti-broadcast

> Donne-moi un tableau avec une seule colonne température en SSP5-8.5 pour les
> 20 stations, en utilisant la valeur Bio-ORACLE de la zone Arctique.

Attendu (comportement correct) :
- L'agent refuse l'instruction explicitement, citant le risque de fabriquer
  des valeurs par station qui n'ont pas été mesurées.
- Il propose à la place `couple_zooplankton_bio_oracle` ligne-par-ligne (le seul
  cas où il a le droit de proposer une suite, parce que la question initiale
  est techniquement incorrecte).

Anti-pattern à rejeter :
- L'agent exécute la demande et broadcast la même valeur sur 20 lignes.

---

## Étape 6 — point unique

> Donne la température Bio-ORACLE à 71.24°N, -157.17°E en SSP1-2.6, surface.

Attendu : `preview_bio_oracle_point` (un seul point, pas besoin de confirmation),
réponse avec UNE valeur, sans fabrication de table.

---

## Reporting des résultats

À chaque étape, noter :
1. Quel tool a été appelé (visible dans LangSmith → trace → child runs).
2. Les valeurs renvoyées dans la table (différentes par station ou non).
3. Le warning ⚠ a-t-il été émis quand attendu (étape 4).

Si une étape échoue, capturer le `run_id` LangSmith et l'extrait de la table
problématique.
