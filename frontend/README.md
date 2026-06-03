# Frontend IDEA

Static HTML/CSS/JS servi par nginx. Pas de framework — vanilla JS, modules IIFE/namespaces.

---

## Pages HTML

| Fichier | Rôle |
|---|---|
| `index.html` | App principale (chat, conversations, sidebar) |
| `login.html` | Page de connexion |
| `share.html` | Vue lecture-seule d'une conversation partagée |

---

## Orchestration

| Module | Lignes | Rôle |
|---|---|---|
| `assistant.js` | 1968 | **Orchestrateur principal** — state global, `sendRequest`, `processChunk`, init de l'app |
| `ui-shell.js` | 68 | Sidebar toggle, mode switcher, sync mobile |
| `welcome-screen.js` | 228 | Écran d'accueil, profil utilisateur, suggestions de prompts |
| `theme-manager.js` | 42 | Thème clair/sombre (persisté en localStorage) |

---

## Chat & rendu

| Module | Lignes | Rôle |
|---|---|---|
| `message-renderer.js` | 1105 | Rendu messages, math (KaTeX), Prism highlights, indicateurs de travail |
| `code-runner.js` | 442 | Suivi STDOUT/STDERR, panneaux de sortie, state des chunks de code |
| `prism.js` / `prism.css` | — | Coloration syntaxique (markup, css, JS, Python, R, MATLAB, Excel) |

---

## Conversations

| Module | Lignes | Rôle |
|---|---|---|
| `conversation_manager.js` | 476 | Persistance, queue, message store, historique (appelle `/conversations`) |
| `conversation_ui.js` | 1059 | UI : liste, chargement, favoris, suppression |
| `session-badge.js` | 101 | Affiche l'ID de session dans le header (cliquable → copie) |
| `share.js` | 514 | Vue d'une conversation partagée en lecture seule |

---

## Auth & comptes

| Module | Lignes | Rôle |
|---|---|---|
| `auth.js` | 59 | Centralise le token JWT (`getToken`, `setToken`, `clearToken`) — utilisé par tous les autres modules |
| `account-settings.js` | 227 | Modal "Account Settings" + changement de mot de passe |
| `user-management.js` | 420 | CRUD utilisateurs (superuser uniquement) |

---

## Fonctionnalités

| Module | Lignes | Rôle |
|---|---|---|
| `file-upload.js` | 214 | Queue d'upload, rendu badge, suppression, envoi (`/upload`) |
| `microphone.js` | 91 | Préchauffe le micro, gère la dictée vocale (`/transcribe`) |
| `knowledge-base.js` | 349 | Upload PDF, liste papers, query RAG (`/knowledge-base/*`) |
| `prompt-manager.js` | 649 | CRUD system prompts + activation |
| `mcp-manager.js` | 429 | CRUD connexions MCP (URL, token, transport) |
| `mcp-tools.js` | 654 | Liste tools/resources/prompts d'une connexion MCP, invocation |

---

## Utilitaires

| Module | Lignes | Rôle |
|---|---|---|
| `modal-utils.js` | 31 | `ModalUtils.open/close` — utilitaire partagé |
| `config.js` | 78 | Auto-détecte `localhost` vs production, expose `config.getEndpoints()` |
| `config.example.js` | 74 | Template à copier en `config.js` |

---

## Tests

| Fichier | Stack |
|---|---|
| `test_conversation_manager.js` | Node.js — `node frontend/test_conversation_manager.js` |
| `__tests__/file-upload.test.js` | Jest (config dans `package.json`) |

---

## Conventions

- **Namespaces IIFE** pour les modules avec state interne (`mcp-manager`, `mcp-tools`, `user-management`)
- **Globals** pour les modules orchestrateurs (`assistant.js`, `conversation_ui.js`)
- **Tous les modules dépendent de `auth.js`** pour le token JWT
- **Endpoints centralisés dans `config.js`** — jamais hardcoder une URL d'API
- **Pas de bundler** : ordre des `<script>` dans `index.html` impose l'ordre de chargement
- **Aucun import ES modules** — fonctions et objets exposés sur `window`

---

## Flux d'un message utilisateur

```
User tape dans textarea
  → assistant.js: sendRequest()
  → fetch('/chat', { headers: { X-Agent-Type, X-Session-Id, Authorization } })
  → flux SSE → assistant.js: processChunk()
  → message-renderer.js: render assistant text + code blocks
  → code-runner.js: render STDOUT/STDERR au fil
  → conversation_manager.js: persiste tour complet
```

---

## Build / déploiement

Le frontend est servi directement par nginx en statique (voir `nginx.conf` à la racine du repo). Pas d'étape de build : éditer les fichiers, recharger le navigateur.

Pour le mode dev local avec hot-reload des sources backend, voir `docker-compose.override.yml`.
