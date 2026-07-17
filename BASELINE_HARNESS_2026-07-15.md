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

## Mesure de clôture de l'étape 3

Le scénario `SC-ECOTAXA` comporte désormais un troisième tour qui ne répète pas le nom EcoTaxa. La baseline offline a été régénérée une fois après les gates.

| Métrique offline | Après étape 2 | Après étape 3 |
|---|---:|---:|
| Invariants niveau 1 | 100 % | 100 % |
| Trajectoires niveau 2 | 100 % | 100 % |
| `SC-LAB` — bon fichier | 100 % | 100 % |
| Tours | 12 | 13 |
| Tools appelés par tour | 1,17 | 1,15 |
| Tokens fixes | 24 392 | 24 477 |

Smoke agent réel unique, modèle `openai/gpt-5.4-mini`, tracing désactivé et catalogue limité aux opérations sûres :

| Tour | Demande | Tools visibles | Affinité après tour |
|---|---|---:|---|
| 1 | EcoTaxa explicitement nommé | 25 | `ecotaxa` |
| 2 | suivi sans répéter EcoTaxa | 25 | `ecotaxa` |
| 3 | chargement d'un fichier local | 3 | `file` |

Le téléchargement lourd `query_ecotaxa` était absent des trois tours. Les appels observés étaient `load_skill` + prévisualisation au tour 1, résumé read-only au tour 2 et chargement local au tour 3. Gate complet final : `1118 passed, 20 skipped, 5 xfailed`. Aucun benchmark live N ≥ 5 ni replay OpenRouter en boucle n'a été lancé.

### Smoke multi-source fichier + EcoTaxa

Un second smoke réel unique a validé la coexistence des deux sources avec le même modèle et les mêmes protections :

| Tour | Demande | Sources autorisées | Tools visibles | Appels observés |
|---|---|---|---:|---|
| 1 | charger `data/demo/ecotaxa_sample_50.tsv` | `file` | 3 | chargement local |
| 2 | comparer le fichier au projet EcoTaxa 17498 | `file`, `ecotaxa` | 25 | skill EcoTaxa, résumé read-only, analyse locale |
| 3 | continuer sans répéter les sources | `file`, `ecotaxa` | 25 | aucun nouvel appel |

Le fichier est resté la source principale aux tours 2 et 3. L'affinité multi-source a survécu au suivi, les tools EcoTaxa étaient invisibles avant leur mention explicite et `query_ecotaxa` est resté absent du catalogue sûr. Le store était isolé, le tracing désactivé et aucun fichier du dépôt n'a été modifié par le smoke.

## Mesure de clôture de l'étape 4A

La baseline offline a été régénérée une seule fois après le passage rouge/vert du contrat numérique.

| Métrique offline | Après étape 3 | Après étape 4A |
|---|---:|---:|
| Invariants niveau 1 | 100 % | 100 % |
| Trajectoires niveau 2 | 100 % | 100 % |
| `SC-LAB` — bon fichier | 100 % | 100 % |
| Tools exposés par tour | 62 | 62 |
| Tools appelés par tour | 1,15 | 1,15 |
| Tokens du system prompt | 6 473 | 6 583 |
| Tokens des schémas | 18 004 | 18 004 |
| Tokens fixes | 24 477 | 24 587 |

Le nouveau contrat coûte 110 tokens fixes. Il ne modifie ni le catalogue ni les trajectoires offline. Gate ciblé : `126 passed`. Gate complet exécuté une fois : `1123 passed, 20 skipped, 4 xfailed`.

Smoke agent réel unique, modèle `openai/gpt-5.4-mini`, tracing désactivé et store isolé :

| Tools visibles | Appels observés | Réponse | pandas | Tools lourds visibles |
|---|---|---:|---|---|
| skill, résumé EcoTaxa spécialisé, pandas | skill → résumé du projet 17498 | `64` | non appelé | aucun |

Le résultat spécialisé contenait bien une valeur numérique et son statut structuré était `success`; le smoke est donc concluant. Aucun replay live N ≥ 5 ni second smoke n'a été lancé.

## Mesure de clôture de l'étape 4B

La baseline offline a été régénérée une seule fois après le passage rouge/vert du routage graphique sémantique.

