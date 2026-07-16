# Guide E2E — comportement de l’agent IDEA

## Objectif

Évaluer l’agent comme un utilisateur réel, un tour à la fois, avec un `curl` par instruction. Le but n’est pas seulement de vérifier la réponse finale : chaque tour doit montrer ce que le modèle a reçu, les tools et skills visibles, les appels réellement effectués, l’état actif et le coût en tokens.

Ce protocole est manuel et séquentiel : aucun scénario suivant n’est lancé sans validation du tour courant.

## Règles d’exécution

1. Démarrer chaque scénario avec un `CHAT_ID` et un `USER_ID` nouveaux.
2. Garder les mêmes identifiants pour tous les tours d’un même scénario.
3. Envoyer uniquement le nouveau message utilisateur à chaque `curl`; le checkpointer conserve la conversation.
4. Observer le flux SSE et le harness en parallèle.
5. Après chaque tour, consigner les faits avant de poursuivre.
6. Arrêter immédiatement le scénario dès qu’une source, un dataset ou un tool incorrect est choisi.
7. Ne jamais corriger le prompt utilisateur pour aider l’agent : le scénario doit rester naturel.

## Préparation d’une session

```bash
export BASE_URL=http://localhost:8000
export USER_ID=e2e-agent-user
export CHAT_ID=e2e-agent-$(date +%Y%m%d-%H%M%S)
export THREAD_ID=$(printf '%s' "$USER_ID:$CHAT_ID" | md5 | cut -c1-16)

curl -sS "$BASE_URL/"
curl -sS "$BASE_URL/debug/harness-trace?thread_id=$THREAD_ID" | jq .
```

Le `THREAD_ID` est constitué des **16 premiers caractères** du MD5 de `USER_ID:CHAT_ID`. Une trace vide après un tour signifie d’abord qu’il faut vérifier cette dérivation et que la requête utilise exactement les mêmes headers.

## Commande d’un tour

Remplacer seulement la valeur de `PROMPT` entre deux tours.

```bash
export PROMPT='Charge le fichier tests/fixtures/source_enrichment_stations.csv.'

jq -n \
  --arg prompt "$PROMPT" \
  --arg chat_id "$CHAT_ID" \
  '{
    model: "copepod-agent",
    stream: true,
    chat_id: $chat_id,
    messages: [{role: "user", content: $prompt}]
  }' |
curl -N -sS --max-time 600 \
  -X POST "$BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -H "X-OpenWebUI-Chat-Id: $CHAT_ID" \
  -H "X-OpenWebUI-User-Id: $USER_ID" \
  --data-binary @- |
tee "logs/e2e-${CHAT_ID}.sse"
```

## Observation du harness

Pendant un tool long, lancer ceci dans un second terminal et interrompre avec `Ctrl-C` après la réponse :

```bash
while true; do
  clear
  date
  curl -sS "$BASE_URL/debug/harness-trace?thread_id=$THREAD_ID" |
    jq '{thread_id, trace, latest_context}'
  sleep 1
done
```

Après le tour, archiver la trace complète :

```bash
curl -sS "$BASE_URL/debug/harness-trace?thread_id=$THREAD_ID" |
  jq . > "logs/e2e-${CHAT_ID}-trace.json"
```

## Fiche de contrôle par tour

Pour chaque instruction, relever :

| Champ | Contrôle |
|---|---|
| Intention | Reformulation courte de la demande réelle |
| Réponse | Résultat exact, sans accepter une réponse seulement plausible |
| Appels modèle | Nombre et ordre des appels |
| Tokens | Estimation par appel, usage provider final, cache et total cumulatif lorsqu’il est disponible |
| Tools exposés | Nombre, noms et familles vus à chaque appel modèle |
| Tools appelés | Nom, arguments, statut, durée et résultat abrégé |
| Skills | Skill chargé, source locale/Hub, version, SHA et budget |
| Source active | Source autorisée et source réellement utilisée |
| Dataset actif | Variable avant/après et provenance |
| Contexte | Messages supprimés, résultats tronqués et dépassement de budget |
| Verdict | PASS, FAIL ou BLOCKED avec une seule cause factuelle |

Ne pas déduire un total provider absent. Dans ce cas, conserver les estimations par appel et l’usage du dernier appel SSE, puis noter `provider_cumulative_missing`.

## Critères globaux

Un tour passe seulement si :

- le résultat répond à l’intention exprimée;
- la bonne source et le bon dataset sont utilisés;
- aucun tool source inutile n’est exposé ou appelé;
- un enrichissement explicite appelle la famille d’enrichissement demandée;
- une zone géographique explicite déclenche les capacités géographiques disponibles pour la source active;
- aucune valeur scientifique n’est inventée;
- une opération lourde demande confirmation avant exécution;
- la réponse n’expose pas les noms internes des tools;
- le harness contient assez d’information pour expliquer la trajectoire.

