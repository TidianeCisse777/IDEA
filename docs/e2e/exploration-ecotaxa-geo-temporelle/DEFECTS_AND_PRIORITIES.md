# Défauts — Exploration géo-temporelle EcoTaxa

## E2E-GEO-001 — Double affichage du tableau samples

- Scénario / tour : Tour 3 — "Affiche-moi les samples de cette campagne"
- Prompt exact : `Affiche-moi les samples de cette campagne.`
- Attendu : un seul tableau dans la réponse finale
- Observé : le tableau apparaît deux fois — une fois dans le bloc `<details>` du tool, une fois dans la réponse finale de l'agent
- Première décision incorrecte : l'agent recopie le contenu du tool result dans sa réponse au lieu de le synthétiser
- Sévérité : **mineur** — redondant mais pas bloquant

---

## E2E-GEO-002 — Colonnes vides affichées dans le tableau samples

- Scénario / tour : Tour 3 — "Affiche-moi les samples de cette campagne"
- Prompt exact : `Affiche-moi les samples de cette campagne.`
- Attendu : tableau réduit aux colonnes non-vides (`sample_id`, `original_id`, `lat_avg`, `lon_avg`, `instrument`)
- Observé : `date_min`, `date_max`, `depth_min`, `depth_max`, `station_id` affichées bien que toutes à `—` sur les lignes visibles
- Première décision incorrecte : l'agent retourne toutes les colonnes du SELECT sans filtrer les colonnes vides
- Sévérité : **mineur** — lisibilité dégradée

---

## E2E-GEO-003 — Mauvais routage sans précision de source

- Scénario / tour : Tour 2 (première tentative) — "Est-ce qu'on a des données UVP6 de la campagne Amundsen leg 4 de 2024 ?"
- Prompt exact : `Est-ce qu'on a des données UVP6 de la campagne Amundsen leg 4 de 2024 ?`
- Attendu : `list_ecotaxa_campaigns` depuis le cache EcoTaxa
- Observé : `query_copepod_knowledge_base` + `load_skill("amundsen_ctd_query")` — réponse "non vérifiable"
- Première décision incorrecte : "Amundsen" dans le prompt oriente l'agent vers la source CTD Amundsen plutôt que EcoTaxa
- Fix appliqué : reformulation avec "Dans EcoTaxa, ..." suffit à corriger le routage
- Sévérité : **majeur** — l'agent ne trouve pas les données sans précision de source explicite

---

## E2E-GEO-004 — `iho_zone` ignorée pour le groupement par zone

- Scénario / tour : Tour 4 — "Groupe par zone et donne le nombre de samples"
- Prompt exact : `Groupe par zone et donne le nombre de samples.`
- Attendu : `GROUP BY iho_zone` sur le cache — colonne dédiée, exacte, déjà calculée
- Observé : l'agent définit des bbox manuelles hardcodées par zone, résultat incomplet (Hudson Bay et James Bay à 0 alors que des samples y existent)
- Première décision incorrecte : l'agent n'utilise pas `iho_zone` et réinvente un découpage spatial approximatif
- Sévérité : **majeur** — résultats incorrects sur certaines zones, colonne `iho_zone` inutilisée

---

## E2E-GEO-005 — Légende absente sur les cartes et graphes

- Scénario / tour : Tour 7 — "Affiche en légende le numéro de sample pour chaque point"
- Observé : la carte du tour 6 est générée sans légende identifiant les points ; l'agent ne l'ajoute que sur demande explicite
- Attendu : toute carte ou graphe généré doit inclure une légende par défaut — au minimum les labels des points (sample_id, original_id) ou une légende de couleur si plusieurs séries
- Règle : l'agent doit systématiquement ajouter une légende lisible sans que l'utilisateur ait à le demander
- Sévérité : **mineur** — la carte est correcte mais incomplète sans légende

---

## E2E-GEO-006 — Perte de la sélection initiale après agrégation

- Scénario / tour : Tour 7 — "Affiche en légende le numéro de sample pour chaque point"
- Prompt exact : `Affiche en légende le numéro de sample pour chaque point.`
- Attendu : carte avec `sample_id` annoté sur chaque point, données disponibles dans la sélection initiale de 155 samples
- Observé : l'agent échoue — `df_ecotaxa_cache_query` a été écrasé par la requête d'agrégation du tour précédent (seulement `lat_avg / lon_avg / n_samples`), la colonne `sample_id` est perdue
- Première décision incorrecte : le groupement par zone au tour 4b a remplacé la sélection complète au lieu de créer une variable séparée
- Sévérité : **majeur** — une agrégation intermédiaire ne doit pas écraser la sélection canonique ; les intermédiaires doivent être stockés dans des variables distinctes
