# Cache EcoTaxa partagé par release

## Objectif

Distribuer à chaque clone autorisé du dépôt un cache EcoTaxa déjà synchronisé,
sans distribuer les identifiants du compte EcoTaxa. Le cache installé doit
rester le fichier SQLite actuellement lu par l'agent et le MCP :
`data/ecotaxa_cache.sqlite`.

## Décision

Le cache n'est ni commité dans Git ni reconstruit par les utilisateurs. Un
mainteneur le synchronise avec le compte de service, le valide, puis publie une
release GitHub privée contenant :

- `ecotaxa_cache.sqlite.gz` : copie compressée du SQLite validé ;
- `manifest.json` : version de schéma, date de synchronisation, SHA-256,
  taille décompressée et compteurs de projets et samples.

Au démarrage, une instance en mode `consumer` télécharge la release configurée
si son cache local est absent ou non conforme. Elle vérifie le manifeste,
décompresse dans un fichier temporaire, valide le schéma existant, puis remplace
le cache local de façon atomique. Elle ne déclenche jamais de synchronisation
EcoTaxa et ne requiert pas d'identifiants EcoTaxa.

Le mode `publisher` conserve le fonctionnement actuel : il synchronise le
cache avec le compte de service, le valide et peut publier une nouvelle release.
Les identifiants restent dans le `.env` du mainteneur ou dans les secrets CI ;
ils ne sont jamais placés dans le dépôt, le manifeste ou les logs.

## Compatibilité

Les outils et l'agent continuent d'ouvrir le même chemin SQLite. Aucun schéma,
nom de table, endpoint MCP ou contrat d'outil ne change. La compression sert
uniquement au transport ; le fichier installé est bit-for-bit celui publié
après décompression.

## Fiabilité et sécurité

- Une release n'est publiée qu'après un contrôle existant de santé et de
  schéma, avec un sync terminé et des compteurs non nuls.
- Le consommateur refuse un manifeste invalide, un hash différent, une archive
  corrompue, une taille inattendue ou une version de schéma incompatible.
- L'installation se fait dans un fichier temporaire, suivi d'un renommage
  atomique ; un cache local sain n'est jamais écrasé par un téléchargement
  invalide.
- La version de release est configurable et peut être figée pour revenir à une
  version validée.
- Les releases restent privées et accessibles uniquement aux personnes déjà
  autorisées à lire le dépôt. Aucun mot de passe EcoTaxa n'est partagé.

## Flux

1. Le mainteneur exécute une synchronisation avec les secrets du compte de
   service.
2. Le script valide `data/ecotaxa_cache.sqlite`, calcule le SHA-256 et produit
   l'archive et le manifeste.
3. Le mainteneur publie ces deux artefacts dans une release GitHub privée.
4. Un collaborateur démarre le projet en mode `consumer`.
5. Le bootstrap télécharge, vérifie et installe le même SQLite sous
   `data/ecotaxa_cache.sqlite`.
6. L'agent et le MCP lisent ce fichier partagé localement, comme aujourd'hui.

## Tests

- publication refusée si le cache est vide, obsolète ou de schéma incompatible ;
- installation réussie avec archive et manifeste valides ;
- refus du hash, de la taille, du schéma ou de l'archive invalides ;
- remplacement atomique : un cache existant demeure intact sur erreur ;
- mode `consumer` sans `ECOTAXA_USERNAME` ni `ECOTAXA_PASSWORD` ;
- non-régression du mode `publisher` et du chemin SQLite utilisé par l'agent et
  le MCP.
