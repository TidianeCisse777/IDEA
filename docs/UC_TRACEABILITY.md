# UC_TRACEABILITY.md — Ancrage des UC et contraintes dans IDEA

Mappe les **14 UC** et **29 contraintes** du PRD V1.2 (`assistant-copepodes-specs/docs/PRD_IDEA_copepod.md`) sur leur point d'implémentation côté runtime IDEA.

Statut :
- ✅ implémenté et testé
- 🟡 implémenté partiellement, à compléter
- ⏳ pas encore implémenté
- ⛔ hors périmètre de l'agent (plateforme)

---

## Use Cases

| UC | Titre | Statut | Implémentation |
|---|---|---|---|
| UC-00 | S'inscrire | ⛔ | Open WebUI (plateforme) |
| UC-01 | Se connecter | ⛔ | Open WebUI (plateforme) |
| UC-02 | Charger des données | ✅ | `tools/data_tools.py::load_file` + `agents/skills/uvp_ecotaxa.md`, `uvp_ecopart.md` pour les exports UVP |
| UC-03 | Interroger une source en ligne | ✅ | `tools/copepod_sources.py`, `tools/ecopart_sources.py`, `tools/amundsen_sources.py`, `tools/bio_oracle_sources.py`. Flow découverte → preview → query imposé par le system prompt |
| UC-04 | Valider les données chargées | ✅ | `load_file` retourne aperçu colonnes/types/manquants ; `preview_sql_table` pour SQL |
| UC-05 | Nettoyer les données | 🟡 | `run_pandas` sur copies. Pas de tool dédié — règle « copie nommée » dictée par le system prompt et CT-AG-10 |
| UC-06 | Générer un graphique | ✅ | `load_skill("graph_planner")` → `load_skill("graph_writer")` → `run_graph` ou `run_pandas` |
| UC-07 | Distribution verticale | ✅ | `join_ecotaxa_ecopart` + `graph_planner`/`graph_writer` |
| UC-08 | Distribution spatio-temporelle | ✅ | `graph_planner`/`graph_writer` sur données chargées |
| UC-09 | Taxonomie et stades | ✅ | `query_ecotaxa(status="V")` + skill `ecotaxa_query` ; règle inclusion/exclusion si statut absent |
| UC-10 | Variables environnementales CTD | ✅ | `query_amundsen_ctd` + `environmental_join` skill + `run_pandas` |
| UC-11 | Complétude et lacunes | 🟡 | `run_pandas` (`.isna().sum()`, `.value_counts()`). Skill dédié `data_completeness` envisagé |
| UC-12 | Calcul de variable dérivée | ✅ | `query_copepod_knowledge_base` pour méthode + `run_pandas` |
| UC-13 | Exporter le résumé de session | 🟡 | Sortie texte de l'agent ; pas de tool dédié `export_session_summary` — c'est une compilation par le LLM |
| UC-14 | Préparer un livrable scientifique | ✅ | `load_skill("deliverable_writer")` + `export_deliverable` (WeasyPrint PDF) |

---

## Contraintes (CT-AG-01 à CT-AG-29)

Notation :
- **Prompt** = règle portée par `agents/copepod_system_prompt.py`
- **Tool** = règle portée par le code d'un tool
- **Runtime** = règle portée par `agent.py` ou `serve.py`

