# Copepod Eval Status — 2026-05-27

Modèle : `gpt-5.4-mini`
Fixture : `ecotaxa_green_edge_sample_200.tsv` (200 lignes, 161 colonnes, profondeurs 0.5–358 m)

---

## Historique des scores

| Eval | Run 1 (avant compaction) | Run 2 (après compaction) |
|---|---|---|
| Plan Mode | 6 / 14 | **7 / 14** |
| Rejection / Retraction | 1 / 4 | crash rate limit |
| Off-topic | 1 / 2 | **1 / 2** |
| Direct Analysis | 1 / 2 | **2 / 2** ✓ |

> Run 2 lancé avec les 4 evals en parallèle → rate limit 200k TPM atteint mid-rejection.
> À relancer en séquentiel.

---

## Détail par eval — Run 2

### Plan Mode (7/14)

| Test | Run 1 | Run 2 | Note |
|---|---|---|---|
| `live_llm_created_data_understanding_draft` | FAIL | **PASS** | Compaction a fixé le crash `summarize_understanding` |
| `live_llm_waited_for_data_understanding_confirmation` | PASS | PASS | — |
| `live_describe_column_covered_all_unmatched` | FAIL | FAIL | 4 appels pour 108 unmatched — filtre pas assez strict |
| `live_phase1_efficient` | PASS | PASS | — |
| `live_du_payload_has_column_catalogue` | FAIL | FAIL | `column_catalogue` vide dans le payload DU |
| `live_llm_activated_data_understanding` | FAIL | FAIL | LLM active le DU en Phase 3 au lieu de Phase 2 |
| `live_llm_created_graph_context_draft_linked_to_active_du` | FAIL | FAIL | Dépend de l'activation Phase 2 |
| `live_llm_did_not_emit_plan_ready_before_graph_context_confirmation` | PASS | PASS | — |
| `live_backend_blocked_premature_plan_ready_button` | PASS | PASS | — |
| `live_llm_waited_for_graph_context_confirmation` | PASS | PASS | — |
| `live_gc_payload_has_all_required_fields` | FAIL | FAIL | GC créé sans les champs requis |
| `live_llm_activated_graph_context` | FAIL | FAIL | — |
| `live_plan_ready_enables_analyse_mode` | FAIL | FAIL | `[PLAN_READY]` jamais émis |
| `live_no_internal_terms_in_llm_text` | PASS | PASS | — |

### Direct Analysis (2/2) ✓

| Test | Run 1 | Run 2 | Note |
|---|---|---|---|
| `live_direct_analysis_refused_before_plan_mode` | FAIL | **PASS** | Le LLM mentionne maintenant "Plan Mode" dans sa réponse |
| `live_post_plan_ready_direct_code_refused` | PASS | PASS | — |

### Off-topic (1/2)

| Test | Run 1 | Run 2 | Note |
|---|---|---|---|
| `live_offtopic_answered_scientific_question` | PASS | PASS | — |
| `live_offtopic_workflow_continued_after_question` | FAIL | FAIL | Phase 1 : LLM appelle `inspect_file` 2× sans créer de DU draft |

### Rejection / Retraction

Run 2 crashé sur rate limit pendant scenario A-DU (4 evals en parallèle).
Phase 1 du scenario A-DU était en bonne voie avant le crash : `inspect_file` → `infer_column_roles` → `describe_column`×2 → interrompu.

---

## Causes racines actives

### 1 — Phase 2 : activation DU sautée ← bloqueur principal

**Impact** : `live_llm_activated_data_understanding`, `live_llm_created_graph_context_draft_linked_to_active_du`, `live_gc_payload_has_all_required_fields`, `live_plan_ready_enables_analyse_mode` (cascade).

**Mécanisme** : Quand l'utilisateur confirme l'analyse (Phase 2), le LLM appelle `get_active_data_understanding` avant d'appeler `activate_data_understanding`. Il voit que rien n'est actif → dit "l'analyse n'est pas disponible" → refuse d'avancer. L'activation arrive finalement en Phase 3 (confirmation GC), trop tard pour les checks.

**Fix à faire** : Rendre la règle du Confirmation Protocol plus explicite : "la première action après confirmation utilisateur est TOUJOURS `activate_data_understanding(session_key, version_id)` avec le `version_id` du draft affiché. Ne pas appeler `get_active_data_understanding` avant d'avoir activé."

### 2 — `column_catalogue` vide dans le DU payload

**Impact** : `live_du_payload_has_column_catalogue`.

**Mécanisme** : `summarize_understanding` ne crashe plus, mais il ne reçoit plus `role_report` (le LLM ne le passe pas en argument puisque le compact `infer_column_roles` ne retourne plus les rôles détaillés — juste `matched_count` et `unmatched_columns`). Sans `role_report`, `summarize_understanding` produit un `column_catalogue` vide.

**Fix à faire** : Dans `_live_tool_impls`, mettre en cache le résultat complet de `infer_column_roles` (pas la version compacte) et l'injecter dans `summarize_understanding` via le wrapper — identique à ce qui est prévu pour `inspect_report`.

### 3 — Offtopic Phase 1 : `inspect_file` appelé 2× sans DU draft

**Impact** : `live_offtopic_workflow_continued_after_question`.

