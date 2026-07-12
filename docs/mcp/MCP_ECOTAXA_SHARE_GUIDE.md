# Guide De Partage — MCP EcoTaxa

Ce document explique comment partager, lancer et tester le MCP EcoTaxa.

Le MCP EcoTaxa expose une interface de navigation read-only sur EcoTaxa pour
des agents compatibles MCP. Il permet d'explorer les projets, samples, zones,
taxons, schémas et métadonnées avant de décider si un export complet est utile.

Il ne modifie pas EcoTaxa, ne crée pas d'annotation, ne classe pas d'images et
ne contourne pas les droits du compte EcoTaxa configuré.

## Démarrage Rapide

À partager avec une personne qui veut seulement tester le MCP :

1. récupérer `docker-compose.mcp.yml` et `.env.mcp.example` ;
2. créer `.env.mcp` depuis l'exemple ;
3. renseigner `MCP_AUTH_TOKEN` et les identifiants EcoTaxa ;
4. lancer le conteneur ;
5. connecter l'agent MCP à `http://localhost:8001/mcp`.

Commandes :

```bash
cp .env.mcp.example .env.mcp
docker compose -f docker-compose.mcp.yml up -d
curl http://localhost:8001/health
```

Connexion MCP à donner à l'agent :

```text
MCP server name: ecotaxa
MCP URL: http://localhost:8001/mcp
Authorization: Bearer <MCP_AUTH_TOKEN>
Transport: streamable HTTP
```

Si le cache est vide, lancer :

```bash
curl -X POST http://localhost:8001/admin/resync \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN"
```

## Ce Que Le MCP Permet De Faire

### Explorer les projets

Exemples de questions :

- `Quels projets EcoTaxa sont accessibles ?`
- `Trouve les projets UVP6.`
- `Résume le projet 14853.`
- `Compare les projets 14853, 2331 et 4042.`

Réponses possibles :

- `project_id`, titre, instrument, statut ;
- droits visibles du compte ;
- nombre de samples et d'objets ;
- dates min/max ;
- bbox du projet ;
- top taxa et counts V/P/D/U quand disponibles.

### Explorer les zones et périodes

Exemples :

- `Quels projets couvrent la Baie de Baffin en 2024 ?`
- `Liste les samples UVP6 dans cette bbox.`
- `Quels samples du projet 14853 sont dans la Baie d'Ungava ?`

Réponses possibles :

- samples avec `sample_id`, `project_id`, latitude, longitude, dates ;
- projets agrégés par zone ;
- nombre de samples et objets par projet ;
- instruments et plages temporelles.

Les zones nommées connues sont résolues côté serveur. L'agent peut donc passer
`zone_name="Baie de Baffin"` au lieu d'envoyer un grand polygone WKT.

### Explorer les taxons

Exemples :

- `Combien de Copepoda validés dans le projet 14853 ?`
- `Cherche les taxon_id candidats pour Calanus.`
- `Où trouve-t-on Calanus glacialis en Baie de Baffin ?`

Réponses possibles :

- résolution du taxon en `taxon_id` EcoTaxa ;
- candidats quand le taxon est ambigu ;
- counts validés (`V`), prédits (`P`), douteux (`D`) et non classés (`U`) ;
- samples appartenant à des projets où le taxon est attesté.

Limite importante : la recherche d'observations est project-filtered. Elle dit
quels samples appartiennent à des projets où le taxon est attesté, mais ne
garantit pas un comptage exact du taxon par sample sans export.

### Inspecter les métadonnées et colonnes

Exemples :

- `Quelles colonnes existent dans le projet 14853 ?`
- `Quelle est la distribution de depth_min ?`
- `Y a-t-il des champs cast_id, station, profile ou volume filtré ?`
- `Compare les schémas des projets 14853 et 2331.`

Réponses possibles :

- schéma par niveau (`sample`, `acquisition`, `object`) ;
- distribution numérique : min, max, moyenne, médiane, quartiles ;
- distribution texte : top valeurs, nombre de valeurs distinctes ;
- colonnes communes, absentes ou en conflit entre projets.

### Diagnostiquer le cache

Exemples :

- `Le cache EcoTaxa est-il prêt ?`
- `Combien de samples sont indexés ?`
- `Est-ce que le sync est encore en cours ?`

Le MCP distingue trois états :

- cache vide sans sync : `CACHE_EMPTY` ;
- cache vide avec sync en cours : `SYNC_IN_PROGRESS` ;
- cache partiel avec sync en cours : les tools répondent avec `partial=True`.

Quand `partial=True`, la réponse est utilisable, mais elle peut changer après
la fin du sync.

## Prérequis

- Docker Desktop avec Docker Compose ;
- identifiants EcoTaxa :
  - `ECOTAXA_USERNAME` ;
  - `ECOTAXA_PASSWORD` ;
