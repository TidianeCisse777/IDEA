# Switch OpenRouter → OpenAI direct — runbook

Pour quand tu auras une clé OpenAI directe (`sk-proj-...` ou `sk-...`).

Coût estimé : ~$5 sur OpenAI = ~50 evals complets sur les 20 scénarios EcoTaxa-vision.

---

## Étape 1 — Backup du `.env` actuel (10 s)

```bash
cd /Users/tidianecisse/PROJET_INFO/IDEA
cp .env .env.openrouter.backup
```

Si quelque chose foire, on revert avec `cp .env.openrouter.backup .env`.

---

## Étape 2 — Modifier `.env` (1 min)

Trouve ce bloc dans `.env` :

```bash
OPENAI_API_KEY=sk-or-v1-396be1...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
LLM_API_BASE=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-5.4-mini
```

Remplace-le par :

```bash
OPENAI_API_KEY=sk-proj-...                   # ta vraie clé OpenAI
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
# LLM_API_BASE=https://openrouter.ai/api/v1
LLM_MODEL=gpt-4o-mini
```

Les `#` désactivent les 2 lignes du milieu. Tu peux aussi les supprimer — même effet.

---

## Étape 3 — Smoke test connexion (5 s)

```bash
set -a && source ./.env && set +a && \
.venv/bin/python -c "
from langchain_openai import ChatOpenAI
import os
llm = ChatOpenAI(model=os.getenv('LLM_MODEL'))
print(llm.invoke('Reply with just OK').content)
"
```

Résultat attendu : `OK` (ou similaire).

**Si erreur 401** → ta clé OpenAI est mauvaise / expirée / sans crédit.
**Si erreur de network** → tu as oublié de commenter `OPENAI_BASE_URL` (le SDK essaie OpenRouter avec une clé OpenAI).
**Si erreur "model not found"** → vérifie que ton compte OpenAI a accès à `gpt-4o-mini` (par défaut oui).

---

## Étape 4 — Test cible (4 scénarios eval — ~$0,05)

```bash
set -a && source ./.env && set +a && \
EVAL_CASE_IDS="EC-01-search,EC-09-anti-query-for-schema,EC-16-chain-observations-then-count,EC-20-no-tool-needed" \
.venv/bin/python evals/eval_ecotaxa_vision.py 2>&1 | tail -30
```

**Cible** : EC-09 et EC-16 doivent passer à `1.0` sur `expected_first_tool` (le fix prompt `f2efb29` doit avoir réglé les collisions H1/H3).

| Scénario | Avant le fix | Cible après fix |
|---|---|---|
| EC-01 | 1.0 ✓ | 1.0 ✓ |
| EC-09 | 0.5 ◐ | 1.0 ✓ |
| EC-16 | 0.0 ✗ | 1.0 ✓ |
| EC-20 | 1.0 ✓ | 1.0 ✓ |

Moyenne `expected_first_tool` attendue : 1.0 (était 0.62).

---

## Étape 5 — Full eval baseline (20 scénarios — ~$0,30)

Si l'étape 4 valide les fixes, lance le full :

```bash
set -a && source ./.env && set +a && \
.venv/bin/python evals/eval_ecotaxa_vision.py 2>&1 | tail -50
```

Le runner pousse le dataset sur LangSmith (projet `copepod-ecotaxa-vision-evals`), tu auras le dashboard complet.

**Cible globale** : > 0,8 sur les 3 métriques M1/M2/M3.

---

## Étape 6 — Documenter le baseline dans le PRD

Une fois les scores stables, mettre à jour `docs/PRD_MCP_ECOTAXA.md` section §11 (Journal) avec :

```
| 2026-MM-JJ | Eval ecotaxa-vision baseline post-fix prompt : M1=X.XX, M2=Y.YY, M3=Z.ZZ sur 20 scénarios. Modèle: gpt-4o-mini direct. |
```

Et cocher P1 dans §12 Suivi post-V1.

---

## Notes annexes

### Le judge eval (legacy) reste sur OpenRouter

`evals/judge.py:13` a un fallback codé en dur vers `https://openrouter.ai/api/v1`. Tant que `OPENAI_BASE_URL` est unset (commenté), le judge utilisera api.openai.com par défaut depuis la lib OpenAI **sauf** si tu lances une eval `eval_inspection.py` / `eval_analysis.py` / `eval_safety.py` qui passent par lui — là il essaiera OpenRouter.

**Si tu lances ces evals legacy en plus**, il faut soit :
- Set `OPENAI_BASE_URL=https://api.openai.com/v1` explicitement
- Ou fix `evals/judge.py:13` pour utiliser le default OpenAI

Pour l'eval ecotaxa-vision (M3+M5), pas de souci — elle n'utilise pas le judge.

### Revenir à OpenRouter

```bash
cp .env.openrouter.backup .env
```

Et redémarre les processus qui auraient cache la connexion.

### Garder les deux clés actives

Tu peux laisser **les deux** clés dans `.env` en gardant la clé OpenAI sous `OPENAI_API_KEY` (priorité) et noter la clé OpenRouter en commentaire pour pouvoir switcher facilement :

```bash
OPENAI_API_KEY=sk-proj-...
# OpenRouter (commenter ci-dessus + décommenter ci-dessous pour basculer)
# OPENAI_API_KEY=sk-or-v1-...
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
# LLM_API_BASE=https://openrouter.ai/api/v1
LLM_MODEL=gpt-4o-mini
```

---

## Garantie

L'archi MCP EcoTaxa est **indépendante du provider LLM** (cf. `docs/MCP_ECOTAXA_USE_CASES.md` §5). Les 361 tests pytest passent sans toucher au LLM. Seul l'eval `ecotaxa_vision` mesure la qualité du LLM ; switcher de provider change les scores baseline, pas le code.
