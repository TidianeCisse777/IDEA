# Copepod GC-Only Live Eval

## Objectif

Cette suite valide uniquement la phase **Graph Context** quand le **Data Understanding** est déjà actif.

Le but n'est pas de re-tester la compréhension du dataset. Le DU est considéré comme acquis. La suite vérifie que le modèle:

- attend le contexte scientifique du user avant de figer un GC;
- pose des questions ciblées quand le contexte est incomplet;
- enrichit le contexte à partir des réponses utilisateur;
- refuse de passer directement en Analyse Mode tant que le GC n'est pas validé;
- n'ouvre jamais une nouvelle Phase 1.

## Positionnement

Cette suite se lance après:

- un DU déjà validé et actif;
- une session en Plan Mode;
- un contexte de fichiers suffisamment riche pour permettre une construction de GC réaliste.

Elle ne remplace pas:

- `--mock`;
- `--live-du-only`;
- `--live`.

Elle complète ces modes en testant le verrou scientifique entre le DU et l'Analyse.

## Principe de test

Le runner GC-only injecte un DU actif dans le `session_store`, puis observe comment le modèle construit le Graph Context à partir d'un contexte utilisateur plus ou moins complet.

Le runner doit vérifier:

1. `get_active_data_understanding(session_key)` retourne un DU actif;
2. le modèle lit ce DU au lieu de réinventer la Phase 1;
3. le modèle demande les champs GC manquants un par un;
4. `create_graph_context_draft(session_key, artifact)` est appelé uniquement quand les champs requis sont connus;
5. `activate_graph_context(session_key, version_id)` n'arrive qu'après confirmation utilisateur;
6. `[PLAN_READY]` n'apparaît qu'après activation du GC.

## Cas de test

La suite doit couvrir plusieurs profils d'entrée, pas seulement le happy path.

### 1. Contexte riche

Le user fournit un objectif clair, des colonnes, des unités et un type de graphe.

Attendus:

- le modèle construit directement un GC draft;
- il ne réouvre pas la Phase 1;
- il attend la confirmation;
- il active ensuite le GC;
- `[PLAN_READY]` est émis seulement après activation.

### 2. Contexte pauvre

Le user donne une intention partielle, mais il manque au moins un champ obligatoire.

Attendus:

- le modèle pose une seule question ciblée;
- il ne crée pas de GC draft trop tôt;
- il n'invente pas les champs manquants;
- il ne passe pas en Analyse.

### 3. Contexte hors sujet

Le user parle autour du sujet, mais ne fournit pas assez d'information pour figer le GC.

Attendus:

- le modèle recentre la discussion;
- il demande le contexte manquant avec une question courte et ciblée;
- il ne se présente pas à nouveau;
- il ne retourne pas en DU;
- il ne saute pas en Analyse.

### 4. Demande de saut vers Analyse

Le user demande directement du code, un graphique ou un passage en Analyse alors que le GC n'est pas encore validé.

Attendus:

- refus explicite en Plan Mode;
- rappel qu'il faut d'abord cadrer le contexte;
- aucune génération de code;
- aucun `[PLAN_READY]` prématuré.

### 5. Contexte multi-fichiers

Le DU actif couvre plusieurs fichiers CSV/TSV.

Attendus:

- le modèle comprend qu'il faut peut-être une sélection ou un couplage;
- il demande la stratégie si elle manque;
- il ne suppose pas un couplage sans base solide;
- il attend un contexte explicite avant de figer le GC.

### 6. Unités ambiguës

L'objectif est clair mais les unités de sortie ne le sont pas.

Attendus:

- une seule question ciblée sur les unités;
- pas d'invention;
- pas de draft GC final tant que l'ambiguïté reste bloquante.

### 7. Type de graphe ambigu

L'objectif est clair mais le type de graphe ne l'est pas.

Attendus:

- une seule question ciblée sur le graphe;
- pas de création prématurée du GC;
- pas de retour en Phase 1.

### 8. Correction du contexte

Le user corrige seulement l'objectif, les colonnes ou les filtres du GC.

Attendus:

- le runner réutilise le DU actif;
- il re-draft uniquement le GC;
- il ne repart pas en Phase 1.

### 9. Question mixte

Le user confirme partiellement le contexte et pose une question scientifique.

Attendus:

- le modèle continue la construction du GC;
- il répond brièvement à la question scientifique sans casser le workflow;
- il n'ouvre pas de nouvelle Phase 1.

## Scores attendus

Le GC-only live doit tracer au minimum:

- `gc_only_uses_active_data_understanding`
- `gc_only_waited_for_user_scientific_context`
- `gc_only_asked_single_targeted_question_when_missing_fields`
- `gc_only_created_graph_context_draft`
- `gc_only_activated_graph_context`
- `gc_only_plan_ready_after_gc_activation`
- `gc_only_refused_direct_analysis_request_before_gc`
- `gc_only_never_reopened_phase1`
- `gc_only_no_internal_terms_in_llm_text`

Selon le scénario, on peut ajouter:

- `gc_only_preserves_multi_turn_context_corrections`

## Critères de réussite

La suite est considérée comme saine si:

- le DU actif est utilisé comme source technique;
- le GC n'est créé que lorsque le contexte est suffisant;
- les questions sont ciblées et minimales;
- le modèle refuse les sauts directs en Analyse;
- le backend bloque toute tentative de dérive;
- `[PLAN_READY]` n'est émis qu'après activation du GC.

## Hors périmètre

Cette suite ne valide pas:

- l'exactitude scientifique finale du graphique;
- la qualité du code généré en Analyse Mode;
- la reconstruction du DU;
- la boucle `inspect_file -> summarize_understanding`.

## Implémentation attendue

Le runner devra suivre la même architecture que les autres evals:

- même `session_store`;
- même gestion de trace Langfuse;
- même style de log local;
- même structure `mock / live-du-only / live / trace-smoke`;
- un mode dédié `--live-gc-only`.

Le runner devra partir d'un DU actif injecté dans la session avant le premier message utilisateur du GC-only.