- un secret `MCP_AUTH_TOKEN` pour protéger le serveur MCP.

## Lancement Avec Docker Compose

### Option Recommandée Pour Partager Le MCP

Pour partager seulement le MCP, fournir ces deux fichiers :

- `docker-compose.mcp.yml` ;
- `.env.mcp.example`.

L'utilisateur n'a pas besoin de tout le repo si l'image
`ghcr.io/tidianecisse777/mcp-ecotaxa:latest` est publiée à jour.

L'image est prévue pour `linux/amd64` et `linux/arm64`, donc elle fonctionne
sur serveur Linux classique et sur Mac Apple Silicon via Docker Desktop.

Le package GHCR peut rester privé. Dans ce cas, le propriétaire doit donner un
accès `Read` aux testeurs dans GitHub, puis chaque testeur doit se connecter à
`ghcr.io` avec un Personal Access Token GitHub.

### Accès Au Package Privé

À faire par le propriétaire du package :

1. ouvrir la page du package :
   `https://github.com/users/TidianeCisse777/packages/container/package/mcp-ecotaxa` ;
2. aller dans `Package settings` ;
3. ouvrir `Manage access` ;
4. ajouter le compte GitHub du testeur ;
5. donner le rôle `Read`.

À faire par chaque testeur :

1. créer un GitHub Personal Access Token avec le scope `read:packages` ;
2. se connecter à GHCR :

```bash
docker login ghcr.io -u VOTRE_USERNAME_GITHUB
```

Quand Docker demande le mot de passe, coller le Personal Access Token GitHub,
pas le mot de passe GitHub.

Vérifier le pull :

```bash
docker pull ghcr.io/tidianecisse777/mcp-ecotaxa:latest
```

```bash
cp .env.mcp.example .env.mcp
```

Renseigner dans `.env.mcp` :

```dotenv
MCP_AUTH_TOKEN=un-token-long-et-secret
ECOTAXA_USERNAME=...
ECOTAXA_PASSWORD=...
```

Puis lancer :

```bash
docker compose -f docker-compose.mcp.yml up -d
```

Le cache SQLite est stocké dans le volume Docker `mcp_ecotaxa_cache`.
Le registry des zones NeoLab/EcoTaxa est déjà inclus dans l'image Docker.

Vérifier :

```bash
curl http://localhost:8001/health
```

Réponse attendue au premier lancement :

```json
{
  "status": "ok",
  "cache": {
    "samples_indexed": 0,
    "projects_indexed": 0,
    "schemas_indexed": 0,
    "last_sync_status": null,
    "cache_age_hours": null
  }
}
```

Le serveur est alors lancé, mais le cache EcoTaxa est encore vide. Déclencher
la première synchronisation :

```bash
curl -X POST http://localhost:8001/admin/resync \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN"
```

Pendant le premier sync, les requêtes cache peuvent répondre
`SYNC_IN_PROGRESS`. Après le sync, `cache_status` doit indiquer des samples et
projets indexés.

### Option Développement Depuis Le Repo Complet

Depuis la racine du dépôt :

```bash
cp .env.example .env
```

Renseigner dans `.env` :

```dotenv
MCP_AUTH_TOKEN=un-token-long-et-secret
ECOTAXA_USERNAME=...
ECOTAXA_PASSWORD=...
```

Lancer le service :

```bash
docker compose up -d mcp-ecotaxa
```

Vérifier la santé :

```bash
curl http://localhost:8001/health
```

## Initialiser Le Cache

Au premier lancement, le cache local peut être vide. Déclencher une synchro :

```bash
curl -X POST http://localhost:8001/admin/resync \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN"
```

Puis suivre l'état :

```bash
curl http://localhost:8001/health | jq '.cache'
```

Le serveur déclenche aussi un sync nocturne automatiquement si
`ECOTAXA_NIGHTLY_SYNC=true`.

Variables utiles :

| Variable | Rôle | Défaut |
|---|---|---|
| `MCP_AUTH_TOKEN` | Bearer token pour `/mcp` et `/admin/*` | requis |
| `ECOTAXA_USERNAME` | Login EcoTaxa | requis |
| `ECOTAXA_PASSWORD` | Mot de passe EcoTaxa | requis |
| `ECOTAXA_CACHE_DB` | chemin SQLite du cache | `data/ecotaxa_cache.sqlite` |
| `ECOTAXA_NIGHTLY_SYNC` | active le sync nocturne | `true` |
| `ECOTAXA_SYNC_HOUR` | heure UTC du sync nocturne | `3` |

## URL MCP

Transport MCP HTTP :

```text
http://localhost:8001/mcp
```

Toutes les requêtes MCP doivent inclure :

```text
Authorization: Bearer <MCP_AUTH_TOKEN>
```

## Comment Le Partager À Un Agent

