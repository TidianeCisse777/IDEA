# Design — Remodelage du routage des sources dans le prompt et les skills

Date : 2026-07-15
Projet : IDEA · NeoLab, Université Laval

## Contexte

Le scénario E2E `cartes-samples-labrador-2026` a montré que l'agent pouvait
charger `ecotaxa_navigation` et appeler des outils EcoTaxa à partir de mots
génériques comme « samples », « positions » ou « zone », même lorsqu'un fichier
TSV était chargé et que l'utilisateur avait explicitement interdit EcoTaxa.

La cause linguistique est structurelle : le system prompt contient de nombreux
déclencheurs EcoTaxa détaillés, tandis que la précédence du fichier chargé est
exprimée dans quelques règles isolées. Une règle locale supplémentaire ne suffit
pas ; elle est noyée par la surface de routage spécialisée.

Le présent design remodèle le system prompt comme routeur minimal et déplace les
procédures spécialisées dans les skills. Il vise d'abord à réduire les risques
d'hallucination et de changement de source implicite. Les défauts distincts du
session store — perte de l'identité du fichier original et chaînage involontaire
des filtres — restent hors de ce changement et feront l'objet d'un correctif
séparé.

## Objectifs

- Faire du fichier chargé la source par défaut de toute demande générique.
- Interdire toute source externe sans mention explicite de cette source par
  l'utilisateur.
- Empêcher les mots génériques de déclencher un skill ou un outil EcoTaxa.
- Maintenir un verrou de source explicite entre les tours jusqu'à sa levée
  explicite.
- Empêcher l'annonce d'un résultat, d'une image ou d'un lien qui n'a pas été
  retourné avec succès par un outil.
- Réduire le volume et les contradictions du system prompt.
- Rendre chaque skill source-spécifique procédural plutôt que responsable de la
  détection d'intention.

## Non-objectifs

- Reconcevoir le session store ou la représentation des DataFrames.
- Corriger dans ce changement le chaînage des filtres géographiques.
- Construire immédiatement un pipeline graphique entièrement déterministe.
- Modifier les règles scientifiques, les méthodes EcoTaxa ou les contraintes de
  confirmation des opérations coûteuses.
- Ajouter un mode de session ; le runtime reste un agent ReAct unique.

## Architecture retenue

Le system prompt devient un routeur court contenant les invariants et l'arbre de
décision. Les détails de navigation, de requête et d'interprétation propres aux
sources sont conservés dans leurs skills spécialisés.

Cette architecture est préférée à :

- un prompt monolithique simplement réordonné, qui resterait long et sujet à la
  dilution des règles prioritaires ;
- un nouveau skill de routage chargé à chaque tour, qui ajouterait un appel
  systématique et laisserait au modèle la responsabilité de penser à le charger.

## Porte d'entrée unique des sources

La sélection de source est la première décision du system prompt, avant les
règles métier et graphiques.

### Un fichier est chargé

- Toute demande générique portant sur des échantillons, positions, stations,
  taxons, cartes, analyses ou zones vise le fichier chargé.
- Une source externe n'est admissible que si l'utilisateur la nomme
  explicitement dans le message courant.
- Un résultat filtré ou dérivé ne change pas implicitement l'identité de la
  source demandée.

### Aucun fichier n'est chargé

- Une demande générique ne déclenche aucune source externe.
- L'agent demande un fichier ou demande à l'utilisateur de choisir la source.
- Un identifiant générique tel que « projet 17498 » ne suffit pas à identifier
  EcoTaxa. L'utilisateur doit mentionner EcoTaxa.

### Une source externe est explicitement nommée

- Seule la source nommée et ses procédures deviennent admissibles.
- Si un fichier est chargé, il reste la source principale ; la source externe
  est secondaire et limitée à l'opération demandée.
- Cette autorisation ponctuelle ne change pas durablement le périmètre de la
  session.

### Un verrou explicite existe

- Une consigne comme « TSV seulement » ou « n'utilise jamais EcoTaxa » reste
  active entre les tours.
- Le verrou ne peut être levé que par une consigne explicite contraire, par
  exemple « utilise maintenant EcoTaxa ».
- Une citation, une mention passive ou un contenu historique ne lève pas le
  verrou.

## Signaux explicites

Une source externe est explicitement demandée seulement lorsque le message
utilisateur courant nomme cette source :

- `EcoTaxa` pour EcoTaxa ;
- `EcoPart` pour EcoPart ;
- `Amundsen CTD` pour Amundsen ;
- `Bio-ORACLE` pour Bio-ORACLE ;
- `OGSL` pour OGSL.

Les mots « projet », « sample », « échantillon », « station », « zone »,
« température », « environnement », « carte », « où » et leurs variantes ne
sont jamais des signaux de source externe.

Un lien appartenant explicitement au domaine d'une source peut compter comme
une mention de cette source. Un numéro de projet seul ne le peut pas.

## Responsabilités des skills

### `ecotaxa_navigation`

- Sa précondition d'activation apparaît en tête du document : EcoTaxa est
  explicitement demandé dans le tour courant et aucun verrou ne l'interdit.
- Il couvre uniquement les opérations EcoTaxa légères : découverte de projets,
  navigation de samples, comptages, schéma, aperçu et préparation d'export.
- Il ne contient aucun déclencheur fondé uniquement sur des termes génériques.
- Il n'est jamais chargé pour analyser un fichier local.

### `ecotaxa_query`

- Il est chargé après une demande explicite d'extraction EcoTaxa ou après un
  résultat EcoTaxa déjà établi dans le même périmètre autorisé.
- Il ne traite jamais un DataFrame local comme s'il provenait d'EcoTaxa.
- Une comparaison ponctuelle avec EcoTaxa ne remplace pas la source fichier.

