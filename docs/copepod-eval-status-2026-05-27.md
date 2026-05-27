# Copepod Eval Status — 2026-05-27

Modèle : `gpt-5.4-mini`  
Fixture : `ecotaxa_green_edge_sample_200.tsv` (200 lignes, 161 colonnes, profondeurs 0.5–358 m)

---

## Scores du dernier run

| Eval | Score | Script |
|---|---|---|
| Plan Mode | **6 / 14** | `run_copepod_plan_mode_eval.py` |
| Rejection / Retraction | **1 / 4** | `run_copepod_rejection_eval.py` |
| Off-topic | **1 / 2** | `run_copepod_offtopic_eval.py` |
| Direct Analysis | **1 / 2** | `run_copepod_direct_analysis_eval.py` |

---

## Détail par eval

### Plan Mode (6/14)

| Test | Statut | Note |
|---|---|---|
| `live_llm_created_data_understanding_draft` | **FAIL** | Aucun DU draft créé — `summarize_understanding` crashe |
| `live_llm_waited_for_data_understanding_confirmation` | PASS | — |
| `live_describe_column_covered_all_unmatched` | **FAIL** | 8 appels pour 0 colonnes "unmatched" (le filtre a tout exclu, mais le compte attendu est 0) |
| `live_phase1_efficient` | PASS | — |
| `live_du_payload_has_column_catalogue` | **FAIL** | Pas de DU artifact → pas de `column_catalogue` |
| `live_llm_activated_data_understanding` | **FAIL** | Pas de DU activé |
| `live_llm_created_graph_context_draft_linked_to_active_du` | **FAIL** | Pas de GC draft (dépend du DU) |
| `live_llm_did_not_emit_plan_ready_before_graph_context_confirmation` | PASS | — |
| `live_backend_blocked_premature_plan_ready_button` | PASS | — |
| `live_llm_waited_for_graph_context_confirmation` | PASS | — |
| `live_gc_payload_has_all_required_fields` | **FAIL** | Pas de GC artifact |
| `live_llm_activated_graph_context` | **FAIL** | Pas de GC activé |
| `live_plan_ready_enables_analyse_mode` | **FAIL** | `[PLAN_READY]` jamais émis |
| `live_no_internal_terms_in_llm_text` | PASS | — |

### Rejection / Retraction (1/4)

| Test | Statut | Note |
|---|---|---|
| `live_llm_creates_new_du_draft_on_rejection` | **FAIL** | Aucun DU draft créé (même cause que Plan Mode) |
| `live_llm_creates_new_gc_draft_on_rejection` | **FAIL** | Aucun GC draft (dépend du DU) |
| `live_llm_creates_new_du_draft_on_retraction` | **FAIL** | LLM refuse de créer un DU — déclenche la règle anti-code |
| `live_llm_creates_new_gc_draft_on_retraction` | **PASS** | Fonctionne : le LLM appelle `get_active_data_understanding` puis `create_graph_context_draft` |

### Off-topic (1/2)

| Test | Statut | Note |
|---|---|---|
| `live_offtopic_answered_scientific_question` | **PASS** | Le LLM répond correctement à la question calanoïde/cyclopoïde |
| `live_offtopic_workflow_continued_after_question` | **FAIL** | Le LLM voit "histogramme, Python, PNG" dans le message de confirmation → déclenche la règle anti-code → refuse au lieu de créer le GC draft |

### Direct Analysis (1/2)

