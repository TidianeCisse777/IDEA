# LangGraph Context Middleware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Appliquer réellement les limites de contexte aux messages envoyés au modèle et rendre l'audit fidèle, sans altérer les checkpoints.

**Architecture:** La préparation migre de `before_model` vers le seam `wrap_model_call`/`awrap_model_call`. Le middleware remplace la requête modèle, pas le state LangGraph.

**Tech Stack:** Python 3.13, LangChain 1.x middleware, LangGraph, pytest.

## Global Constraints

- Préserver les paires `AIMessage.tool_calls` / `ToolMessage`.
- Conserver l'historique complet dans les checkpoints.
- TDD : observer l'échec intégré avant de modifier `agent.py`.
- Préserver les variantes mémoire sync et async.

---

### Task 1: Prouver puis corriger le contexte réellement envoyé

**Files:**
- Modify: `tests/test_agent_factory.py`
- Modify: `agent.py`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Consumes: `_ContextMiddleware`, `get_context_audit`, `create_agent`.
- Produces: requête modèle réellement bornée et audit fidèle.

- [ ] Ajouter un test spy-model avec ancien tour volumineux, tour récent et paire tool-call/résultat.
- [ ] Exécuter ce test et vérifier qu'il échoue parce que l'ancien tour reste visible.
- [ ] Extraire la troncature et le trim en helpers du middleware.
- [ ] Préparer `request.messages` dans les wrappers sync/async avec `request.override`.
- [ ] Supprimer `_make_context_hook`, son pseudo-trim et son injection mémoire morte.
- [ ] Vérifier le test intégré, puis les tests mémoire sync/async/no-op.
- [ ] Mettre `ARCHITECTURE.md` à jour : plafond actif, trim non destructif des checkpoints.

### Task 2: Vérification de non-régression

**Files:**
- Verify: `tests/test_agent_factory.py`
- Verify: `tests/test_serve_streaming.py`
- Verify: `tests/test_cli.py`

**Interfaces:**
- Consumes: middleware corrigé.
- Produces: preuve de compatibilité agent, streaming et CLI.

- [ ] Exécuter les tests agent ciblés.
- [ ] Exécuter les tests streaming et CLI.
- [ ] Exécuter toute la suite `tests/`.
- [ ] Inspecter le diff, vérifier la documentation et committer.
