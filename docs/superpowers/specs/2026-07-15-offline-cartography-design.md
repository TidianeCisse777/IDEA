# Cartographie autonome hors ligne — Design

## Contexte

IDEA produit toutes ses cartes géographiques avec Cartopy. Les gabarits actuels
utilisent quatre couches Natural Earth à la résolution `110m` : terre, océan,
traits de côte et frontières nationales. Cartopy télécharge ces fichiers à la
première utilisation dans son cache utilisateur. Un nouveau clone installé avec
`pip install -r requirements.txt`, ou un nouveau conteneur Docker, dépend donc
encore du réseau au moment de créer sa première carte.

Les polygones métier des zones marines suivent un autre chemin. Le fichier
compilé `data/geo/zones_registry.geojson` est versionné et suffit à l'exécution.
Le shapefile IHO source d'environ 142 Mo sert uniquement à reconstruire ce
registre et doit rester exclu du dépôt et des images Docker.

## Objectif

Après un nouveau téléchargement du projet, les deux parcours suivants doivent
créer immédiatement une carte sans téléchargement cartographique au runtime :

1. installation locale avec `pip install -r requirements.txt` ;
2. construction ou téléchargement de l'image Docker IDEA.

La même installation doit également conserver les PNG générés dans le stockage
de données persistant de l'application plutôt que dans `/tmp`.

## Décision

Le dépôt versionne les quatre couches Natural Earth réellement consommées, à
**deux échelles** (`110m` bassin entier et `50m` régional) :

- `physical/ne_{110m,50m}_land.*` ;
- `physical/ne_{110m,50m}_ocean.*` ;
- `physical/ne_{110m,50m}_coastline.*` ;
- `cultural/ne_{110m,50m}_admin_0_boundary_lines_land.*`.

Le `50m` est indispensable : les singletons `cfeature.LAND/OCEAN/COASTLINE`
portent un `AdaptiveScaler` qui, au rendu d'un extent régional zoomé, choisit
une échelle plus fine que le `110m` par défaut (jusqu'à `10m`). Un garde-fou
runtime (`core.cartography._install_scale_guard`) borne toute échelle demandée
— `10m`, `auto` ou explicite — à la plus fine échelle vendorée (`50m`), afin
que Cartopy ne lise que des fichiers embarqués et ne télécharge jamais rien.

Ils résident sous `assets/cartopy/shapefiles/natural_earth/` selon l'arborescence
attendue nativement par Cartopy. Les fichiers nécessaires au fonctionnement de
chaque shapefile (`.shp`, `.shx`, `.dbf`, `.prj` et, lorsqu'il existe, `.cpg`)
sont inclus. Aucun autre niveau de résolution et aucun fond non utilisé n'est
embarqué.

Natural Earth place ces données dans le domaine public. Un fichier de provenance
dans `assets/cartopy/` documente la source, la version, les couches incluses et la
date d'acquisition.

## Architecture

### Configuration Cartopy

Un module ciblé, `core/cartography.py`, expose :

- le chemin canonique des fonds embarqués ;
- la liste exacte des quatre couches obligatoires ;
- une fonction de configuration qui affecte `cartopy.config["pre_existing_data_dir"]`
  au répertoire embarqué ;
- une validation qui retourne une erreur explicite et actionnable si un fichier
  obligatoire manque.

`tools/data_tools.py` appelle cette configuration avant toute exécution de code
graphique. Cartopy trouve donc les shapefiles locaux avant de consulter son
téléchargeur. Aucune modification des gabarits de cartes n'est nécessaire.

La validation n'interdit pas Cartopy en général : elle porte seulement sur les
quatre couches garanties par IDEA. Une future couche ou une résolution différente
devra être ajoutée explicitement au manifeste avant d'être utilisée hors ligne.

### Stockage des PNG

Le chemin des graphiques est centralisé afin que le producteur (`run_graph`) et
le serveur HTTP (`/graphs/{filename}`) utilisent toujours le même répertoire.
La variable `GRAPHS_DIR` permet une surcharge explicite. Sa valeur par défaut est
`data/graphs` dans le projet.

En Docker, `GRAPHS_DIR=/app/data/graphs`. Le volume nommé `copepod_data`, déjà
monté sur `/app/data`, rend alors les images persistantes entre les redémarrages
et remplacements de conteneur. Aucun nouveau volume n'est requis.

### Distribution

Les fonds résident sous `assets/cartopy/**`, qui est versionné et inclus dans le
contexte Docker hors du volume `/app/data`. Les données de session et les PNG
restent ignorés. `.dockerignore` continue d'exclure le shapefile IHO source et le
reste de `data/`.

Le Dockerfile exécute un contrôle de disponibilité des quatre couches pendant la
construction. Une image incomplète échoue donc au build plutôt que lors de la
première requête utilisateur.

## Flux d'exécution

1. Le projet ou l'image contient les quatre couches Natural Earth minimales.
2. `run_graph` initialise le runtime cartographique commun.
3. Le runtime vérifie les fichiers et configure `pre_existing_data_dir`.
4. Le code Cartopy existant ouvre les fichiers locaux sans appel réseau.
5. Matplotlib écrit le PNG dans le répertoire de graphiques commun.
6. FastAPI sert ce même fichier via `/graphs/{filename}`.

Les données scientifiques restent indépendantes : une carte utilise le fichier
chargé ou le sous-ensemble obtenu par les outils de source. Ce changement ne
provoque aucun téléchargement complet EcoTaxa, EcoPart, Amundsen ou Bio-ORACLE.

## Gestion des erreurs

- Couche embarquée absente ou incomplète : erreur IDEA mentionnant la couche et
  le chemin manquant, sans tentative silencieuse de téléchargement.
- Répertoire de graphiques non inscriptible : erreur de création de répertoire
  au démarrage du composant concerné.
- Fond futur non manifesté : le test hors ligne échoue jusqu'à ce que la couche
  soit ajoutée au manifeste et à la provenance.

## Tests et critères d'acceptation

- Un test unitaire vérifie la résolution du chemin embarqué et la détection d'un
  fichier manquant.
- Un test d'intégration rend une vraie carte avec les quatre couches tandis que
  le téléchargeur Cartopy est remplacé par une fonction qui échoue à tout appel.
- Les tests de `run_graph` confirment l'écriture dans le répertoire centralisé.
- Les tests du serveur confirment que `/graphs/` lit le même répertoire.
- Un test de configuration vérifie que les contextes Git et Docker incluent les
  fonds embarqués et que le compose définit le chemin persistant.
- La suite pytest ciblée passe localement.
- Une construction Docker de validation passe lorsque le moteur Docker est
  disponible ; sinon, la vérification statique et le rendu hors ligne constituent
  le minimum requis et la limite est signalée.

## Documentation

`PARTAGE.md` explique qu'un clone ou une image contient les fonds minimaux et
que la première carte ne dépend plus du réseau. `ARCHITECTURE.md` décrit le
runtime cartographique et le répertoire persistant des PNG. La documentation de
provenance précise que les sources IHO lourdes restent exclues et distinctes des
fonds Natural Earth.

## Hors périmètre

- embarquer toutes les résolutions ou toutes les couches Natural Earth ;
- embarquer le shapefile IHO source d'environ 142 Mo ;
- précharger ou télécharger toutes les données scientifiques ;
- modifier la projection, le style ou les contrats graphiques existants ;
- garantir hors ligne des couches Cartopy futures non déclarées dans le manifeste.