| ID | Règle (rappel court) | Statut | Porté par |
|---|---|---|---|
| CT-AG-01 | Citer la source de données | ✅ | Prompt + chaque skill `*_query` |
| CT-AG-02 | Aucune valeur absente complétée par supposition | ✅ | Prompt |
| CT-AG-03 | Résultat qualifié (fiable/exploratoire/impossible) | 🟡 | Prompt — qualification implicite via blocages |
| CT-AG-04 | Pas d'analyse sans contexte validé | ✅ | Prompt (clarification ciblée) + `graph_planner` skill |
| CT-AG-05 | Colonnes requises vérifiées avant calcul | ✅ | Prompt + `graph_planner` |
| CT-AG-06 | Méthode annoncée + **validation utilisateur** avant exécution lourde | ✅ | Prompt § « Confirmation before heavy operations » — liste des tools nécessitant un « oui/go/lance/confirme » explicite ; opérations légères restent immédiates |
| CT-AG-07 | Jointures documentées | ✅ | Skill `environmental_join` + `join_ecotaxa_ecopart` |
| CT-AG-08 | Communiquer ce que chaque source permet | ✅ | Prompt + skills `*_query` + RAG `sources_en_ligne.md` |
| CT-AG-09 | Code traçable, visible, erreurs expliquées | ✅ | Tool `run_pandas`/`run_graph` retournent stdout + erreur ; LangSmith trace |
| CT-AG-10 | Données brutes jamais modifiées | ✅ | Prompt + `load_file` (lecture seule), `copy_sql_query_to_workspace` |
| CT-AG-11 | Aucun credential affiché | ✅ | Prompt (Security section) |
| CT-AG-12 | Téléchargements proportionnés | 🟡 | Prompt + le flow list/preview/query oblige à passer par preview |
| CT-AG-13 | Aucune interprétation scientifique | ✅ | Prompt (Scope section) — refus formel |
| CT-AG-14 | Graphique avec titre, axes, unités, source, filtres, limites | ✅ | Skill `graph_writer` |
| CT-AG-15 | Pas de citation inventée | ✅ | Prompt (Citations section) |
| CT-AG-16 | Périmètre V1 limité | ✅ | Prompt (Scope) + ce document |
| CT-AG-17 | Reproductibilité (temperature=0.0) | ✅ | `agent.py` configuration LLM |
| CT-AG-18 | Réponses courtes, orientées résultat | ✅ | Prompt (Format section) |
| CT-AG-19 | Affirmation factuelle reliée à source/colonne/calcul | ✅ | Prompt + obligation `query_copepod_knowledge_base` |
| CT-AG-20 | Résultat inclut ID source, colonnes, script | ✅ | Skills `*_query` + `graph_writer` |
| CT-AG-21 | Cohérence sortie ↔ données sources | 🟡 | Vérification implicite via `run_pandas` ; pas de check formel |
| CT-AG-22 | Demande vague ne déclenche pas d'analyse | ✅ | Prompt (clarification ciblée si paramètre manquant) |
| CT-AG-23 | Vocabulaire technique et neutre — interdiction explicite de « je/moi » | ✅ | Prompt § Tone — bannit `I`, `me`, `as an AI`, fillers, politesse ; format Result/Source/Method/Limit/Next pour les résultats analytiques, réponse directe pour les questions courtes |
| CT-AG-24 | Résultats incertains visuellement distincts | ✅ | Skill `graph_writer` § Uncertainty rendering : palette confirmed/exploratory/uncertain, hatch, stamp confiance, annotation rouge si `low`. Skill `graph_planner` § étape 7 calcule les counts et le niveau de confiance |
| CT-AG-25 | Livrable soutient la rédaction du chercheur | ✅ | Skill `deliverable_writer` |
| CT-AG-26 | Distinction absence confirmée / biais / incertitude | 🟡 | RAG `methodes_calcul.md` + prompt — à formaliser dans `graph_writer` |
| CT-AG-27 | Pas de credentials EcoTaxa/EcoPart/SQL exposés | ✅ | Prompt (Security) + `.env` |
| CT-AG-28 | Pas de citation fabriquée — redirige Google Scholar / WoS | ✅ | Prompt (Citations) |
| CT-AG-29 | SQL lecture seule, résultats en copie locale | ✅ | `tools/sql_workspace.py` + skill `sql_workspace_query` |

---

## Contraintes retirées en V1.2

Ces contraintes étaient dans le PRD V1.1 mais sont supprimées car contredites ou caduques :

- **CT-AG-22 V1.1** (« pas de streaming ») → contredite : `serve.py` streame en SSE via `_stream_agent_sse`.
- **CT-AG-23 V1.1** (« Mode Contexte vs Mode Analyse ») → caduque : pas de modes dans le runtime.
- **CT-AG-24 V1.1** (« résultats en bloc, pas de streaming progressif ») → contredite : SSE actif.

Les contraintes utiles ont été renumérotées et CT-AG-27/28/29 ajoutées pour couvrir le SQL workspace et la sécurité credentials/citations.

---

## Sources de vérité

| Sujet | Où c'est défini | Où c'est appliqué |
|---|---|---|
| Identité métier de l'agent | `assistant-copepodes-specs/docs/CONTEXT.md` § Production graphique sans interprétation | `agents/copepod_system_prompt.py` § Scope |
| Liste UC | `assistant-copepodes-specs/docs/PRD_IDEA_copepod.md` § 5 | Ce document |
| Liste contraintes | `assistant-copepodes-specs/docs/PRD_IDEA_copepod.md` § 7 | Ce document + system prompt |
| Sources autorisées | `CONTEXT.md` § Sources de données + PRD § 6 | Toolset construit par `agent.py` |
| Skills | `IDEA/CONTEXT.md` § Skills | `agents/skills/*.md` + push hub via `push_skills.py` |
| RAG | `IDEA/CONTEXT.md` § Skills et RAG | `core/copepod_rag/docs/*.md` + ChromaDB |

Quand une contrainte ou un UC change : **mettre à jour le PRD d'abord** (source de vérité), puis remettre ce document à jour pour ancrer le point d'implémentation.
