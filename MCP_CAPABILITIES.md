# MCP EcoTaxa — Catalogue Des Demandes Utilisateur

Ce document répertorie les types de questions auxquelles le MCP EcoTaxa doit
pouvoir répondre côté exploration. Le but est d'aider l'utilisateur à trouver
les bons projets, samples, taxa, colonnes et métadonnées avant un éventuel
export complet.

Le MCP sert d'abord à explorer. Il ne modifie pas EcoTaxa et ne lance pas
d'export lourd sauf demande explicite.

## 1. Trouver Des Projets EcoTaxa

L'utilisateur peut demander :

- `Quels projets EcoTaxa sont accessibles ?`
- `Liste les projets visibles par mon compte.`
- `Trouve les projets UVP6.`
- `Trouve les projets Loki.`
- `Cherche les projets qui parlent d'Amundsen.`
- `Montre-moi les projets autour de Green Edge.`
- `Preview le projet 14622.`
- `Donne-moi les infos générales du projet 42.`

Le MCP peut répondre avec :

- `project_id` ;
- titre du projet ;
- instrument ;
- statut ;
- droits visibles du compte ;
- nombre d'objets ;
- pourcentage validé/classifié quand disponible ;
- aperçu des premiers objets.

## 2. Explorer Les Projets Par Zone

L'utilisateur peut demander :

- `Quels projets couvrent la Baie de Baffin ?`
- `Quels projets couvrent la Baie de James ?`
- `Quels projets couvrent la Baie d'Ungava ?`
- `Quels projets ont des samples dans cette bbox ?`
- `Quels projets ont des samples au nord de 75N ?`
- `Quels projets couvrent cette zone en 2024 ?`
- `Quels projets UVP6 couvrent cette zone ?`

Le MCP peut répondre avec :

- liste de projets ;
- nombre de samples par projet ;
- nombre d'objets indexés ;
- instruments ;
- dates min/max ;
- emprise spatiale ;
- filtre zone/période/instrument appliqué.

## 3. Explorer Les Samples Par Zone, Date Ou Instrument

L'utilisateur peut demander :

- `Liste les samples en Baie de Baffin en 2024.`
- `Quels samples sont dans la Baie de James ?`
- `Quels samples Loki sont dans le cache ?`
- `Quels samples UVP6 sont disponibles ?`
- `Quels samples du projet 14853 sont en Baie de Baffin ?`
- `Quels samples existent entre 2015 et 2024 ?`
- `Quels samples sont dans cette zone et cette période ?`

Le MCP peut répondre avec :

- `sample_id` ;
- `project_id` ;
- latitude / longitude ;
- `date_min` / `date_max` ;
- instrument ;
- total de samples trouvés ;
- indication si la réponse est tronquée.

## 4. Explorer Un Taxon

L'utilisateur peut demander :

- `Combien de copépodes validés dans le projet 14853 ?`
- `Combien de Calanus dans le projet 42 ?`
- `Où trouve-t-on Calanus glacialis ?`
- `Où trouve-t-on des copépodes en Baie de Baffin ?`
- `Compare les copépodes dans les projets 14853, 14859 et 17498.`
- `Quels projets ont des copépodes validés ?`
- `Quels samples appartiennent à des projets où ce taxon est attesté ?`

Le MCP peut répondre avec :

- taxon résolu ;
- `taxon_id` EcoTaxa ;
- nombre d'objets validés (`V`) ;
- nombre d'objets prédits (`P`) ;
- nombre d'objets douteux (`D`) ;
- nombre d'objets non classés (`U`) quand disponible ;
- total par projet et par taxon ;
- projets non accessibles ou taxa non résolus.

## 5. Résumer Des Projets Avant De Choisir

L'utilisateur peut demander :

- `Résume les projets 14853, 14859 et 17498.`
- `Quel projet contient le plus d'images non annotées ?`
- `Quels projets ont le plus de prédits ?`
- `Quels projets ont le plus de validés ?`
- `Quels projets ont le plus de samples ?`
- `Quels sont les top taxa de ces projets ?`
- `Quels projets sont les plus intéressants à exporter ?`

Le MCP peut répondre avec :

- nombre de samples ;
- dates couvertes ;
- bbox ;
- instruments ;
- counts V/P/D/U ;
- top taxa ;
- projets absents du cache local.

## 6. Résumer Des Samples Avant Export

L'utilisateur peut demander :

- `Résume ces samples.`
- `Parmi ces samples, lesquels ont le plus d'objets ?`
- `Parmi ces samples, lesquels ont le plus de validés ?`
- `Quels samples ont le plus de prédits ?`
- `Quels sont les top taxa de ces samples ?`
- `Est-ce que ces samples valent la peine d'être exportés ?`

Le MCP peut répondre avec :

- `sample_id` ;
- projet ;
- counts V/P/D/U ;
- total d'objets ;
- top taxa par sample.