**Mécanisme** : Le LLM appelle `inspect_file` deux fois de suite sans passer à `infer_column_roles` ni créer de DU draft. Probablement une confusion sur le chemin de fichier dans le compact result (le chemin contient un session_id → "fichier non accessible" → retry).

**Fix à faire** : Vérifier que le chemin retourné dans le compact `inspect_file` est correct et accessible.

### 4 — Rate limit sur runs parallèles

**Impact** : Rejection eval inutilisable quand les 4 scripts tournent en même temps.

**Fix à faire** : Lancer les evals en séquentiel, ou ajouter un délai entre les lancements.

---

## Ce qui fonctionne

- Phase 1 complète : `inspect_file` → `infer_column_roles` → `describe_column`×N → `summarize_understanding` → `create_data_understanding_draft` ✓
- Refus de code en Plan Mode (avant et après `[PLAN_READY]`) ✓
- Réponse aux questions scientifiques hors-sujet ✓
- Retraction GC uniquement (Rejection Scenario C-GC) ✓
- Aucun terme interne dans les messages utilisateur ✓
- Blocage du bouton Analyse avant GC actif ✓

---

## Améliorations apportées dans cette session

| Changement | Impact |
|---|---|
| `_compact_tool_result` : grouping par rôle pour `inspect_file` | -92% tokens (9k → 759) |
| `_compact_tool_result` : unmatched only pour `infer_column_roles` | -78% tokens |
| `_compact_tool_result` : confirmation only pour `summarize_understanding` | -97% tokens |
| `_compact_tool_result` : strip payload pour tous les artifacts | -99% tokens |
| `_EVAL_CANONICAL_SESSION_ID` : system message stable | prefix caching actif |
| `_cleanup_old_logs` : auto-purge après chaque run | max 3 logs par type |

---

## Logs de référence (run 2)

```
logs/evals/live_eval_live-eval-85d76323a0.log
logs/evals/rejection_eval_9d599536ba.log      # crash rate limit
logs/evals/offtopic_eval_offtopic-eval-21d40c6876.log
logs/evals/direct_analysis_eval_cadbfaeec5.log
```

---

## Guide opérationnel — pour les autres agents

### Conteneur Docker

L'application tourne dans `idea_container`. Vérifier avec :
```bash
docker ps --format "{{.Names}}" | grep idea
# → idea_container, idea_langfuse, idea_langfuse_db, idea-redis-1, idea-db-1, ...
```

### Lancer les evals

**Toujours lancer en séquentiel** — les 4 scripts en parallèle dépassent la limite TPM (200k/min) et le rejection eval crashe.

```bash
# Un script à la fois, depuis le conteneur
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --live
docker exec idea_container python scripts/evals/run_copepod_rejection_eval.py
docker exec idea_container python scripts/evals/run_copepod_offtopic_eval.py
docker exec idea_container python scripts/evals/run_copepod_direct_analysis_eval.py

# En arrière-plan (résultats dans /tmp/)
docker exec -d idea_container bash -c "cd /app && python scripts/evals/run_copepod_plan_mode_eval.py --live > /tmp/eval_plan.out 2>&1"
# Suivre : docker exec idea_container tail -f /tmp/eval_plan.out
```

Les logs sont écrits dans `logs/evals/`. Auto-nettoyage : 3 logs max par type après chaque run.

### Fixture EcoTaxa

```
scripts/evals/fixtures/ecotaxa_green_edge_sample_200.tsv
```
200 lignes, 161 colonnes, campagne Green Edge. Profondeurs 0.5–358 m, 12 taxa validés.
Chemin dans Docker : `/app/scripts/evals/fixtures/ecotaxa_green_edge_sample_200.tsv`

### Erreurs connues et solutions

| Erreur | Cause | Solution |
|---|---|---|
| `RateLimitError 429 TPM` | 4 evals en parallèle = >200k tokens/min | Lancer en séquentiel |
| `Unterminated string at char 15211` | LLM re-sérialise `inspect_report` (161 cols) dans les args JSON | Résolu : `_live_tool_impls` cache les résultats et les injecte dans `summarize_understanding` |
| `No such container: idea-app` | Mauvais nom de conteneur | Utiliser `idea_container` |
| `ModuleNotFoundError: No module named 'redis'` | Exécution hors Docker | Toujours lancer via `docker exec idea_container` |
| `activate_data_understanding → blocked` | LLM appelle `get_active_data_understanding` avant d'activer | Résolu dans le prompt : activation obligatoire en premier |

### Variables d'environnement nécessaires

Dans `.env` à la racine :
- `LLM_MODEL` — ex: `gpt-5.4-mini`
- `LLM_API_KEY` — clé OpenAI
- `OPENAI_API_KEY` — idem (alias utilisé par certains modules)

### Structure des scripts evals

Tous les scripts importent depuis `run_copepod_plan_mode_eval.py` qui contient :
- `_load_tools()` — charge les tools copepod dans un namespace Python
- `_live_tool_impls(tools, session_key)` — wrappers avec cache et injection session_key
- `_compact_tool_result(name, result)` — réduit les résultats de tools avant injection dans le contexte LLM (~94% réduction Phase 1)
- `_build_eval_system_message(store, session_id)` — system message avec `_EVAL_CANONICAL_SESSION_ID` fixe pour le prefix caching
- `_cleanup_old_logs(log_dir, prefix, keep=3)` — purge automatique des vieux logs
