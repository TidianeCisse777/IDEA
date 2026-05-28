# Langfuse REST API — Inspection des traces et observations

Le CLI `npx langfuse-cli` échoue contre le self-hosted (`localhost:3001`) — il reçoit du HTML au lieu de JSON. Utiliser l'API REST directement via curl avec Basic Auth.

## Credentials

Dans `IDEA/.env` :

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST_LOCAL=http://localhost:3001
```

Auth : `PUBLIC_KEY:SECRET_KEY` en Basic Auth.

---

## Recettes

### Lister les traces récentes par tag

```bash
curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "http://localhost:3001/api/public/traces?tags=du-multi&limit=20" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data['data']:
    print(t['id'], t['name'], t['timestamp'], 'output:', t.get('output') and 'done' or 'running')
"
```

### Lister les observations d'une trace avec I/O

```bash
TRACE_ID="891a3a0d-..."

curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "http://localhost:3001/api/public/observations?traceId=$TRACE_ID&limit=100" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
for o in data.get('data', []):
    print(o['startTime'][:19], o.get('name',''))
print('total:', data['meta']['totalItems'])
"
```

### Inspecter les arguments d'un tool call spécifique

```bash
curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "http://localhost:3001/api/public/observations?traceId=$TRACE_ID&limit=100" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
for o in data.get('data', []):
    name = o.get('name', '')
    if 'create_data_understanding_draft' in name:
        print('INPUT kwargs:', json.dumps((o.get('input') or {}).get('kwargs', {}), indent=2, ensure_ascii=False)[:2000])
        print('OUTPUT:', json.dumps(o.get('output', {}), indent=2, ensure_ascii=False)[:500])
"
```

### Filtrer par nom d'observation exact (URL-encodé)

```bash
curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "http://localhost:3001/api/public/observations?traceId=$TRACE_ID&name=round-unknown%2Ftool%2Fcreate_data_understanding_draft&limit=50"
```

---

## Structure d'une observation tool

```json
{
  "name": "round-unknown/tool/create_data_understanding_draft",
  "startTime": "2026-05-28T18:25:43.680Z",
  "input": {
    "args": [],
    "kwargs": {
      "session_key": "eval-user:du-multi-xxx:copepod",
      "artifact": { ... }
    }
  },
  "output": {
    "status": "draft",
    "payload": { ... }
  }
}
```

---

## Trouver le trace_id d'un eval

Le log eval affiche le `session_id` en en-tête :

```
=== DU-MULTI EVAL du-multi-555fe991af model=gpt-5.4-mini ===
```

Le trace Langfuse correspondant a `sessionId = eval-user:du-multi-555fe991af:copepod`.  
Chercher par tag dans `/api/public/traces?tags=du-multi` ou via l'UI sur `http://localhost:3001`.

---

## Cas d'usage — diagnostiquer un FAIL eval

Quand un check échoue (ex. `payload_has_n_files`), inspecter les observations pour voir exactement ce que le LLM a passé aux tools :

| Champ | Ce qu'il révèle |
|---|---|
| `input.kwargs.artifact` sur `create_data_understanding_draft` | Structure réelle passée par le LLM — permet de détecter si le LLM a reconstruit l'artifact de mémoire au lieu de passer le return de `synthesize_file_understanding` |
| `input.args[0]` sur `summarize_understanding` | Rapport inspect_file passé — colonnes, types, sample values |
| `output` sur `synthesize_file_understanding` | Ce que le tool a retourné — `file_summaries`, `global` block |

**Exemple concret (mai 2026)** : le check `payload_has_n_files` retournait 0 fichiers.  
En inspectant `input.kwargs.artifact` sur `create_data_understanding_draft`, on a vu que le LLM passait les keys de `summarize_understanding` (`column_catalogue`, `probable_source_type`, etc.) au lieu du return de `synthesize_file_understanding` (`file_summaries`, `global`). Le LLM avait reconstruit l'artifact de mémoire.
