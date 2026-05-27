# Guide Langfuse — IDEA Copepod

Ce guide explique comment accéder aux traces, scores et sessions Langfuse générés par le runner d'évaluation Plan Mode (`scripts/evals/run_copepod_plan_mode_eval.py`) — à la fois via l'interface web et via le CLI / SDK Python.

---

## Prérequis : variables d'environnement

Langfuse n'est actif que si `LANGFUSE_PUBLIC_KEY` est défini dans `.env` :

```env
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3001        # Docker local
# ou
LANGFUSE_HOST=https://cloud.langfuse.com  # Cloud
```

Sans `LANGFUSE_PUBLIC_KEY`, `core/copepod_observability.py:trace_copepod_event()` retourne silencieusement et aucune trace n'est envoyée. Le comportement runtime reste identique.

Pour les appels CLI dans ce guide, exporter aussi :

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=http://localhost:3001
```

---

## Lancer les evals et pousser vers Langfuse

```bash
# Mock : 12 checks déterministes, sans LLM, avec push Langfuse
python scripts/evals/run_copepod_plan_mode_eval.py --mock --push-langfuse

# Live : LLM réel (LLM_MODEL depuis .env), trace complète + scores
python scripts/evals/run_copepod_plan_mode_eval.py --live --push-langfuse

# Smoke : une seule génération pour vérifier que les traces arrivent
python scripts/evals/run_copepod_plan_mode_eval.py --trace-smoke --push-langfuse

