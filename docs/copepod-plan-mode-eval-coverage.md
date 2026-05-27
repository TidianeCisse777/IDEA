# Plan Mode Eval — Couverture et lacunes

## Ce qui est couvert

### Mock eval (backend pur, sans LLM)

12 checks déterministes, exécutés en CI via pytest :

| Check | Ce qui est vérifié |
|---|---|
| `upload_ecotaxa_creates_data_understanding` | Un upload EcoTaxa crée bien un artifact DU en état `draft` |
| `analyse_blocked_before_active_artifacts` | Le bouton Analyser est inaccessible tant qu'aucun artifact actif |
| `graph_context_without_data_understanding_version_is_blocked` | Un GC sans `data_understanding_version_id` est rejeté |
| `phase_gate_blocks_graph_context_before_data_understanding_confirmation` | Créer un GC avant confirmation du DU est bloqué |
| `plan_ready_button_not_emitted_before_minimum_turns` | `[PLAN_READY]` ne peut pas apparaître avant le minimum de tours |
| `backend_phase_gate_blocks_premature_plan_ready_button` | Le backend supprime le bouton Analyser même si le LLM émet `[PLAN_READY]` trop tôt |
| `data_understanding_confirmation_activates_artifact` | La confirmation utilisateur active bien le DU |
| `graph_context_draft_links_to_active_du` | Le draft GC référence le bon `version_id` du DU actif |
| `plan_ready_after_graph_context_activation` | `[PLAN_READY]` déclenche le passage en mode Analyse |
| `upload_in_analyse_creates_draft_without_replan` | Un re-upload en mode Analyse crée un nouveau draft sans reset complet |
| `analyse_blocked_when_graph_context_references_stale_data_understanding` | Un GC lié à un DU périmé est bloqué |
| `artifact_debug_routes_are_copepod_only` | Les routes debug artifacts sont restreintes à `agent_type=copepod` |

### Live eval (LLM réel, via `LLM_MODEL`)

13 checks automatiques par run, organisés en 3 phases :

**Phase 1 — Data Understanding**

| Check | Ce qui est vérifié |
|---|---|
| `live_llm_created_data_understanding_draft` | Le LLM crée un artifact DU `draft` en phase 1 |
| `live_llm_waited_for_data_understanding_confirmation` | Le LLM s'arrête et attend avant d'activer ou de passer à la phase 2 |
| `live_describe_column_covered_all_unmatched` | `describe_column` appelé au moins autant de fois qu'il y a de colonnes `unmatched` |
| `live_phase1_efficient` | Phase 1 complétée en ≤ 10 rounds (détecte les boucles séquentielles) |
| `live_du_payload_has_column_catalogue` | L'artifact DU contient un `column_catalogue` non vide (RAG utilisé) |

**Phase 2 — Graph Context**

| Check | Ce qui est vérifié |
|---|---|
| `live_llm_activated_data_understanding` | Le LLM active bien le DU après confirmation |
| `live_llm_created_graph_context_draft_linked_to_active_du` | Le draft GC référence le `version_id` du DU actif |
| `live_llm_did_not_emit_plan_ready_before_graph_context_confirmation` | Pas de `[PLAN_READY]` dans le texte avant confirmation du GC |
| `live_backend_blocked_premature_plan_ready_button` | Le bouton Analyser reste absent même si le LLM dérive |
| `live_llm_waited_for_graph_context_confirmation` | Le GC n'est pas activé avant confirmation |
| `live_gc_payload_has_all_required_fields` | L'artifact GC contient tous les champs obligatoires |

**Phase 3 — Plan Ready**

| Check | Ce qui est vérifié |
|---|---|
| `live_llm_activated_graph_context` | Le LLM active bien le GC après confirmation |
| `live_plan_ready_enables_analyse_mode` | `[PLAN_READY]` dans le texte → bouton SSE → `/session/mode` HTTP 200 |

---

## Ce qui manque

### Qualité scientifique des artifacts (non couverte)

- Les rôles de colonnes assignés par le LLM sont-ils corrects ? (`depth` bien identifiée comme `depth`, `taxon` comme `taxon`, etc.)
- Le `column_catalogue` contient-il les bonnes définitions RAG, ou des hallucinations ?
- L'objectif du Graph Context est-il scientifiquement cohérent avec les données du DU ?
- Les `blockers` sont-ils pertinents et actionnables ?
- L'évaluation de `feasibility` (`exploratory` / `blocked`) est-elle juste ?

→ Nécessite annotation humaine ou LLM-as-a-judge calibré.

### Cas d'erreur sur les données (non couverts)

- Fichier corrompu ou format inconnu → le LLM gère-t-il l'erreur sans crasher ?
- Fichier non-EcoTaxa (CSV générique, données labo) → source type correctement inféré ?
- Colonnes entièrement nulles ou constantes → signalées dans le DU ?
- Fichier très petit (< 10 lignes) ou très grand (> 10k lignes) → comportement stable ?

### Scénarios multi-turn (non couverts)

- L'utilisateur modifie sa demande après avoir vu le DU draft (demande de correction)
- L'utilisateur rejette le DU et demande une nouvelle analyse
- L'utilisateur charge un deuxième fichier après avoir confirmé le DU
- Messages ambigus ou hors-sujet pendant le workflow (non-confirmation, question de côté)

### Robustesse du modèle (non couverte)

- Le LLM reçoit un résultat d'outil avec `blocking_reason` — stoppe-t-il correctement ?
- Le LLM ignore-t-il un `error` dans le résultat d'outil ou le reporte-t-il à l'utilisateur ?
- `describe_column` appelé pour les **bonnes** colonnes (celles dans `unmatched_columns`) — pas seulement le bon nombre
- Hallucination de noms de colonnes inexistants dans l'artifact DU

### Couverture multi-modèle (non couverte)

- La suite teste uniquement le modèle sélectionné par `LLM_MODEL` pour le run courant.
- Régression détectée entre deux versions du même modèle ?

### Intégration end-to-end (non couverte)

- Le workflow via l'interface web (WebSocket + SSE + bouton Analyser) sans eval script
- La persistance des artifacts entre redémarrages du serveur (Redis TTL)
- Le passage réel en mode Analyse après `[PLAN_READY]` (la suite actuelle vérifie HTTP 200 mais pas ce que le mode Analyse fait ensuite)