### Autres sources externes

`ecopart_query`, `amundsen_ctd_query`, `bio_oracle_query` et les règles OGSL
reçoivent la même précondition explicite avec le nom de leur propre source. Les
termes métier génériques ne suffisent pas à les activer.

### Skills graphiques

- `graph_planner` travaille à partir de la variable source explicitement
  sélectionnée.
- `graph_writer` n'introduit aucune valeur, coordonnée, colonne ou identifiant
  absent de cette variable.
- Aucun skill graphique ne suggère de changer silencieusement de source pour
  combler une donnée manquante.
- Une colonne absente reste une limite ; elle n'est jamais renommée ou simulée
  pour satisfaire un contrat.

## Règles anti-hallucination

### Autorité des résultats d'outils

- Un résultat `Error`, `blocked`, une exception ou un résultat vide signifie
  que l'opération n'a pas réussi.
- L'agent ne reformule jamais cet état comme un succès total ou partiel.
- Un résultat vide est une conclusion valide et ne justifie pas un changement
  de source.

### Artefacts vérifiables

- Une image, un fichier ou une URL ne peut être annoncé que si le dernier outil
  pertinent a retourné exactement cet artefact avec succès.
- Les chemins génériques, anciens ou inventés tels que
  `sandbox:/graphs/graph.png` sont interdits.
- Un ancien artefact ne peut pas être présenté comme le résultat du tour
  courant.

### Traçabilité des données

- Toute valeur numérique provient d'un outil, d'un calcul exécuté ou du RAG
  autorisé.
- Toute valeur graphique provient de la variable explicitement choisie.
- Il est interdit de coder en dur des coordonnées, identifiants ou comptages
  issus d'une autre source.
- Une donnée manquante est signalée ; aucune source externe n'est substituée
  silencieusement.

### Résultats vides

- Lorsque le résultat de filtrage contient zéro ligne, l'agent rapporte la
  source, la méthode et la limite, puis s'arrête.
- Il ne charge pas les skills graphiques et ne tente pas de rendu.
- Il peut proposer une prochaine action, mais ne l'exécute pas en changeant de
  source sans demande explicite.

## Nouvelle structure du system prompt

Le prompt principal est organisé dans l'ordre suivant :

1. Identité et limites scientifiques.
2. Sélection de source et verrou explicite.
3. État du fichier, source originale et variables dérivées.
4. Exécution et confirmations des opérations coûteuses.
5. Vérité des résultats et artefacts.
6. Format de réponse clinique.

Les longues procédures EcoTaxa — navigation, filtres de profondeur, comptages,
exports et exemples détaillés — quittent le prompt principal et restent dans
les skills EcoTaxa. Les répétitions et règles contradictoires sont supprimées,
pas seulement déplacées dans une nouvelle section.

## Comportements attendus

| Contexte | Message | Comportement attendu |
|---|---|---|
| Fichier chargé | « samples en Baffin » | Fichier uniquement |
| Aucun fichier | « samples en Baffin » | Demander fichier ou source |
| Fichier chargé | « compare avec EcoTaxa en Baffin » | Fichier principal, EcoTaxa secondaire demandé |
| Aucun contexte source | « projet 17498 » | Demander la source ; ne pas supposer EcoTaxa |
| Verrou TSV actif | Mention passive d'EcoTaxa | Maintenir le verrou |
| Verrou TSV actif | « utilise maintenant EcoTaxa » | Lever explicitement le verrou |
| Rendu bloqué | Tool retourne `graph contract blocked` | Rapporter l'échec, aucune image |
| Filtre vide | `n_in=0` | Rapporter zéro ligne, aucun rendu |
| Colonne absente | Graphique exige une colonne manquante | Signaler la limite, aucune valeur simulée |

## Validation

### Tests statiques

- Vérifier que le system prompt n'associe plus les mots génériques aux routes
  EcoTaxa.
- Vérifier la présence de la porte d'entrée unique avant les procédures métier.
- Vérifier que chaque skill externe commence par sa précondition explicite.
- Vérifier que les exemples détaillés EcoTaxa ne sont plus dupliqués dans le
  prompt principal.
- Vérifier la présence des règles d'autorité du résultat et d'artefact exact.

### Tests comportementaux

Rejouer une matrice E2E couvrant les comportements du tableau précédent, puis
rejouer intégralement `cartes-samples-labrador-2026` avec le checkpointer SQLite.
Pour chaque tour, consigner :

- les skills chargés ;
- les outils appelés ;
- la variable réellement utilisée ;
- l'état succès, vide, bloqué ou erreur ;
- les artefacts réellement retournés ;
- toute valeur ou source introduite sans provenance.

## Critères d'acceptation

- Zéro chargement de skill externe sans mention explicite de sa source.
- Zéro appel d'outil externe sans mention explicite ou levée explicite d'un
  verrou existant.
- Zéro hypothèse EcoTaxa fondée sur un numéro de projet seul.
- Zéro image ou lien annoncé après un rendu bloqué ou en erreur.
- Zéro changement silencieux de source après un résultat vide ou une colonne
  manquante.
- Le scénario professeur reste entièrement sur le TSV après le chargement et
  après le verrou explicite.
- Les contraintes existantes de confirmation coûteuse et de ton clinique
  restent satisfaites.

## Déploiement

Le runtime actuel lit le system prompt local. Les skills locaux sont la source
de vérité du développement ; toute synchronisation externe encore utilisée par
un environnement déployé doit être exécutée seulement après validation locale
et E2E. Le remodelage ne doit pas être considéré comme validé sur la seule base
de tests statiques : le rejeu LLM du scénario professeur est obligatoire.