# Sortie JSON (utile pour automatiser ou déboguer)
python scripts/evals/run_copepod_plan_mode_eval.py --live --push-langfuse --json
```

La dernière ligne de la sortie `--push-langfuse` est l'URL directe vers la trace :

```
Langfuse trace: https://cloud.langfuse.com/trace/abc123...
```

---

## Ce qui est créé dans Langfuse

### Mode mock (`--mock`)

Crée **une trace** via `_push_scores_to_langfuse()` :

| Champ | Valeur |
|---|---|
| `name` | `copepod-plan-mode-eval-scores` |
| `tags` | `["eval", "copepod", "scores"]` |
| `user_id` | `eval-user` |
| `session_id` | clé de session (`eval-user:{session_id}:copepod`) |
| `input` | `{"dataset": "copepod-plan-mode-v1"}` |
| `output` | `{"passed_count": N, "total_count": 12}` |

Chaque check est attaché comme **score boolean** sur cette trace.

### Mode live (`--live`)

Crée **une trace parente** via `_make_eval_trace()` :

| Champ | Valeur |
|---|---|
| `name` | `copepod-eval/live` |
| `tags` | `["eval", "copepod", "plan-mode", "live"]` |
| `session_id` | `eval-user:{live-eval-xxxx}:copepod` |
| `input` | `{"model": "...", "file": "ecotaxa_sample_50.tsv", "session_id": "..."}` |

Sous cette trace, **3 spans de phase** :

| Span | Contenu |
|---|---|
| `phase/du-draft` | Phase 1 — inspection + création du Data Understanding |
| `phase/gc-draft` | Phase 2 — activation DU + création Graph Context |
| `phase/plan-ready` | Phase 3 — activation GC + émission `[PLAN_READY]` |

Chaque span contient des **générations** nommées `round-N` (une par appel LLM), avec :
- `model` : le modèle utilisé
- `input` : les 2 derniers messages + nombre d'outils
- `output` : noms des tool_calls + contenu texte
- `usage_details` : tokens prompt / completion / total
- `metadata` : phase, round, tool_calls

### Mode trace-smoke (`--trace-smoke`)

Crée une trace `copepod-langfuse-trace-smoke` avec une génération `trace-smoke-prompt` et un score boolean `trace_smoke_prompt_returned_output`.

---

## Naviguer dans l'interface Langfuse

### Retrouver une trace par session

Toutes les traces d'un eval partagent le même `session_id` (= la clé de session).
Dans l'interface Langfuse → **Sessions** → chercher `eval-user:live-eval-...`.
Toutes les traces du run apparaissent regroupées.

### Lire les scores

Dans une trace → onglet **Scores** :
- `1.0` = PASS (type `BOOLEAN`)
- `0.0` = FAIL
- Le champ `comment` contient le `detail` du check (message explicatif)

Score names du mode mock :

| Score | Ce qu'il vérifie |
|---|---|
| `upload_ecotaxa_creates_data_understanding` | DU créé en `draft` après upload |
| `analyse_blocked_before_active_artifacts` | HTTP 409 avant activation |
| `graph_context_without_data_understanding_version_is_blocked` | GC sans DU ref rejeté |
| `phase_gate_blocks_graph_context_before_data_understanding_confirmation` | Gate DU → GC |
| `plan_ready_button_not_emitted_before_minimum_turns` | Pas de bouton avant min turns |
| `backend_phase_gate_blocks_premature_plan_ready_button` | Backend supprime le bouton |
| `data_understanding_confirmation_activates_artifact` | Confirmation → status `active` |
| `graph_context_draft_links_to_active_du` | GC référence le bon `version_id` |
| `plan_ready_after_graph_context_activation` | Bouton Analyse + HTTP 200 |
| `upload_in_analyse_creates_draft_without_replan` | Re-upload sans reset |
| `analyse_blocked_when_graph_context_references_stale_data_understanding` | Stale linkage → 409 |
| `artifact_debug_routes_are_copepod_only` | Route debug → 404 pour generic |

Score names du mode live (ajoutés à la trace parente) :

| Score | Phase |
|---|---|
| `live_llm_created_data_understanding_draft` | Phase 1 |
| `live_llm_waited_for_data_understanding_confirmation` | Phase 1 |
| `live_describe_column_covered_all_unmatched` | Phase 1 |
| `live_phase1_efficient` | Phase 1 |
| `live_du_payload_has_column_catalogue` | Phase 1 |
| `live_llm_activated_data_understanding` | Phase 2 |
| `live_llm_created_graph_context_draft_linked_to_active_du` | Phase 2 |
| `live_llm_did_not_emit_plan_ready_before_graph_context_confirmation` | Phase 2 |
| `live_backend_blocked_premature_plan_ready_button` | Phase 2 |
| `live_llm_waited_for_graph_context_confirmation` | Phase 2 |
| `live_gc_payload_has_all_required_fields` | Phase 2 |
| `live_llm_activated_graph_context` | Phase 3 |
| `live_plan_ready_enables_analyse_mode` | Phase 3 |

### Lire les générations (tokens, latence)

Dans une trace live → span `phase/du-draft` → génération `round-1` :
- **Input** : derniers messages + nombre d'outils disponibles
- **Output** : tool_calls appelés + réponse texte
- **Usage** : tokens prompt/completion/total

Utile pour détecter les phases inefficaces (beaucoup de rounds) ou les modèles qui consomment trop de tokens en phase 1.

---

## Accès programmatique via CLI

Le CLI `langfuse-cli` (via `npx`, sans installation) permet de requêter l'API directement.

### Lister les traces d'un eval

```bash
# Toutes les traces taguées "eval" et "copepod"
npx langfuse-cli api traces list \
  --tags eval copepod \
  --user-id eval-user \
  --fields core,scores \
  --json

# Traces d'une session spécifique (clé de session complète)
npx langfuse-cli api traces list \
  --session-id "eval-user:live-eval-abc123:copepod" \
  --json

# Traces récentes (dernier run live)
npx langfuse-cli api traces list \
  --name "copepod-eval/live" \
  --from-timestamp "2026-05-27T00:00:00Z" \
  --order-by "timestamp.desc" \
  --limit 5 \
  --json
```

### Récupérer une trace par ID

```bash
npx langfuse-cli api traces get <trace-id> --json
```

La sortie inclut toutes les observations (spans + générations) et les scores attachés.

### Lister les scores d'un eval

```bash
# Tous les scores boolean d'un run mock (par trace-id)
npx langfuse-cli api scores list \
  --trace-id <trace-id> \
  --data-type BOOLEAN \
  --json

# Scores d'une session complète (regroupe mock + live si même session)
npx langfuse-cli api scores list \
  --session-id "eval-user:live-eval-abc123:copepod" \
  --json

