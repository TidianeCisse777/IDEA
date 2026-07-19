# Campagnes de test — EcoTaxa, export et analyse au grain objet

Objectif : vérifier, avec le vrai modèle, le parcours complet **exploration
read-only → plan d'export → confirmation explicite → export → analyse/graphe
objet**. Chaque campagne est volontairement courte et doit rester dans un scope
réduit : aucun export de projet complet.

## Règles communes de validation

- Le premier tour n'exporte rien : il explore le cache et expose des samples.
- La demande d'export déclenche un plan/dry-run, jamais le download immédiat.
- Le « oui » arrive dans un tour distinct et confirme seulement le plan affiché.
- Après un export multi-projets, la table active doit être la campagne consolidée
  et contenir `export_project_id` ; le graphe doit exploiter tous les objets de
  ce scope, pas seulement le dernier projet exporté.
- Chaque réponse distingue résultat, source, méthode et limite. Aucun outil ni
  nom de DataFrame n'est montré à l'utilisateur final.

## C1 — Baie de Baffin, découverte puis histogramme de profondeur

But : valider le chemin le plus courant avec une campagne d'abord inconnue,
puis une analyse de tous les objets validés de la sélection retenue.

1. « Je ne connais pas les données EcoTaxa disponibles en Baie de Baffin entre
   le 1er août et le 1er octobre 2024. Explore sans exporter et donne une
   synthèse par projet, puis au plus cinq samples représentatifs avec instrument,
   position et date. »
2. Après lecture des résultats : « Garde exactement les samples `14859000001`
   et `17498000048` affichés. Prépare l'export de tous leurs objets, sans rien
   télécharger. »
3. « Oui, lance exactement ce plan. »
4. « À partir de l'export, produis un histogramme du nombre d'objets par classes
   de profondeur de 10 m. Indique le nombre d'objets et de samples couverts,
   sans interprétation biologique. »

Réussite : exploration sans download, plan avec scope/filtres, confirmation
distincte, puis graphique basé sur les colonnes profondeur objet réellement
présentes. Si plusieurs projets sont inclus, le graphique couvre chacun d'eux
et peut être ventilé par `export_project_id`.

## C2 — Campagne SQL multi-projets, taxon puis distribution de taille

But : vérifier que la sélection automatique `latest` relie une exploration
libre à un export multi-projets, et que la persistance consolidée est utilisée.

1. « Dans EcoTaxa, explore sans exporter les samples UVP5 et LOKI du Détroit de
   Davis en 2015 : projets, dates, positions et nombre d'objets. »
2. « Parmi les samples affichés, limite la campagne à au plus un sample par
   projet et prépare l'export des objets validés ; donne le plan projet par
   projet, sans lancer l'export. »
3. « Oui, confirme ce plan précis. »
4. « Fais un histogramme de la taille image des objets exportés. Sépare les
   projets si plusieurs sont présents et rapporte les colonnes de taille
   effectivement utilisées, sans convertir pixels en millimètres. »

Réussite : le modèle ne retape pas les IDs de l'aperçu, réutilise la sélection
mémorisée, confirme avant le download et analyse la campagne entière. Il choisit
une colonne réellement disponible (`object_feret`, `object_major`, `fre_feret`
ou équivalent) et ne mélange pas les unités/calibrations.

## C3 — Une sélection réduite, carte d'objets et provenance spatiale

But : vérifier la forme objet des données exportées et le traitement honnête des
coordonnées manquantes.

1. « Explore les samples EcoTaxa UVP6 d'une zone et période où des résultats
   existent. Ne télécharge rien : montre le tableau de couverture et choisis au
   plus deux samples, en expliquant le critère de sélection. »
2. « Prépare l'export de tous les objets validés de ces samples, sans le lancer.
   Dis si la carte pourra utiliser des coordonnées objet ou seulement sample. »
3. « Oui, lance le plan affiché. »
4. « Produis une carte des objets exportés si des coordonnées objet sont
   présentes ; sinon, produis une carte des positions de sample et explique cette
   limite. Affiche aussi le nombre d'objets et de samples par projet. »

Réussite : aucune position n'est inventée. Le modèle inspecte les colonnes
réelles (`object_lat`/`object_lon`, `obj_latitude`/`obj_longitude`, ou colonnes
sample) avant le graphe et énonce clairement le niveau spatial employé.

## Ordre et coût recommandé

Exécuter C1 d'abord. C2 ne doit être lancé que si son dry-run reste à un sample
par projet. C3 peut réutiliser une petite sélection de C1 pour éviter un second
download. Arrêter une campagne si le dry-run révèle un volume inattendu ; réduire
la période, le nombre de samples ou appliquer le filtre `status="V"` avant de
demander une nouvelle confirmation.
