# Baseline du harness IDEA — 15 juillet 2026

## Statut

L'étape 0 du plan de renforcement est terminée. Cette baseline constitue le point de comparaison « avant modifications » pour le system prompt, les skills, les descriptions de tools et le control plane du runtime.

Deux pistes sont conservées :

- **offline déterministe** : fixtures scriptées, prompt et schémas mesurés depuis le code courant, aucun appel modèle ;
- **live** : 5 répétitions de chacun des 3 scénarios avec `openai/gpt-5.4-mini` via OpenRouter.

Artefacts :

- `evals/baseline_offline_2026-07-15.json`
- `evals/baseline_live_2026-07-15.json`
- `evals/scenarios/harness_reference.json`
- `evals/replay_harness.py`

## Conditions du benchmark live

| Élément | Valeur |
|---|---:|
| Scénarios | 3 |
| Répétitions par scénario | 5 |
| Runs complets | 15 / 15 |
| Tours observés | 60 |
| Modèle | `openai/gpt-5.4-mini` |
| Provider | OpenRouter |
| Tracing LangSmith | désactivé |
| Store/checkpointer | répertoires jetables isolés |
| Reprise | sauvegarde atomique après chaque run complet |

Le provider n'a pas renvoyé de coût monétaire exploitable. `cost_usd: null` signifie **coût non disponible**, pas coût nul.

## Résultats globaux

| Métrique | Baseline live |
|---|---:|
| Invariants niveau 1 | 60 / 60 — 100 % |
| Trajectoires niveau 2 | 49 / 60 — 81,7 % |
| `SC-LAB` — bon fichier/sous-ensemble sur les tours qui doivent le lire | 17 / 25 — 68 % |
| Tools appelés par tour | 1,70 |
| Tools exposés par tour | 41,58 |
| Tokens fixes par requête | 33 654 |
| Tokens d'entrée cumulés | 2 144 850 |
| Tokens de sortie cumulés | 25 054 |

Les 33 654 tokens fixes se décomposent en environ 6 388 tokens de system prompt et 27 266 tokens de schémas de tools. Selon le scope courant, le modèle a vu soit 27 tools, soit les 62 tools du catalogue configuré. La moyenne de 41,58 reste très supérieure à la cible de 15 tools par tour.

Le niveau 1 couvre ici les interdictions déclarées dans les fixtures et l'isolation du replay. Il ne faut pas l'interpréter comme une preuve que toutes les politiques de sécurité du futur `ToolGuardMiddleware` sont déjà garanties.

## Résultats par scénario

### `SC-LAB` — fichier TSV, Baffin puis Labrador

- Niveau 1 : **35 / 35**.
- Niveau 2 : **31 / 35**.
- Bon fichier et bon sous-ensemble lorsqu'une lecture est attendue : **17 / 25**.
- Aucun appel EcoTaxa/EcoPart interdit observé.

Défaillances significatives :

- 2 runs sur 5 ont produit le tour `labrador_color_taxa` alors que le dataset actif restait filtré sur la baie de Baffin ;
- 1 run a produit les tours Baffin puis Labrador depuis le fichier brut sans matérialiser le sous-ensemble géographique attendu ;
- 3 runs n'ont exécuté aucune action pour `add_coast` ;
- 1 run n'a exécuté aucune action pour `labrador_positions_tsv`.

Conclusion : le filtre de famille de tools empêche la dérive EcoTaxa, mais ne garantit pas que le **bon dérivé de zone** est utilisé ni que la consigne TSV-only devient un verrou de session exécutable.

### `SC-ENRICH` — Amundsen puis Bio-ORACLE

- Niveau 1 : **15 / 15**.
- Niveau 2 : **10 / 15**.
- Bio-ORACLE a matérialisé un dataset enrichi dans 5 / 5 runs.
- Amundsen a seulement appelé `find_amundsen_data_for_table` dans 5 / 5 runs ; le dataset actif est resté le fichier local.

Conclusion : la source Amundsen est correctement reconnue, mais le chemin « disponibilité → confirmation → enrichissement effectif » n'aboutit pas dans ce scénario. Ce point doit être mesuré séparément du simple choix de la bonne famille de source.

### `SC-ECOTAXA` — projet explicitement demandé

- Niveau 1 : **10 / 10**.
- Niveau 2 : **8 / 10**.
- Le premier tour a utilisé EcoTaxa dans 5 / 5 runs.
- Le second tour de prévisualisation n'a appelé aucun tool dans 2 / 5 runs.

Conclusion : le routage explicite vers EcoTaxa fonctionne, mais la continuité entre deux demandes proches reste instable.

## Faiblesses du harness révélées pendant l'étape 0

Le chantier de mesure a lui-même exposé trois besoins :

1. sauvegarder après chaque run et reprendre sans doublon — désormais implémenté ;
2. distinguer la famille de source consultée du dataset réellement matérialisé ;
3. distinguer `file:path.tsv`, le fichier brut et ses dérivés géographiques.

Ces distinctions sont maintenant présentes dans les graders. Les 60 tours live n'ont pas été rejoués pour corriger les scores : les métriques ont été recalculées localement depuis les observations sauvegardées.

## Priorités concrètes pour la suite

La baseline justifie l'ordre suivant :

1. **Étape 1 — tests rouges versionnés** : transformer les failles de sécurité et de cohérence déjà auditées en contrats exécutables ;
2. **Étape 2A — registre déclaratif** : réduire les divergences entre catalogue, politiques et documentation ;
3. **Étape 3 — politique de source** : séparer explicitement famille de source, fichier canonique et dérivé actif ;
4. **Étape 5 — `TurnContext`** : rendre persistants `source_lock`, dataset canonique et carte des dérivés ;
5. **Étape 6 — filtrage dynamique** : passer de 27/62 tools visibles à une cible ≤ 15 sans dégrader les taux ci-dessus.

La prochaine action est l'étape 1. Aucun changement de comportement runtime n'a été introduit pendant l'étape 0.

## Mesure de clôture de l'étape 2

La baseline offline a été régénérée une seule fois après la migration complète avec :

```bash
python -m evals.replay_harness --lane offline --runs 1 --output evals/baseline_offline_2026-07-15.json
```

| Métrique offline | Avant étape 2 | Après étape 2 |
|---|---:|---:|
| Invariants niveau 1 | 100 % | 100 % |
| Trajectoires niveau 2 | 100 % | 100 % |
| `SC-LAB` — bon fichier | 100 % | 100 % |
| Tools exposés par tour | 62 | 62 |
| Tools appelés par tour | 1,17 | 1,17 |
| Tokens fixes | 33 654 | 24 392 |

La trajectoire déterministe reste identique et les appels offline portent désormais un résultat structuré validable. La baisse de 9 262 tokens fixes (−27,5 %) vient de la représentation actuelle du prompt et des schémas; elle ne constitue pas encore le filtrage dynamique prévu à l'étape 6. Aucun benchmark live ni appel OpenRouter n'a été relancé pour clôturer l'étape 2.

Gate de code : `1089 passed, 20 skipped, 6 xfailed` sur `pytest -q tests/`. Les skips sont les intégrations opt-in EcoTaxa/PostgreSQL; les six `xfail` sont les contrats red-team appartenant aux étapes suivantes.
