# Numeric Evidence Routing Design — étape 4A

**Date :** 15 juillet 2026
**Statut :** approuvé en conversation, en attente de revue du document
**Portée :** corriger uniquement la contradiction « tout nombre exige pandas ». Les déclencheurs graphiques et les procédures OGSL/autres sources appartiennent aux tranches 4B et 4C.

## Objectif

L'agent doit utiliser directement une valeur numérique déjà produite par un tool spécialisé. Une exécution pandas est requise seulement lorsqu'il faut calculer une nouvelle valeur depuis une table disponible. Aucun nombre ne peut être inventé lorsque les résultats disponibles ne le fournissent pas.

## Règle normative

La règle injectée dans le system prompt distingue trois cas exclusifs :

1. **Valeur fournie par un tool spécialisé** — utiliser directement la valeur et conserver sa provenance. Ne pas appeler pandas uniquement pour la reproduire.
2. **Valeur dérivée d'une table** — exécuter pandas pour toute nouvelle agrégation, transformation, métrique, sélection chiffrée, ratio ou statistique qui n'est pas déjà présente dans un résultat spécialisé.
3. **Valeur absente** — répondre « valeur inconnue » ou décrire la donnée manquante. Ne jamais estimer, compléter ou mémoriser un nombre non fourni.

## Exemples normatifs

| Demande | Résultat disponible | Route attendue |
|---|---|---|
| « Combien de taxa dans ce projet EcoTaxa ? » | `count_ecotaxa_taxa` fournit le compte | consommer le résultat spécialisé; aucun pandas |
| « Résume les 3 projets » | `summarize_ecotaxa_projects` fournit les nombres demandés | consommer le tableau spécialisé |
| « Quelle est la moyenne de profondeur dans mon fichier ? » | seulement les lignes du DataFrame sont disponibles | exécuter pandas |
| « Classe les cinq stations avec le plus d'objets » | le DataFrame est disponible, aucun classement spécialisé | exécuter pandas |
| « Quel est le ratio validés / total ? » | deux comptes spécialisés existent mais pas le ratio | exécuter le calcul contrôlé seulement si ces valeurs existent dans une table/structure persistée; sinon matérialiser les données avec le tool approprié ou déclarer la limite |
| « Donne le nombre d'objets » | aucun résultat ni dataset ne le fournit | valeur inconnue; demander la donnée nécessaire |

Un `preview_*` ou `summarize_*` n'est pas automatiquement autoritaire pour toute question numérique : seule une valeur effectivement présente dans son résultat peut être reprise directement.

Une valeur visible uniquement dans du texte de conversation ne devient pas une table calculable. Si une dérivation exige pandas mais qu'aucune structure persistée ne contient les entrées, l'agent doit d'abord obtenir ou matérialiser ces données; à défaut, il signale la limite.

## Architecture

La correction est volontairement limitée au contrat modèle :

- une constante `NUMERIC_EVIDENCE_RULES` contient le bloc canonique;
- `COPEPOD_SYSTEM_PROMPT` injecte ce bloc une seule fois;
- le bloc remplace la phrase absolue « Always call run_pandas to produce any numeric value »;
- les règles de routage existantes qui préfèrent un tool spécialisé restent inchangées;
- `ToolResult` demeure la structure de preuve (`status`, `provenance`, `method`, `metrics`).

Aucun parseur de nombres dans la réponse finale n'est ajouté. Un tel validateur exigerait une traçabilité nombre→résultat complète et appartient à un chantier ultérieur, pas à cette correction de contradiction.

## Contrats et smoke agent

Les tests déterministes doivent prouver :

- disparition exacte de l'ancienne règle absolue;
- présence des trois branches `specialized`, `derived`, `unknown`;
- le contrat red-team de l'étape 4A perd son `xfail`;
- les règles graphiques et les skills ne sont pas modifiés dans cette tranche.

Un smoke agent réel unique utilise un catalogue sûr et une demande EcoTaxa read-only dont le résultat numérique est fourni par un tool spécialisé. Le succès exige :

- source EcoTaxa explicitement autorisée;
- appel d'un tool spécialisé de comptage ou résumé;
- aucun appel `run_pandas` après ce résultat;
- aucun tool lourd visible;
- réponse finale fondée sur la valeur retournée;
- tracing désactivé et store isolé.

Si le tool spécialisé échoue ou ne renvoie pas la valeur demandée, le smoke ne doit pas être présenté comme une validation positive du contrat.

## Critères d'acceptation

1. Le test red-team numérique devient vert.
2. Les tests statiques du prompt prouvent les trois branches de décision.
3. La suite ciblée prompt/EcoTaxa reste verte.
4. La suite complète reste verte avec un `xfail` de moins.
5. Le smoke réel ne déclenche pas pandas pour recopier un nombre spécialisé.
6. La baseline offline conserve 100 % aux niveaux 1 et 2.

## Hors portée

- Détection exécutable de chaque nombre dans la réponse finale.
- Changement des schémas ou retours des 62 tools.
- Chargement conditionnel de `graph_planner` / `graph_writer`.
- Correction des procédures OGSL, EcoTaxa, EcoPart, Amundsen ou Bio-ORACLE.
- Nouvelle métrique scientifique ou interprétation biologique.