## Ordre recommandé des scénarios

### S0 — Smoke du harness

But : valider l’observation avant de tester le comportement.

1. `Charge le fichier tests/fixtures/source_enrichment_stations.csv.`
2. Vérifier `load_file`, 3 lignes × 5 colonnes et la variable persistante.
3. Vérifier que la trace contient au moins deux appels modèle, les tools exposés et l’appel `load_file` terminé.

Si la trace est vide ou non reliée à la session, arrêter ici.

### S1 — Géographie sur fichier local

1. `Charge le fichier data/demo/neolabs_taxonomy_2014_2020.tsv.`
2. `Affiche toutes les stations présentes dans la mer du Labrador sur une carte.`
3. `Fais la même chose dans la baie de Baffin.`
4. `Modifie cette carte : affiche dans la légende le nombre de casts dans chaque station.`
5. `Fais la même chose dans la baie d’Hudson.`

Attendu : détection sémantique de la zone, filtrage du dataset actif, carte fondée sur le sous-ensemble exact et absence d’appel EcoTaxa/EcoPart.

### S2 — Géographie sur EcoTaxa

1. `Dans EcoTaxa, liste les samples de la baie de Baffin.`
2. Vérifier la source et les limites géographiques réellement appliquées.
3. `Exporte cette sélection.`
4. Vérifier qu’un plan et une confirmation sont demandés.
5. `Je confirme cet export.`

Attendu : la zone est résolue sans regex métier, la sélection exportée est celle affichée et aucun export lourd ne part avant confirmation.

### S3 — Enrichissement Amundsen

1. Charger un petit fichier contenant coordonnées, date et profondeur.
2. `Enrichis ce sample avec Amundsen.`

Attendu : chargement du skill Amundsen si nécessaire, appel d’enrichissement — pas une simple requête catalogue — conservation de la table active et couverture exacte.

### S4 — Enrichissement Bio-ORACLE

Dans une nouvelle session :

1. Charger le même petit fichier.
2. `Enrichis ce sample avec Bio-ORACLE baseline.`

Attendu : enrichissement ligne par ligne à partir des coordonnées, paramètres manquants demandés seulement s’ils sont réellement nécessaires, provenance et couverture exactes.

### S5 — Enrichissement EcoPart

1. Rechercher puis exporter un petit sous-ensemble EcoTaxa connu.
2. `Enrichis ce dataset avec EcoPart.`
3. Confirmer uniquement si le dry-run identifie un volume ou une opération lourde.

Attendu : jointure/enrichissement EcoPart sur le dataset actif, pas une exploration indépendante d’EcoPart, avec clés et couverture rapportées.

### S6 — Affinité et changement de source

1. Charger un fichier.
2. Effectuer un enrichissement explicite.
3. Demander une analyse sans renommer la source.
4. Demander ensuite explicitement une autre source.

Attendu : la demande implicite reste sur le dataset enrichi actif; la mention explicite suivante change proprement de famille sans être bloquée par l’affinité précédente.

### S7 — Tools inutiles

Dans une nouvelle session :

1. `Quelles colonnes sont nécessaires pour enrichir un fichier avec Amundsen ?`
2. `Quel fichier ai-je chargé ?`
3. `Résume ce que nous avons fait.`

Attendu : aucun téléchargement, enrichissement, export ou calcul lourd. Les capacités disponibles ne doivent pas devenir des actions sans intention utilisateur claire.

## Format du rapport de défaut

Créer un défaut par dérive, jamais un défaut global vague :

```markdown
## E2E-XXX — titre factuel

- Scénario / tour :
- Session (`CHAT_ID`, `THREAD_ID`) :
- Prompt exact :
- Attendu :
- Observé :
- Tools exposés :
- Tools appelés et arguments :
- Skills chargés et provenance :
- Tokens / troncatures :
- Source et dataset réellement utilisés :
- Première décision incorrecte :
- Artefacts : fichier SSE, trace JSON, image ou export
- Sévérité : bloquant / majeur / mineur
```

La « première décision incorrecte » est le point principal du diagnostic : exposition erronée, mauvais routage, mauvais argument, état périmé, résultat tool ou formulation finale.

## Fin d’une session

Le scénario est terminé lorsque tous ses tours sont documentés ou à la première dérive bloquante. Conserver ensemble :

- le flux SSE brut;
- la trace JSON du harness;
- les images et exports produits;
- la fiche de contrôle par tour;
- les défauts séparés par cause.

Ne pas réutiliser la session pour le scénario suivant.
