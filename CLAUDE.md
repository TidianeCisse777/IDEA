# CLAUDE.md — IDEA · NeoLab, Université Laval
# Branche : langchain-openwebui

Assistant scientifique copépodes : LangChain (agent + tools + RAG) + Open WebUI (frontend).
Utilisateurs : professeurs et étudiants. Réponses en français par défaut.

---

## Architecture cible

```
Open WebUI  ──────────────────────────────────────────────────────────
  │  appel OpenAI-compatible  (http://localhost:8000/openai)
  ▼
serve.py  (LangServe → endpoint /openai, /invoke, /stream)
  │
agent.py  (LangGraph ReAct agent)
  │  system prompt : agents/copepod_prompt.py
  │
  ├── tools/rag_tool.py          → query_copepod_rag (@tool LangChain)
  ├── tools/data_tools.py        → inspect_file, describe_column (@tool)
  └── core/copepod_rag/query.py  → ChromaDB (déjà construit)
```

**Étape 1** — Agent CLI (tester sans Open WebUI) : `python agent.py`
**Étape 2** — Brancher Open WebUI : `python serve.py` + pointer Open WebUI sur `http://localhost:8000/openai`

---

## Fichiers présents (à conserver)

| Fichier | Rôle |
|---|---|
| `agents/copepod_prompt.py` | `COPEPOD_SYSTEM_PROMPT` — system prompt de l'agent |
| `agents/copepod_profile.py` | Métadonnées du profil (nom, description) |
| `core/copepod_rag/query.py` | `query_copepod_rag(question, top_k)` — ChromaDB |
| `core/copepod_rag/build_index.py` | Construit l'index Chroma depuis les docs |
| `core/copepod_rag/chunk_docs.py` | Découpe les docs en chunks |
| `core/copepod_rag/chroma_db/` | Index vectoriel persistant |
| `core/copepod_rag/docs/*.md` | 7 docs RAG (colonnes, domaine, méthodes…) |
| `core/tool_registry/tools/copepod_*.py` | Tools copépodes — à convertir en `@tool` LangChain |

---

## Fichiers à créer

```
requirements.txt          ← langchain, langgraph, langchain-openai, langserve, chromadb, …
agent.py                  ← LangGraph ReAct agent (test CLI)
serve.py                  ← LangServe → endpoint OpenAI-compatible pour Open WebUI
tools/
  __init__.py
  rag_tool.py             ← query_copepod_rag comme @tool LangChain
  data_tools.py           ← inspect_file, describe_column comme @tool
```

---

## Comment les tools fonctionnent (LangChain)

Les tools sont des **vraies fonctions Python décorées `@tool`**, pas des strings injectées dans un sandbox.

```python
from langchain_core.tools import tool

@tool
def query_copepod_knowledge_base(question: str) -> str:
    """Interroge la base de connaissances copépodes (colonnes, méthodes, taxonomie)."""
    from core.copepod_rag.query import query_copepod_rag
    chunks = query_copepod_rag(question, top_k=3)
    return "\n\n".join(c["content"] for c in chunks)
```

L'agent LangGraph reçoit la liste de tools au moment de sa construction :
```python
agent = create_react_agent(llm, tools=[query_copepod_knowledge_base, inspect_file, ...])
```

---

## Connexion Open WebUI

Open WebUI supporte nativement les endpoints **OpenAI-compatibles**.

LangServe expose automatiquement `/openai` (format `ChatCompletion`) quand on ajoute une `ChatPromptTemplate` + le runnable.

Dans Open WebUI : Settings → Connections → ajouter `http://localhost:8000/openai` comme endpoint OpenAI custom.

---

## Démarrage

```bash
# Installer les dépendances
pip install -r requirements.txt

# Reconstruire l'index RAG si nécessaire
python core/copepod_rag/build_index.py

# Tester l'agent en CLI
python agent.py

# Lancer le serveur pour Open WebUI
python serve.py
```

Variables `.env` minimum :
- `OPENAI_API_KEY` (ou `ANTHROPIC_API_KEY` selon le modèle choisi)
- `LLM_MODEL` (ex: `gpt-4o`, `claude-sonnet-4-6`)

---

## Règles de dev

- Chaque tool : docstring claire (le LLM la lit pour décider quand appeler le tool)
- Pas de logique métier dans `agent.py` ou `serve.py` — seulement le wiring
- Les docs RAG (`core/copepod_rag/docs/*.md`) ne se modifient pas sans rebuilt de l'index
- TDD : écrire le test avant l'implémentation pour chaque tool
