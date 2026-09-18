# Frictions UVP encore ouvertes

Ce registre complète les cas d’usage SQL. Il décrit les situations qui peuvent
empêcher une réponse fiable ou changer le sens scientifique d’une requête.
Chaque friction doit être résolue par l’ingestion, une vue SQL ou une règle
scientifique explicitement validée. L’agent ne doit pas l’inventer pendant une
conversation.

## Statuts

- **géré par le schéma** : la donnée et le statut existent déjà ;
- **à confirmer sur les fichiers** : le modèle est prêt, mais il faut vérifier
  le format réel ;
- **décision scientifique requise** : plusieurs interprétations sont possibles ;
- **à implémenter** : une table, vue ou validation manque encore.

## Registre

| Friction | Statut | Gestion prévue | Preuve attendue |
|---|---|---|---|
| Sample sans station, date, position ou profondeur | à confirmer sur les fichiers | conserver `NULL`, exposer un indicateur de complétude dans une vue de diagnostic | taux de remplissage par export |
| Zone maritime absente | géré par le schéma, ingestion à confirmer | calculer la zone à partir des coordonnées et stocker `marine_zone_source` et `marine_zone_version` | échantillons classés `ARCTIQUE_CANADIEN` ou `HORS_ARCTIQUE_CANADIEN` |
| Correspondance CTD par nom de fichier insuffisante | géré par le schéma, ingestion à confirmer | conserver candidat, station, écart temporel, distance et statut avant d’accepter le lien | audit des liens acceptés/ambigus/rejetés |
| Variables CTD et unités hétérogènes | à confirmer sur les fichiers | renseigner `ctd_variable`, garder code source, nom canonique et unité | catalogue Amundsen vérifié sur un fichier réel |
| Profil CTD absent malgré un nom de fichier | à confirmer sur les fichiers | distinguer `no_candidate`, `candidate`, `accepted`, `rejected` | couverture CTD par zone et station |
| Objet EcoTaxa sans bin EcoPart | géré par le schéma | conserver `mapping_status = unmatched` et ne pas le compter silencieusement | audit des objets non rattachés |
| Objet à la limite d’un bin | géré par la règle historique | appliquer `floor(object_depth_min / 5) * 5 + 2.5` et conserver `depth_delta_m` | comparaison avec le script historique |
| Abondance sur plusieurs bins | géré par la règle de calcul | sommer objets et volumes par profil avant toute moyenne entre profils | test pondéré objets/volumes |
| Taxons FILET et UVP nommés différemment | décision scientifique requise | utiliser `taxon_mapping`, seuls les mappings `accepted` alimentent la comparaison | mapping relu par un biologiste |
| Stades taxonomiques non équivalents | décision scientifique requise | conserver le stade source et la relation de mapping, ne pas fusionner automatiquement | règle documentée par taxon |
| Mesures CTD jointes au mauvais grain | géré par les vues | garder CTD au grain profil × profondeur × variable ; résumer avant de joindre au sample | contrôle du nombre de lignes après jointure |
| Profil/sample sans objet mais avec volume EcoPart | à confirmer sur les fichiers | conserver le bin et son volume ; ne pas transformer l’absence en zéro taxonomique | contrôle des bins sans objets |
| Plusieurs versions d’exports mélangées | à implémenter | imposer `dataset_version_id` sur les requêtes et les liens | requête reproductible sur une version unique |
| Projet présent dans plusieurs zones | géré par les agrégations | produire des vues projet × zone et ne pas écraser la zone au niveau projet | comptage par zone vérifié |

## Règle de comportement de l’agent

Lorsque l’une de ces situations apparaît, l’agent doit retourner la donnée et
son statut (`missing`, `ambiguous`, `unmatched`, `rejected` ou équivalent). Il
peut proposer une requête de diagnostic, mais ne doit pas choisir une valeur,
un taxon, un profil CTD ou une unité sans règle enregistrée.

## Critères de clôture

Une friction est clôturée seulement lorsque :

1. un export réel la couvre ;
2. la règle est écrite dans le schéma ou une vue ;
3. un test de contrat ou un test de données la vérifie ;
4. un exemple SQL produit le résultat attendu au bon grain.
