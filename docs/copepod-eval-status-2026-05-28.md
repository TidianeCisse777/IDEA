# Copepod Eval Status — 2026-05-28

Modèle : `gpt-5.4-mini`
Quota OpenAI : **épuisé en fin de session** — recharger avant de relancer.

---

## Point de départ pour la prochaine session

### Ordre de lancement obligatoire

```bash
# 1. Mock — toujours en premier
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --mock
# attendu : 13/13

# 2. DU-only
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --du-only
# attendu : vert

# 3. GC-only
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --gc-only
# attendu : vert

# 4. DU-multi — scénario par scénario, dans cet ordre
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --du-multi --scenario ecotaxa_ogsl
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --du-multi --scenario ecotaxa_ecopart
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --du-multi --scenario ecotaxa_amundsen
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --du-multi --scenario ecotaxa_neolabs
docker exec idea_container python scripts/evals/run_copepod_plan_mode_eval.py --du-multi --scenario neolabs_loki_taxon
```

---

## État des scénarios DU-multi au 2026-05-28

| Scénario | Dernier score | État |
|---|---|---|
| `ecotaxa_bio_oracle` | **14/14** ✅ | Validé — ne pas relancer sauf régression |
| `ecotaxa_ogsl` | **12/14** | À revalider — fixes committés mais quota coupé avant confirmation |
| `ecotaxa_ecopart` | non testé | Bénéficiera des mêmes fixes |
| `ecotaxa_amundsen` | non testé | Bénéficiera des mêmes fixes |
| `ecotaxa_neolabs` | non testé | Bénéficiera des mêmes fixes |
| `neolabs_loki_taxon` | non testé | Bénéficiera des mêmes fixes |

### Fails restants sur `ecotaxa_ogsl` (12/14)

| Test | Cause connue |
|---|---|
| `draft_created` | Round `create_data_understanding_draft` scanné — cherche `status=draft`. Dernier run : round 10 a eu un JSON garblé (truncation 4000 tokens), retry round 11 → `status=draft`. Eval cherchait le premier call seulement. **Fix committé** dans eval_du_multi.py. |
| `payload_has_n_files` | DU payload avait 1 fichier au lieu de 2. **Fix committé** : driver injecte les cached summaries quand LLM passe count < expected. |

---

## Fixes committés dans cette session (2026-05-28)

| Commit | Fichier | Description |
|---|---|---|
| `165627e` | session_store.py, copepod_session_artifacts.py, llm_driver.py, eval_du_multi.py, copepod_mode_plan.py | bio_oracle 14/14 — file_synthesis cache, column_catalogue recovery, synthesize injection, temporal/spatial prompt |
| `f395c07` | eval_du_multi.py, llm_driver.py | ogsl fixes — draft_created scan all calls, file_summaries count injection |
| `07b342f` | llm_driver.py | **Réduction tokens** : inspect_file compact 28K→9K chars, describe_column tronqué à 300 chars, [USAGE] log par round, usageDetails Langfuse fix |

---

## Diagnostics token — ce qu'on sait

- **Cache hit : 91%** côté dashboard OpenAI (7.3M/8M tokens cachés le 28/05)
- **`usageDetails: null`** dans Langfuse = bug de reporting côté code (fix dans `07b342f`), pas un problème de caching réel
- **13/100 rounds maxaient `max_completion_tokens=4000`** — causé par `inspect_file` retournant 161 colonnes × 7 champs dans le compact → le LLM copiait ~28K chars dans ses arguments
- **Fix `07b342f`** réduit à 3 champs/colonne → ~9K chars — attendu : 0 rounds maxés

### Lire les logs [USAGE] après le prochain run

Chaque round dans le log eval affiche maintenant :
```
[USAGE] phase=du-draft round=2 prompt=9845 completion=312 cached=0
```
- `cached=no_details` → modèle ne retourne pas `prompt_tokens_details` (informatif seulement, le caching fonctionne)
- `cached=0` → round 1 normal (froid), devrait monter sur rounds suivants
- `cached=N` → hits confirmés

---

## Architecture llm_driver — points clés

- `_compact_tool_result()` : formate ce que le LLM voit en retour de chaque tool call. C'est ici qu'on contrôle la taille du contexte.
- `_cache["all_summaries"]` : accumule tous les outputs `summarize_understanding` par session. Injecté dans `synthesize_file_understanding` si le LLM passe des summaries incomplets.
- `describe_column_round_seen` : flag par fichier (reset sur `inspect_file`). Bloque un 2ème round de describe_column pour le même fichier.
- `_resolved_tool_specs` : calculé une fois avant la boucle pour garantir le prefix caching.