Il y a deux choses à partager à un agent :

1. l'URL du serveur MCP ;
2. une consigne courte qui explique quand utiliser EcoTaxa et comment traiter
   les réponses.

### Informations De Connexion

Donner à l'agent :

```text
MCP server name: ecotaxa
MCP URL: http://localhost:8001/mcp
Authorization: Bearer <MCP_AUTH_TOKEN>
Transport: streamable HTTP
```

Ne pas mettre le token dans un prompt public ou dans un document partagé hors
de l'équipe. Le token doit être configuré comme secret côté client MCP quand le
client le permet.

### Consigne Courte À Mettre Dans Le Prompt De L'agent

```text
Use the EcoTaxa MCP when the user asks about EcoTaxa projects, samples,
taxa, zones, instruments, metadata, columns, cache status, or project/sample
availability. Prefer EcoTaxa MCP tools over generic file/table/graph tools for
these questions.

Before counting a taxon, resolve ambiguous names with search_taxa. If a tool
returns AMBIGUOUS_TAXON, show the candidate taxon_id values and ask the user to
choose.

If cache_status or a tool reports SYNC_IN_PROGRESS, tell the user the cache is
still syncing and retry later. If a result contains partial=True, answer with
the available data but state that the result is partial.

When answering, give the requested conclusion first, then include the relevant
project_id, sample_id, taxon_id, filters, and source identifiers used.
```

### Exemple Pour Un Agent MCP Externe

À configurer dans le client MCP :

```json
{
  "mcpServers": {
    "ecotaxa": {
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_AUTH_TOKEN}"
      }
    }
  }
}
```

La syntaxe exacte dépend du client. Certains clients demandent le token dans
une interface de secrets plutôt que dans le fichier JSON.

### Exemple De Message À Envoyer À Un Agent

```text
Tu as accès au MCP EcoTaxa nommé "ecotaxa".
Utilise-le pour toute question sur les projets, samples, taxa, zones,
instruments, métadonnées et colonnes EcoTaxa.

Commence par cache_status si tu suspectes un cache vide ou un sync en cours.
Pour une zone nommée, utilise zone_name plutôt qu'un polygon_wkt géant.
Pour un taxon ambigu, utilise search_taxa avant de compter.
Si une réponse contient partial=True, indique clairement que le sync est en
cours et que le résultat peut changer.
```

### Pour L'agent IDEA / Open WebUI

L'agent IDEA n'a pas besoin de l'URL HTTP MCP pour fonctionner : il utilise les
mêmes fonctions Python via les wrappers LangChain dans `tools/copepod_sources.py`.

Pour cet agent, les consignes à maintenir sont plutôt dans :

- `agents/copepod_system_prompt.py` ;
- `agents/skills/ecotaxa_navigation.md` ;
- les docstrings des tools dans `tools/copepod_sources.py`.

Le guide présent sert donc surtout à partager le MCP avec des agents externes
ou avec une personne qui doit le configurer.

## Vérifier Que La Distribution Fonctionne

Test minimal après lancement :

1. Vérifier HTTP :

```bash
curl http://localhost:8001/health
```

2. Vérifier que le serveur expose les tools MCP :

```bash
curl -s -X POST http://localhost:8001/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"initialize",
    "params":{
      "protocolVersion":"2025-11-25",
      "capabilities":{},
      "clientInfo":{"name":"smoke","version":"0"}
    }
  }'
```

Réponse attendue :

- serveur `EcoTaxa Browser` ;
- capability `tools`.

3. Appeler un tool sans dépendre du cache :

```bash
curl -s -X POST http://localhost:8001/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"search_taxa",
      "arguments":{"query":"Calanus"}
    }
  }'
```

Réponse attendue : une liste de candidats avec `taxon_id`.

4. Tester une zone nommée avant sync :

```bash
curl -s -X POST http://localhost:8001/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":3,
    "method":"tools/call",
    "params":{
      "name":"projects_in_region",
      "arguments":{"zone_name":"Baie de Baffin"}
    }
  }'
```

Sur un cache neuf, la bonne réponse est `CACHE_EMPTY`, pas une erreur de
fichier manquant. Cela confirme que le registry des zones est bien inclus dans
l'image Docker.

## Exemple D'appel Direct

Initialisation MCP :

```bash
curl -s -X POST http://localhost:8001/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"initialize",
    "params":{
      "protocolVersion":"2025-11-25",
      "capabilities":{},
      "clientInfo":{"name":"curl","version":"0"}
    }
  }'
```

Appel d'un outil :

```bash
curl -s -X POST http://localhost:8001/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"projects_in_region",
      "arguments":{
        "zone_name":"Baie de Baffin",
        "date_range":{"from":"2024-01-01","to":"2024-12-31"}
      }
    }
  }'
```

## Outils Disponibles