| Test | Statut | Note |
|---|---|---|
| `live_direct_analysis_refused_before_plan_mode` | **FAIL** | Le LLM appelle `inspect_file` (au lieu de refuser d'abord) puis dit que le fichier n'est pas lisible. La détection `"plan" in reply.lower()` rate car le mot "Plan Mode" n'apparaît pas dans la réponse |
| `live_post_plan_ready_direct_code_refused` | **PASS** | Le LLM refuse correctement de générer du code après `[PLAN_READY]` |

---

## Causes racines

### 1 — `summarize_understanding` crashe (bloqueur principal)

**Impact** : Plan Mode, Rejection/DU, Rejection/GC — tout ce qui dépend de la création d'un DU.

**Mécanisme** : En mode function-calling (eval), le LLM doit sérialiser `inspect_report` en JSON dans les arguments de l'appel. Pour 161 colonnes, ce JSON fait ~15 000 caractères. Le LLM atteint sa limite de tokens en sortie → JSON tronqué → `json.JSONDecodeError: Unterminated string at char 15211`.

**En production** (OpenInterpreter / code Python) : le LLM écrit `summarize_understanding(ir, rr, defs)` avec des variables Python — pas de sérialisation, pas de problème. L'eval teste une abstraction différente de la production.

**Fix à faire** : Dans `_live_tool_impls`, mettre en cache les résultats de `inspect_file` et `infer_column_roles`. La version wrapper de `summarize_understanding` utilise le cache au lieu d'exiger que le LLM re-passe les gros objets. Mettre `inspect_report` et `role_report` comme non-requis dans `_tool_specs`. Mettre à jour le prompt pour dire "n'inclus pas `inspect_report`/`role_report` dans l'appel".

### 2 — Le LLM saute `infer_column_roles`

**Impact** : Phase 1 incomplète — `role_report` manquant pour `summarize_understanding`.

**Mécanisme** : Le LLM va directement de `inspect_file` à `describe_column` (×8–9 appels selon le filtre). Cause probable : après avoir vu le volume du résultat d'`inspect_file` (161 colonnes), le LLM anticipe qu'appeler `infer_column_roles(columns=<161 objets>)` produirait un argument JSON trop grand et saute l'étape.

**Fix à faire** : Dans le prompt (`copepod_mode_plan.py`), step b : préciser "passe uniquement les noms de colonnes `[col['name'] for col in inspect_report['columns']]` — pas les objets complets". Rendre la règle d'enchaînement plus dure.

### 3 — Conflit dans la règle de refus de code

**Impact** : Off-topic Phase 2 (workflow non continué) + Rejection C-DU (retraction refusée) + détection Direct Analysis Scenario A.

**Mécanisme** : Le prompt dit "refuse AVANT d'appeler un outil" ET "commence Phase 1 dans le même message après avoir refusé". Ces deux instructions se contredisent. Conséquence :
- Quand l'utilisateur dit "histogramme, Python, PNG" dans un message de confirmation Phase 2, le LLM croit que c'est une demande de code → refuse.
- Quand l'utilisateur dit "je veux revoir l'analyse du fichier" (retraction C-DU), le LLM déclenche la règle de refus.

**Fix à faire** : Clarifier la règle de refus pour qu'elle ne s'applique que si le message ne contient *que* une demande de code/graphique — pas si c'est du contexte scientifique dans un message de confirmation Phase 2. Clarifier que la retraction est une révision du plan, pas une demande de code.

### 4 — Détection `live_direct_analysis_refused_before_plan_mode` trop stricte

**Impact** : Scenario A de `direct_analysis_eval` toujours FAIL.

**Mécanisme** : La détection actuelle = `"plan" in reply.lower()`. Quand le LLM appelle `inspect_file` puis dit "le fichier n'est pas lisible", le mot "plan" n'apparaît pas.

**Fix à faire** : Soit élargir la détection (`python_block absent` ET (`inspect_file` appelé OU `"plan"` présent)), soit rendre la règle de refus plus forte pour que le LLM dise explicitement "Plan Mode" dans sa réponse.

---

## Ce qui fonctionne correctement

- Refus de code après `[PLAN_READY]` (Direct Analysis Scenario C)
- Réponse aux questions scientifiques hors-sujet (Off-topic)
- Retraction du GC uniquement (Rejection Scenario C-GC)
- Règles de langage (aucun terme interne dans les messages utilisateur)
- Blocage du bouton Analyse tant que le GC n'est pas actif
- Le LLM attend la confirmation avant d'activer DU et GC

---

## Logs de référence

```
logs/evals/live_eval_live-eval-c51b273702.log     # Plan Mode run principal
logs/evals/rejection_eval_e685960bb2.log           # Rejection run principal
logs/evals/offtopic_eval_offtopic-eval-a5dc35b0af.log
logs/evals/direct_analysis_eval_2d0465260c.log
```