Limite : le résumé sample donne les top taxa et les counts globaux V/P/D/U du
sample. Pour un comptage précis d'un taxon nommé, il faut utiliser le comptage
par projet/taxon.

## 7. Comprendre Un Sample Ou Un Déploiement

L'utilisateur peut demander :

- `Donne-moi les métadonnées du sample 42000013.`
- `Quelle est la position du sample 42000013 ?`
- `Quelle est la profondeur min/max du sample 42000013 ?`
- `Quelle est la date du sample 42000013 ?`
- `Quel instrument est lié à ce sample ?`
- `Quelle acquisition est liée à ce sample ?`
- `Quels champs UVP sont disponibles pour ce sample ?`
- `Y a-t-il un station id, profile id, cast id ou volume filtré ?`

Le MCP peut répondre avec :

- `sample_id` ;
- `project_id` ;
- `original_id` ;
- latitude / longitude ;
- dates min/max calculées depuis les objets ;
- profondeurs min/max calculées depuis les objets ;
- nombre d'objets scannés ;
- acquisitions associées ;
- instrument ;
- free fields sample ;
- free fields acquisition.

Les champs comme `cast_id`, `station`, `profile`, `volume`, `pixel`,
`bottomdepth` dépendent du projet. Ils sont retournés quand ils existent dans
les `free_fields`.

## 8. Explorer Les Métadonnées UVP

L'utilisateur peut demander :

- `Quels champs UVP sont disponibles dans le projet 42 ?`
- `Est-ce qu'il y a un volume filtré ?`
- `Est-ce qu'il y a pixel size ou exposure ?`
- `Quels champs morphométriques existent ?`
- `Quels champs de profondeur existent ?`
- `Quels champs station/profil/cast existent ?`

Le MCP peut répondre avec les colonnes disponibles aux niveaux :

- sample ;
- acquisition ;
- object.

Il peut aussi indiquer si une colonne existe à plusieurs niveaux et demander ou
utiliser une précision de niveau.

## 9. Inspecter Une Colonne

L'utilisateur peut demander :

- `Quelle est la distribution de depth_min dans le projet 42 ?`
- `Quelle est la profondeur min/max ?`
- `Quelles valeurs existent dans classif_qual ?`
- `Inspecte orig_id.`
- `Quelle est la distribution de area ?`
- `Combien de valeurs distinctes pour stationid ?`

Le MCP peut répondre avec :

- min / max ;
- moyenne ;
- médiane ;
- quartiles ;
- nombre de valeurs ;
- top valeurs textuelles ;
- nombre de valeurs distinctes.

## 10. Comparer Des Projets Avant Export

L'utilisateur peut demander :

- `Compare les projets 14844, 14853, 14859 et 17498 avant export.`
- `Quelles colonnes sont communes ?`
- `Quelles colonnes manquent selon les projets ?`
- `Y a-t-il des conflits de type ?`
- `Y a-t-il des conflits entre sample/acquisition/object ?`
- `Est-ce qu'un export combiné est raisonnable ?`

Le MCP peut répondre avec :

- colonnes communes ;
- colonnes propres à chaque projet ;
- conflits de type ;
- conflits de niveau ;
- sévérité des conflits ;
- points à vérifier avant export.

## 11. Vérifier Les Droits Et L'accessibilité

L'utilisateur peut demander :

- `Est-ce que le projet 14853 est accessible ?`
- `Quels projets puis-je exporter ?`
- `Pourquoi l'export de ce projet échoue ?`
- `Est-ce que ce projet est seulement visible ou exportable ?`

Le MCP peut répondre avec :

- droit visible du compte ;
- succès ou échec d'accès metadata ;
- message d'erreur EcoTaxa ;
- indication quand un projet est dans le cache mais pas exportable.

## 12. Préparer Un Export Sans Le Lancer

L'utilisateur peut demander :

- `Prépare l'export de ces samples.`
- `Regroupe ces samples par projet avant export.`
- `Dis-moi quels projets seront exportés.`
- `Quels samples sont absents du cache ?`

Le MCP peut répondre avec :

- plan d'export ;
- groupement `project_id -> sample_ids` ;
- samples non résolus ;
- confirmation requise avant export réel.

## 13. Exporter Les Données Complètes

L'utilisateur peut demander explicitement :

- `Exporte les objets validés du projet 42.`
- `Charge les objets du sample 42000013.`
- `Exporte ces samples après confirmation.`
- `Télécharge les données complètes de ce projet.`

Dans ce cas, l'assistant peut utiliser les outils d'export EcoTaxa. Ce n'est
plus une simple exploration.

## 14. Ce Que L'utilisateur Ne Peut Pas Demander Au MCP

Le MCP EcoTaxa ne sert pas à :

- modifier un projet ;
- annoter des objets ;
- classifier automatiquement ;
- télécharger les images EcoTaxa ;
- calculer une abondance ou une biomasse finale sans analyse supplémentaire ;
- garantir un champ comme `cast_id` si le projet ne l'a pas défini ;
- contourner les permissions EcoTaxa du compte configuré.