### Disponibilité Zone / Temps

| Tool | Usage |
|---|---|
| `samples_in_region` | samples par bbox, zone nommée, période, instrument, projet |
| `projects_in_region` | projets qui ont des samples dans une zone/période |

### Taxons

| Tool | Usage |
|---|---|
| `search_taxa` | trouver les `taxon_id` candidats |
| `taxonomy_node` | explorer l'arbre taxonomique |
| `taxa_stats` | counts V/P/D/U par projet et taxon |
| `find_observations` | samples dont le projet atteste un taxon |

### Résumés

| Tool | Usage |
|---|---|
| `summarize_projects` | résumé de plusieurs projets |
| `summarize_project` | résumé d'un projet |
| `summarize_samples` | résumé de plusieurs samples |
| `summarize_sample` | résumé d'un sample |
| `summarize_sample_deployment` | position, dates, profondeurs, acquisition, free fields |

### Catalogue

| Tool | Usage |
|---|---|
| `search_projects` | chercher des projets par titre/instrument |
| `get_project` | métadonnées projet |
| `list_project_samples` | samples d'un projet |
| `get_sample` | métadonnées sample |
| `list_project_acquisitions` | acquisitions d'un projet |
| `get_acquisition` | métadonnées acquisition |
| `list_sample_objects` | objets d'un sample |
| `get_object` | objet avec contexte sample/acquisition/projet |

### Schémas

| Tool | Usage |
|---|---|
| `get_project_schema` | colonnes disponibles par niveau |
| `get_column_distribution` | distribution d'une colonne |
| `compare_project_schemas` | compatibilité de plusieurs projets |

### Cache

| Tool | Usage |
|---|---|
| `cache_status` | état du cache, dernier sync, progression, `running` |

## Codes D'erreur Importants

| Code | Signification | Action recommandée |
|---|---|---|
| `CACHE_EMPTY` | aucun sample indexé et pas de sync en cours | lancer `/admin/resync` |
| `SYNC_IN_PROGRESS` | sync en cours mais cache encore vide | attendre et rappeler `cache_status` |
| `AMBIGUOUS_TAXON` | plusieurs taxons correspondent | utiliser `search_taxa`, puis choisir un `taxon_id` |
| `TAXON_NOT_FOUND` | aucun taxon trouvé | corriger le nom |
| `AMBIGUOUS_COLUMN` | colonne présente à plusieurs niveaux | rappeler avec `level=sample/acquisition/object` |
| `COLUMN_NOT_FOUND` | colonne absente du projet | appeler `get_project_schema` |
| `UNKNOWN_ZONE` | zone nommée inconnue | utiliser une zone connue ou une bbox |
| `INVALID_BBOX` | bbox invalide | corriger `{south, west, north, east}` |
| `INVALID_DATE_RANGE` | période invalide | corriger `{from, to}` |
| `INVALID_STATUS` | statut taxon invalide | utiliser `V`, `P`, `D` ou `all` |

## Bonnes Pratiques Pour Les Agents

- Charger ou lire les consignes EcoTaxa avant d'appeler les tools si l'agent a
  un mécanisme de skills.
- Si la demande mentionne EcoTaxa, un `project_id`, un `sample_id`, une zone ou
  un taxon, privilégier les tools EcoTaxa avant les outils génériques.
- En cas d'ambiguïté de taxon, appeler `search_taxa` avant de compter.
- Ne pas répondre avec une table brute seulement : extraire la conclusion
  demandée, puis garder le tableau comme preuve.
- Préserver les liens et identifiants sources (`project_id`, `sample_id`,
  `taxon_id`) dans les réponses quand les tools les fournissent.
- Si `partial=True`, dire clairement que la réponse vient d'un cache en cours
  de synchronisation.

## Limites

Le MCP EcoTaxa ne permet pas de :

- modifier EcoTaxa ;
- annoter ou classifier des objets ;
- télécharger les images ;
- contourner les permissions du compte EcoTaxa ;
- garantir qu'un champ existe dans tous les projets ;
- fournir un comptage exact d'un taxon par sample sans export objet ;
- remplacer une analyse scientifique finale.

## Tests Rapides

```bash
docker compose exec -T mcp-ecotaxa curl -sf http://localhost:8001/health
```

Depuis le dépôt :

```bash
pytest -q tests/test_mcp_cache_admin.py tests/test_ecotaxa_browser_region.py
pytest -q tests/test_ecotaxa_browser_observations.py tests/test_mcp_capabilities_parity.py
```

## Références Internes

- `core/mcp/README.md` : documentation technique du serveur.
- `MCP_CAPABILITIES.md` : catalogue détaillé des demandes utilisateur.
- `core/ecotaxa_browser/` : logique métier pure Python.
- `tools/copepod_sources.py` : wrappers LangChain utilisés par l'agent IDEA.