| Métrique offline | Après étape 4A | Après étape 4B |
|---|---:|---:|
| Invariants niveau 1 | 100 % | 100 % |
| Trajectoires niveau 2 | 100 % | 100 % |
| `SC-LAB` — bon fichier | 100 % | 100 % |
| Tools exposés par tour | 62 | 62 |
| Tools appelés par tour | 1,15 | 1,15 |
| Tokens du system prompt | 6 583 | 6 695 |
| Tokens des schémas | 18 004 | 18 004 |
| Tokens fixes | 24 587 | 24 699 |

Le contrat sémantique ajoute 112 tokens fixes. Il retire cependant le chargement à la demande des longs skills graphiques sur une analyse non visuelle; ce coût dynamique n'apparaît pas dans la mesure fixe du prompt. Gate canonique : `6 passed`. Régressions graphiques : `124 passed`. Gate complet exécuté une fois : `1129 passed, 20 skipped, 4 xfailed`.

### Smoke agent réel tableau → carte

Modèle `openai/gpt-5.4-mini`, tracing désactivé, store/checkpointer isolés et catalogue limité à quatre tools sûrs : chargement local, pandas, chargement de skill et rendu graphique.

| Tour | Intention | Appels observés | Statut |
|---|---|---|---|
| 1 | charger `zooplankton_demo_stations.tsv` | chargement local | succès |
| 2 | « Montre le nombre d'observations par station » | pandas uniquement | succès; aucun skill graphique |
| 3 | « Représente maintenant ces stations sur une carte » | planner → writer → rendu | succès; image produite |

La première fixture testée, `ecotaxa_sample_50.tsv`, contenait zéro latitude/longitude non nulle. Le rendu a échoué correctement avec une table spatiale vide; aucun graphique fictif n'a été annoncé. Après diagnostic local, le scénario a été corrigé avec la fixture spatiale valide ci-dessus. Aucun replay live N ≥ 5 n'a été lancé.

## Mesure de clôture de l'étape 4B.1 — garde exécutable

La baseline offline a été régénérée une fois après le correctif final de concurrence.

| Métrique offline | 4B sémantique | 4B.1 exécutable |
|---|---:|---:|
| Invariants niveau 1 | 100 % | 100 % |
| Trajectoires niveau 2 | 100 % | 100 % |
| `SC-LAB` — bon fichier | 100 % | 100 % |
| Tools exposés par tour | 62 | 62 |
| Tools appelés par tour | 1,15 | 1,15 |
| Tokens du system prompt | 6 695 | 6 719 |
| Tokens des schémas | 18 004 | 18 004 |
| Tokens fixes | 24 699 | 24 723 |

Le surcoût fixe de 24 tokens rend explicite l'interdiction de demander planner et writer dans le même lot. La contrainte forte reste dans le middleware : empreinte stable du tour, classification structurée `visual|non_visual|ambiguous`, cache single-flight sync/async et validation des ToolResults du tour courant. Gate ciblé final : `29 passed`; régression agent/data/prompt : `184 passed`; gate complet final : `1153 passed, 20 skipped, 3 xfailed`.

### Smoke agent réel adversarial tableau → carte — résultat partiel (`exit 1`)

Modèle `openai/gpt-5.4-mini`, tracing désactivé, store fichier isolé et catalogue limité aux quatre tools locaux utiles.

| Tour | Décision / compteur | Appels graphiques | Résultat |
|---|---|---|---|
| chargement | aucune classification | aucun | fichier 15 × 10 chargé |
| tableau adversarial | `non_visual/high`, 1 | planner tenté puis `blocked` | tableau de 15 stations rendu |
| carte | `visual/high`, 1 | planner `success` → writer `success` → rendu `success` | PNG produit |

Le tour carte contient un `run_pandas` intermédiaire entre planner et writer pour sélectionner les coordonnées; le contrat exige seulement que le writer précède immédiatement le rendu. Les assertions graphiques 4B.1 sont satisfaites.

La campagne globale a néanmoins terminé avec `AssertionError` et un code non nul. L'assertion en échec était l'exigence d'un appel `run_pandas: success` au tour tableau. L'agent a repris les lignes exposées par `load_file` et produit lui-même le comptage. Il s'agit d'une violation comportementale de la branche 4A « nouvelle agrégation sur une table → pandas ». Elle est désormais suivie comme dette 4A.1. Aucun replay du modèle n'a été effectué, et cette campagne ne doit pas être décrite comme entièrement verte.
