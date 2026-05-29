# Langfuse Live Logger

Script qui poll l'API Langfuse toutes les 5 secondes et écrit les traces en temps réel dans `logs/langfuse_live.log`.

## Prérequis

- Langfuse self-hosted tourne sur `localhost:3001`
- `LANGFUSE_PUBLIC_KEY` et `LANGFUSE_SECRET_KEY` dans `IDEA/.env` (ou définis dans l'environnement)

## Lancer le logger

```bash
# Depuis IDEA/
python3 scripts/langfuse_live_log.py
```

Suivre dans un second terminal :

```bash
tail -f logs/langfuse_live.log
```

## Options

| Option | Défaut | Description |
|---|---|---|
| `--tail` | off | Stdout seulement, pas d'écriture fichier |
| `--limit N` | 30 | Nb de traces à surveiller à chaque poll |

```bash
python3 scripts/langfuse_live_log.py --tail          # stdout only
python3 scripts/langfuse_live_log.py --limit 50      # surveille plus de traces
```

## Lire le log

```
────────────────────────────────────────────────────────────────────────
[13:59:01] TRACE  idea-chat-runtime  session=9cdfa9c8…  tags=[chat, copepod, runtime]
         id=a7f9761b-d0a2-4394-8ed6-012ea9641dec
  [13:59:07] SPAN   round-20/tool/activate_data_understanding
             IN    {"session_key": "copepod-abc", "source_file": "loki.tsv"}
             OUT   {"status": "active", "payload": {…}}
  [13:59:08] LLM    round-20  model=openai/gpt-5.4-mini  tokens=19762  5.1ms
             PROMPT  {"messages": [{…}]} …
             REPLY   "Je vais analyser les colonnes…"
```

- **TRACE** — une conversation IDEA (session ID + tags)
- **SPAN** — un tool call (`round-N/tool/nom`) avec ses inputs/outputs
- **LLM** — appel LiteLLM avec modèle, tokens, latence, prompt et réponse tronqués

Quand de nouvelles observations arrivent sur une trace déjà connue :

```
  [14:00:03] +2 obs  trace=a7f9761b-d0a2…
  [14:00:03] SPAN   round-21/tool/create_graph_context
             IN    {…}
             OUT   {…}
```

## Ce qui est tracé / pas tracé

**Tracé** : tout ce qui passe par IDEA (LiteLLM + Open Interpreter) — conversations depuis l'interface web, evals.

**Pas tracé** : conversations directes avec Claude Code CLI (côté Anthropic, pas routé par IDEA).

## Diagnostiquer un eval

Lancer le logger avant un eval, puis lancer l'eval dans un autre terminal :

```bash
# Terminal 1
python3 scripts/langfuse_live_log.py

# Terminal 2
docker exec -it idea-app python scripts/evals/run_copepod_plan_mode_eval.py --gc-only
```

Les tool calls apparaissent en temps réel — utile pour voir exactement ce que le LLM passe aux tools sans aller dans l'UI Langfuse.
