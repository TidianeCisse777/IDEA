# LangGraph Context Middleware Design

## Objectif

Rendre effectifs `MAX_CONTEXT_TOKENS` et `MAX_TOOL_RESULT_CHARS` sur la requête
réellement envoyée au modèle, sans détruire l'historique persistant du thread.
L'audit de contexte doit décrire les messages vus par le modèle, pas un résultat
intermédiaire ensuite annulé par le reducer LangGraph.

## Défaut actuel

`_make_context_hook` retourne une liste réduite depuis `before_model`, mais le
reducer `add_messages` la fusionne avec l'état existant. Le modèle reçoit donc
l'historique complet alors que l'audit annonce des messages et tokens supprimés.
Le hook contient aussi une ancienne injection mémoire qui ne cible pas le vrai
system prompt et duplique le chemin sync/async fonctionnel du middleware.

## Architecture retenue

`_ContextMiddleware` devient l'unique module de préparation de la requête modèle.
Dans `wrap_model_call` et `awrap_model_call`, il :

1. lit les messages de `ModelRequest` ;
2. réarme le garde de qualité graphique au début d'un tour utilisateur ;
3. tronque les contenus de `ToolMessage` trop longs ;
4. conserve le suffixe récent sous le budget de contexte, à partir d'un message
   humain afin de ne pas créer de résultat d'outil orphelin ;
5. injecte les mémoires du store runtime dans le system prompt ;
6. remplace uniquement `request.messages` et `request.system_message` avant
   l'appel du handler ;
7. enregistre les métriques de cette requête préparée.

Le state LangGraph et ses checkpoints ne sont pas modifiés par le trim. Ils
restent la source complète pour les tours futurs et les diagnostics.

Si le dernier tour complet dépasse à lui seul le budget, le module privilégie
un historique valide : il conserve ce tour complet après troncature des résultats
d'outils et rend le dépassement visible dans l'audit.

## Invariants

- Le modèle ne voit pas les anciens tours retirés par le trim.
- Un `ToolMessage` envoyé au modèle possède toujours son `AIMessage.tool_calls`
  correspondant dans la requête préparée.
- Les checkpoints conservent l'historique complet.
- La mémoire utilise exclusivement le store runtime, en sync comme en async.
- `messages_after_trim` et `approx_tokens_after_trim` correspondent aux messages
  réellement passés au handler.
- Les clés d'audit existantes restent disponibles pour `/debug/context-audit`.

## Tests TDD

Un spy model reçoit un ancien tour volumineux puis un tour récent contenant un
appel d'outil et son résultat. Avec une petite limite, le test vérifie que :

- l'ancien tour n'est pas vu par le modèle ;
- la paire appel/résultat récente est complète ;
- le résultat d'outil est réellement tronqué ;
- l'audit correspond au nombre et au volume des messages observés ;
- le state checkpointé contient encore les messages anciens.

Les tests mémoire sync, async et no-op existants restent verts.

## Hors périmètre

- Résumé génératif de l'historique.
- Modification du system prompt métier.
- Changement du checkpointer ou du store long terme.
- Sélection dynamique des tools.
