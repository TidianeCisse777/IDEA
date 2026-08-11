# Monitoring local de l’agent

Le service doit être accessible sur `http://localhost:8000`.

## 1. Trouver une conversation

Ouvrir dans le navigateur :

<http://localhost:8000/debug/harness-turns>

La réponse liste les `thread_id` actuellement gardés en mémoire.

## 2. Parcourir ses tours

Remplacer `THREAD_ID` :

<http://localhost:8000/debug/harness-turns?thread_id=THREAD_ID&limit=20>

Chaque tour montre la demande, le contexte réellement envoyé au modèle,
les DataFrames visibles, les tools exposés, les décisions, les appels de tools,
les durées et les tokens.

## 3. Ouvrir un tour précis

Remplacer aussi `3` par le numéro du tour :

<http://localhost:8000/debug/harness-turns?thread_id=THREAD_ID&turn_index=3>

Dans `model_calls`, regarder principalement :

- `context.current_task` et `context.available_dataframes` ;
- `response_preview` et `requested_tools` ;
- `tools_exposed` et `provider_usage`.

Dans `tool_calls`, vérifier `name`, `arguments`, `status`, `data_ref`,
`provenance`, `metrics` et `result_preview`.

## 4. Suivre le tour courant

```bash
watch -n 2 'curl -s "http://localhost:8000/debug/harness-trace?thread_id=THREAD_ID" | jq'
```

## 5. Lire les traces persistées

Les traces terminées survivent au redémarrage dans :

```text
logs/conversations/THREAD_ID.jsonl
```

Dernier tour enregistré :

```bash
tail -n 1 logs/conversations/THREAD_ID.jsonl | jq '.harness_turn'
```

Les routes `/debug` sont destinées au développement local : les traces peuvent
contenir les demandes utilisateur et des métadonnées de session.
