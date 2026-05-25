# ADR 004 — [PLAN_READY] tag pour le switch Plan → Analyse

**Status:** Accepted — 2026-05-25

Quand le LLM a complété le Graph Context et obtenu la confirmation de l'utilisateur, il émet le tag `[PLAN_READY]` à la fin de sa réponse. Le backend détecte ce tag, le retire du texte affiché, et envoie un chunk `action_button` au frontend. Le frontend affiche un bouton [Valider] dans la conversation. Quand l'utilisateur clique, le mode de session passe à `analyse` dans Redis (`session_mode:{user_id}:{session_id}:copepod`), et le `CopepodProfile` n'injecte plus que `copepod_mode_analyse`.

## Alternatives considérées

**Pattern detection** : le backend parse la réponse du LLM à la recherche de `### Graph Context` et injecte automatiquement le bouton. Rejeté — fragile si le LLM reformule le titre de section, et ne capture pas le moment où l'utilisateur a confirmé (le LLM peut produire le Graph Context sans que l'utilisateur ait validé).

**Tool call** : le LLM appelle `request_plan_validation()` pour signaler la fin du plan. Rejeté — un tool pour déclencher de l'UI mélange les responsabilités. Les tools servent aux données et calculs, pas aux transitions d'état UI.

## Conséquences

- Le tag `[PLAN_READY]` doit être dans le system prompt — si le prompt change, le mécanisme casse silencieusement.
- Le backend doit parser le stream et strip le tag avant de le sauvegarder dans l'historique Redis.
- Le frontend doit gérer un nouveau type de chunk `action_button`.
