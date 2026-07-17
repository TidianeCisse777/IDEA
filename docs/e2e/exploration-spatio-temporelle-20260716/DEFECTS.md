# Défauts — Exploration spatio-temporelle NeoLabs

## D1 — Format visuel non respecté

Une demande explicite de graphique du nombre de stations par année a produit un
tableau. Le calcul était exploitable, mais l’intention visuelle n’a pas été
respectée.

## D2 — Station utilisée comme zone

Le fichier ne contient pas de colonne de région ou de zone. L’agent a utilisé
`STATION_NAME`, parfois numérique, puis a intitulé la sortie `zone_or_region`.
La sortie doit dire clairement `station` et ne doit pas présenter un identifiant
de station comme une mer ou une baie.

## D3 — Années hors filtre dans une réponse

Une réponse limitée à 2014–2020 a affiché 2021–2023, alors que le code de
préparation appliquait bien le filtre. La trace indique une mauvaise restitution
du résultat par le modèle après le tool.

## D4 — Découpage aquatique — IMPLÉMENTÉ (2026-07-16)

Le découpage automatique par mers, baies et détroits est désormais disponible
dans le workflow local via le tool `split_dataframe_by_zone` (groupe d’exposition
`file_analysis`, visible dès qu’un fichier est chargé). Il annote le DataFrame
chargé d’une colonne `zone` par point-in-polygon sur le registre IHO/NeoLab
(`core.geo.assign_zones`, famille `iho` par défaut, la plus spécifique gagne les
chevauchements), avec buckets explicites `Hors zone référencée` et
`Sans coordonnées`.

Validé sur agent réel (`neolabs_taxonomy_2014_2020.tsv`, 7093 lignes) : l’agent
route « découpe par mer/baie/détroit » vers `split_dataframe_by_zone` puis
`run_pandas` sur la variable zonée. Résultat outil correct : Baie de Baffin 20
stations, Baie d’Hudson 22, Détroit de Davis 18, Mer de Beaufort 12, Détroit
d’Hudson 10, Baie d’Ungava 3, Mer des Tchouktches 1, `Hors zone référencée` 40.
2711/7093 lignes tombent hors des polygones IHO physiques — envisager
`family="meow"` ou `composite` si une couverture plus large est voulue.

Réserve : sur ce run, la table *finale rédigée par le modèle* était corrompue
(doublon `Détroit d’Hudson`, zones `Lancaster`/`Labrador` inexistantes dans le
résultat outil) alors que le tool et `run_pandas` renvoyaient la bonne table.
C’est le défaut de restitution D3, pas un bug du découpage.

## D5 — Limite provider inférieure au plafond applicatif initial

Le plafond applicatif à 120k tokens dépassait la limite effective provider de
103601 tokens. Le plafond a été abaissé à 100k et la compaction sélective a été
ajoutée. La reprise B7 est passée sous la limite.