# Filtrer sur un score spécifique qui a échoué (value=0)
npx langfuse-cli api scores list \
  --name "live_llm_created_data_understanding_draft" \
  --value 0 \
  --operator "=" \
  --data-type BOOLEAN \
  --json

# Tous les scores des 7 derniers jours pour tracer une régression
npx langfuse-cli api scores list \
  --user-id eval-user \
  --from-timestamp "2026-05-20T00:00:00Z" \
  --data-type BOOLEAN \
  --json
```

### Récupérer une session et ses traces

```bash
# Session complète avec toutes ses traces
npx langfuse-cli api sessions get "eval-user:live-eval-abc123:copepod" --json

# Lister toutes les sessions d'eval
npx langfuse-cli api sessions list \
  --json | jq '.data[] | select(.id | startswith("eval-user"))'
```

---

## Accès programmatique via SDK Python

```python
from langfuse import Langfuse

lf = Langfuse()

# --- Traces ---

# Récupérer les traces d'un run live
traces = lf.fetch_traces(
    user_id="eval-user",
    tags=["eval", "copepod", "live"],
    limit=10,
)
for t in traces.data:
    print(t.id, t.name, t.session_id)

# Récupérer une trace par ID
trace = lf.fetch_trace("trace-id-ici")
print(trace.id, trace.input, trace.output)

# --- Scores ---

# Tous les scores d'une trace
scores = lf.fetch_scores(trace_id="trace-id-ici", data_type="BOOLEAN")
for s in scores.data:
    print(f"{'PASS' if s.value == 1.0 else 'FAIL'}  {s.name}: {s.comment}")

# Scores d'une session entière
scores = lf.fetch_scores(session_id="eval-user:live-eval-abc123:copepod")
failed = [s for s in scores.data if s.value == 0.0]
print(f"{len(failed)} score(s) en échec")

# --- Observations (spans + générations) ---

observations = lf.fetch_observations(trace_id="trace-id-ici")
for obs in observations.data:
    print(obs.name, obs.type, obs.usage)
```

---

## Traces générées par le runtime (hors eval)

`core/copepod_observability.py:trace_copepod_event()` génère des spans pendant l'exécution normale de IDEA (activation d'artifact, transitions de phase, etc.).

Si un eval live est en cours (`COPEPOD_EVAL_LF_TRACE_ID` est défini dans l'environnement), ces spans sont **rattachés à la trace parente** du eval plutôt que créés en orphelin :

```python
# Comportement dans copepod_observability.py
eval_trace_id = os.getenv("COPEPOD_EVAL_LF_TRACE_ID")
if eval_trace_id:
    # Rattaché à la trace eval courante
    span = lf.span(trace_id=eval_trace_id, name=f"tool/{event_name}", ...)
else:
    # Trace indépendante en production
    span = lf.span(name=f"copepod_{event_name}", session_id=session_key, ...)
```

Cela permet de voir les appels d'outils réels (côté backend) alignés avec les générations LLM dans la même trace.

---

## Langfuse local (Docker)

Si `LANGFUSE_HOST` pointe vers `langfuse:3000` (réseau Docker interne), le script détecte automatiquement et rebascule sur `http://localhost:3001` pour les appels depuis le shell local (`_configure_local_langfuse_host()`). Aucune configuration supplémentaire n'est requise.

Vérifier que Langfuse est accessible :

```bash
curl -s http://localhost:3001/api/public/projects
# → 401 Unauthorized = OK, Langfuse répond
```

---

## Boucle debug rapide

1. Lancer `--mock --push-langfuse` → URL trace en sortie → ouvrir dans Langfuse
2. Vérifier l'onglet **Scores** : tous à `1.0` = backend intact
3. Si un score est `0.0` → lire le `comment` pour le message d'erreur, ou via CLI :
   ```bash
   npx langfuse-cli api scores list --trace-id <id> --value 0 --operator "=" --json
   ```
4. Lancer `--live --push-langfuse` → ouvrir la trace → inspecter les spans de phase
5. Un score live à `0.0` + score mock à `1.0` = le backend bloque correctement mais le LLM dérive → fix prompt
6. Un score mock à `0.0` = le backend ne bloque pas → fix tool ou route
7. Pour comparer deux runs, extraire les scores via SDK Python et calculer les deltas par nom de score
