# Liste dynamique des projets EcoTaxa

## Objectif

Permettre à l'agent de répondre en temps réel aux questions comme
« Quels projets EcoTaxa sont disponibles pour moi ? », sans dépendre d'une
liste de projets codée en dur dans un skill.

## Architecture

`EcotaxaClient` porte l'appel HTTP authentifié. Une nouvelle méthode
`list_projects()` appelle `GET /api/projects/search` avec les filtres de
recherche vides, puis normalise chaque projet en :

```python
{"project_id": int, "name": str}
```

La méthode utilise l'authentification existante et laisse les erreurs HTTP
remonter selon le même mécanisme que les autres opérations EcoTaxa.

`make_source_tools(thread_id)` expose un nouveau tool LangChain
`list_ecotaxa_projects`. Le tool :

1. crée et authentifie un `EcotaxaClient`;
2. récupère les projets accessibles au compte;
3. trie les projets par `project_id` croissant;
4. retourne une table Markdown contenant uniquement `project_id` et `name`.

Ce tool ne charge aucun DataFrame et ne modifie pas la session courante.

## Données et rendu

La réponse EcoTaxa attendue contient `projid` pour l'identifiant et `title`
pour le nom. Les entrées sont normalisées dans le client afin que le tool ne
dépende pas du schéma brut de l'API.

Si aucun projet n'est accessible, le tool retourne un message explicite plutôt
qu'une table vide.

En cas d'échec d'authentification, de réseau ou d'API, le tool retourne un
message commençant par `Erreur lors de l'accès à EcoTaxa`, comme
`query_ecotaxa`, sans exposer de credential.

## Routage de l'agent et skills

Le system prompt indique d'appeler `list_ecotaxa_projects` lorsque
l'utilisateur demande quels projets EcoTaxa sont disponibles ou accessibles.

Le skill `ecotaxa_query` ne contient plus de liste de projets codée en dur. Il
indique d'utiliser `list_ecotaxa_projects` pour découvrir les identifiants avant
d'appeler `query_ecotaxa`.

## Tests TDD

Les tests sont écrits et observés en échec avant l'implémentation. Ils couvrent :

- l'appel authentifié à `/projects/search` avec les filtres vides;
- la normalisation de `projid` et `title`;
- le tri par identifiant et le rendu Markdown du tool;
- le cas d'une liste vide;
- le retour contrôlé lors d'une erreur EcoTaxa;
- l'enregistrement du nouveau tool dans `make_source_tools`;
- la règle de routage du system prompt;
- l'absence de la liste de projets codée en dur dans `ecotaxa_query`.

## Hors portée

- descriptions ou métadonnées supplémentaires des projets;
- recherche ou filtrage par nom;
- fallback vers un autre endpoint EcoTaxa;
- chargement automatique d'un projet après la liste;
- modification de l'index RAG.
