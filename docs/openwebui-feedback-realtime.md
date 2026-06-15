# Open WebUI feedback en temps réel

Le dépôt contient un bridge navigateur qui intercepte le `POST /api/v1/evaluations/feedback`
d'Open WebUI et le renvoie immédiatement vers le backend `POST /feedback`, qui pousse ensuite le
feedback dans LangSmith.

## Fichier

- `openwebui/feedback_tap.js`

## Usage rapide

Dans la console du navigateur sur Open WebUI:

```js
OpenWebUIFeedbackTap.installOpenWebUIFeedbackTap({
  backendBaseUrl: "http://localhost:8000",
});
```

Si ton backend tourne ailleurs, remplace l'URL. Le patch reste non bloquant:
le clic feedback continue de fonctionner dans Open WebUI, et le push LangSmith part en parallèle.

## Vérification

Après un clic sur 👍 ou 👎:

1. Open WebUI enregistre le feedback.
2. Le bridge navigateur le duplique vers le backend.
3. Le backend l'attache au `run_id` courant.
4. Le feedback apparaît dans LangSmith sur la trace correspondante.
