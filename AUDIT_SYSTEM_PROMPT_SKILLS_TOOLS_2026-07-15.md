# Audit du system prompt, des skills et des descriptions de tools

**Projet :** IDEA — Assistant copépodes NeoLab, Université Laval  
**Date de l'audit :** 15 juillet 2026  
**Périmètre :** état du dépôt de travail au moment de l'audit  
**Statut global :** **fonctionnel, bien testé, mais fragile sous charge de contexte et insuffisamment contraint par le code sur plusieurs règles critiques**

> **Mise à jour d'implémentation — 16 juillet 2026, Steps 8 et 10.** Ce document
> conserve les constats du snapshot du 15 juillet. Depuis cet audit : les 15
> skills ont un manifest commun validé (`name`, `version`, `triggers`,
> `forbidden_when`, `requires`, `next_tool`, `max_tokens`), le Hub est borné par
> l'allowlist et le hash local revu, et la provenance expose source,
> environnement, version et SHA-256. Le prompt permanent est passé d'environ
> 6 980 à 2 896 tokens selon le compteur runtime. Le replay offline garde les
> trois scénarios à 100 % aux niveaux 1 et 2, avec un coût fixe maximal de 8 843
> tokens et 15 tools exposés au maximum.
>
> Un défaut supplémentaire a été trouvé puis corrigé pendant cette étape : le
> plafond générique de 8 000 caractères tronquait les grands résultats de
> `load_skill` (`graph_writer` n'était visible qu'à ~20 %). Les résultats de
> skills manifestés utilisent désormais leur budget déclaré, borné à 12 000
> tokens, et un test vérifie la vue réellement envoyée au modèle jusqu'à la fin
> du document. Les procédures contradictoires de `environmental_join` et
> `neolabs_abundance_analysis` ont aussi été alignées sur la sélection explicite
> de source et les quatre enrichissements canoniques.
>
> Restent hors de cette fermeture : approbations exécutables de l'étape 7,
> isolation processus complète de l'étape 9 et éventuelle découpe future des
> grands skills déjà justifiés. Les mesures historiques ci-dessous ne doivent
> donc pas être lues comme l'état courant.
>
> **État de distribution Hub au 16 juillet :** 4/15 skills synchronisés dans
> les deux environnements; 11/15 refusés par LangSmith avec HTTP 500. Le script
> valide maintenant les manifests avant envoi et sort en erreur sur échec. Le
> runtime reste déterministe grâce au fallback local validé par hash.

## 1. Synthèse exécutive

L'architecture possède de bons fondements : un point d'assemblage unique des tools, un system prompt structuré par domaines, des skills spécialisés chargés à la demande, des métadonnées de présentation validées et des tests nombreux. Le runtime réel est lisible : `agent.py` charge le prompt local, construit un catalogue de 59 tools obligatoires, puis injecte le contexte de session via un middleware.

Les risques principaux ne viennent pas d'une absence de règles, mais de leur accumulation et de leur niveau d'application. Une partie importante des politiques critiques reste écrite en langage naturel alors qu'elle devrait être imposée par le runtime.

Les cinq constats prioritaires sont les suivants :

1. **Budget de contexte presque saturé avant la conversation.** Le prompt consomme environ 6 132 tokens et les schémas/descriptions des 59 tools environ 26 902 tokens, soit près de 33 034 tokens fixes sur une limite par défaut de 40 000. Le workflow graphique nominal ajoute environ 12 861 tokens avec `graph_planner` et `graph_writer`.
2. **Contradiction directe entre le prompt et le verrou Python sur les identifiants de projet.** Le prompt dit qu'un numéro de projet seul n'autorise pas EcoTaxa, tandis que `source_scope.py` et son test considèrent « projet 17498 » comme un signal EcoTaxa.
3. **Activation des skills partiellement déclarative et parfois permissive.** Les skills sont chargés depuis le Hub avant validation contre la liste locale, la provenance n'est pas renvoyée, et l'état `loaded_skills` persiste dans la session sans représenter l'ordre d'activation du tour courant.
4. **Confirmations coûteuses inégalement imposées.** Plusieurs téléchargements lourds n'ont aucun argument `confirmed` et dépendent uniquement du respect du system prompt par le modèle.
5. **Documentation d'inventaire en retard sur le runtime.** Le catalogue contient 59 tools obligatoires et 62 avec SQL, alors que `TOOLS.md`, `ARCHITECTURE.md`, `SPEC.md` et `AGENTS.md` annoncent encore 55/58 ou environ 53/54.

## 2. Appréciation par couche

| Couche | État | Appréciation | Risque principal |
|---|---|---|---|
| Chargement du system prompt | Bon | Source locale explicite et déterministe | Documentation affirme encore un pull Hub inexistant |
| Contenu du system prompt | Moyen | Bonne couverture fonctionnelle, structure claire | Densité, répétitions et contradictions |
| Activation des skills | Moyen-faible | Chargement à la demande opérationnel | Autorisation persistante, Hub non borné, activation surtout en prose |
| Description des tools | Moyen | Plusieurs descriptions riches et précises | Forte hétérogénéité et coût de contexte très élevé |
| Catalogue des tools | Bon | Composition unique, noms uniques, métadonnées validées | Tous les tools sont exposés à chaque tour |
| Garde-fous runtime | Moyen | Contrôles réels pour le scope fichier, les IDs et les graphes | Couverture partielle des sources et opérations lourdes |
| Tests | Bon sur les contrats statiques | 69 tests ciblés passent | Les tests de présence de texte ne détectent pas les contradictions sémantiques |
| Documentation | Faible à moyenne | Plusieurs documents de référence utiles | Inventaires et chemin Hub obsolètes |

## 3. État réel du runtime

### 3.1 Chemin du prompt

Le prompt réellement utilisé est exclusivement local :

```text
agents/copepod_system_prompt.py
        ↓ import
agent.py::_load_system_prompt()
        ↓
agent.py::_SYSTEM_PROMPT
        ↓
create_agent(..., system_prompt=_SYSTEM_PROMPT)
```

Références : `agent.py:25`, `agent.py:44-56`, `agent.py:513-530`.

Le commentaire de `_load_system_prompt()` indique clairement que le Hub LangSmith a été retiré du chemin de lecture. Toutefois, les documents et commentaires suivants disent encore que le prompt est tiré du Hub avec fallback local :

- `AGENTS.md:29-30`, `AGENTS.md:145` ;
- `CONTEXT.md:43` ;
- `ARCHITECTURE.md:111`, `ARCHITECTURE.md:235` ;
- `serve.py:1480-1483`.

Le script `scripts/dev/push_prompt.py` pousse toujours le prompt vers LangSmith, mais le runtime ne le relit pas. Il s'agit donc actuellement d'une synchronisation sans consommateur de production dans `agent.py`.

### 3.2 Composition du contexte modèle

Avant chaque appel modèle, `_ContextMiddleware` :

- tronque les résultats de tools trop longs ;
- estime le coût du prompt, des schémas de tools, de la mémoire et de l'historique ;
- injecte la mémoire et un bloc `ACTIVE DATASET STATE` ;
- réduit l'historique selon le budget restant ;
- filtre une partie des tools EcoTaxa/EcoPart lorsque le tour est rattaché au fichier chargé.

Références : `agent.py:210-338`.

Mesures obtenues sur le catalogue obligatoire sans SQL :

| Élément | Estimation |
|---|---:|
| System prompt | 6 132 tokens |
| Schémas et descriptions des 59 tools | 26 902 tokens |
| Coût fixe avant mémoire et historique | 33 034 tokens |
| Limite configurée par défaut | 40 000 tokens |
| Réserve configurée | 2 000 tokens |
| `graph_planner` | 2 648 tokens |
| `graph_writer` | 10 213 tokens |

Conséquence : dans le workflow graphique normal, le dernier tour complet peut dépasser la limite. Le code choisit alors de conserver ce dernier tour entier plutôt que de perdre la demande utilisateur (`agent.py:171-184`). Ce comportement protège la cohérence du tour, mais ne protège pas contre le dépassement de fenêtre.

## 4. Audit du system prompt

### 4.1 Points forts

- Structure explicite par domaines : sélection de source, session, vérité des résultats, RAG, géographie, SQL, graphes, ton, confirmation et sécurité.
- Règle claire de source locale par défaut lorsqu'un fichier est chargé.
- Séparation raisonnable entre règles permanentes et procédures spécialisées externalisées dans les skills.
- Règles fortes contre les identifiants non fondés, les artefacts inventés et les résultats de tools présentés comme succès après erreur.
- Politique de non-interprétation scientifique cohérente avec le périmètre métier.
- Tests de présence et d'ordre des sections dans `tests/test_agent_factory.py` et `tests/test_prompt_source_routing.py`.

### 4.2 Faiblesses et contradictions

#### P0 — Numéro de projet : règle contradictoire

Le prompt impose : « A project number alone is not an EcoTaxa signal » (`agents/copepod_system_prompt.py:21`).

Le code considère pourtant comme signal explicite :

```python
r"\bproje?t\s+n?[°o]?\s*\d{3,6}\b"
```

Référence : `tools/source_scope.py:23-32`. Le test `tests/test_source_scope.py:43-51` valide explicitement « résume le projet 17498 avant export » comme signal EcoTaxa. Le test du prompt valide simultanément la règle opposée (`tests/test_prompt_source_routing.py:24-25`). Les deux suites passent, ce qui démontre une lacune des tests contractuels actuels.

#### P0 — Règle numérique incompatible avec les tools spécialisés

Le prompt dit à la fois :

- préférer les tools read-only spécialisés pour compter, classer et résumer (`agents/copepod_system_prompt.py:31-34`) ;
- toujours appeler `run_pandas` pour produire toute valeur numérique (`agents/copepod_system_prompt.py:44`).

Un tool comme `count_ecotaxa_taxa`, `audit_ecotaxa_availability` ou `summarize_ecotaxa_projects` retourne déjà des valeurs numériques. Le modèle reçoit donc deux obligations incompatibles : utiliser le résultat spécialisé directement, ou recalculer via pandas.

#### P1 — Activation graphique trop large

La section graphique demande de charger les deux skills pour « ANY data analysis or visualization request » (`agents/copepod_system_prompt.py:103-108`). Cette formulation englobe une question numérique simple, alors que le reste du prompt distingue analyse tabulaire et visualisation. Elle déclenche potentiellement plus de 12 000 tokens de skills pour une table ou un calcul sans figure.

#### P1 — Répétition normative

Le prompt contient environ 51 occurrences de formulations impératives fortes (`must`, `always`, `never`, `critical`). Plusieurs politiques sont répétées dans `Routing Priority`, `Session Rules`, `Context and Session State`, `Files and DataFrames`, puis dans les skills. La répétition augmente le coût et le risque que deux variantes divergent.

#### P1 — Verrou de source persistant uniquement en prose

Le prompt affirme qu'une restriction explicite de source persiste entre les tours (`agents/copepod_system_prompt.py:23`, `agents/copepod_system_prompt.py:49`). Aucun état de type `source_lock` n'est conservé dans le runtime. Le middleware ne regarde que le dernier message utilisateur et l'existence d'un DataFrame.

#### P2 — Politique de citations trop restrictive

Le prompt demande de refuser toute référence vérifiée et de renvoyer vers Google Scholar ou Web of Science (`agents/copepod_system_prompt.py:166-168`). Cette règle réduit la capacité du RAG ou d'un outil taxonomique à restituer une source déjà présente et traçable. Elle devrait distinguer « ne pas inventer » de « ne jamais fournir ».

## 5. Audit de l'activation des skills

### 5.1 État actuel

Le dépôt contient 14 skills Markdown. `load_skill` :

1. découvre les fichiers locaux au moment de construire sa description ;
2. tente un pull LangSmith Context Hub si une clé est disponible ;
3. retombe silencieusement sur le fichier local en cas d'échec ;
4. enregistre le nom dans `session.meta.loaded_skills`.

Références : `tools/skill_tool.py:23-49`, `tools/skill_tool.py:52-86`.

Les tests couvrent le pull Hub, le fallback local, l'absence de clé et l'enregistrement en session (`tests/test_skill_tool.py`).

### 5.2 Taille et cohérence des skills

| Skill | Tokens approx. | Précondition d'activation dédiée | Frontmatter |
|---|---:|---|---|
| `amundsen_ctd_query` | 1 003 | oui | non |
| `bio_oracle_query` | 1 813 | oui | non |
| `copepod_hydrodynamic_micro_zoom` | 1 595 | non | oui |
| `deliverable_writer` | 1 826 | non | oui |
| `ecopart_query` | 1 326 | oui | non |
| `ecotaxa_navigation` | 8 503 | oui | non |
| `ecotaxa_query` | 1 472 | oui | non |
| `environmental_join` | 1 028 | non | oui |
| `graph_planner` | 2 648 | non | non |
| `graph_writer` | 10 213 | non | non |
| `neolabs_abundance_analysis` | 3 084 | non | oui |
| `sql_workspace_query` | 841 | non | non |
| `uvp_ecopart` | 1 190 | non | non |
| `uvp_ecotaxa` | 4 505 | non | non |

Les formats ne sont pas homogènes : cinq skills externes possèdent une section `Activation precondition`, cinq fichiers ont un frontmatter, et certains n'ont ni l'un ni l'autre. Le chargeur ne lit ni le frontmatter ni les préconditions pour prendre une décision ; tout est transmis au modèle comme texte.

### 5.3 Points faibles

#### P0 — Le Hub est consulté avant la validation locale du nom

`load_skill` appelle `_pull_from_hub(skill_name)` avant de vérifier si `skill_name` appartient aux skills découverts localement (`tools/skill_tool.py:74-84`). Un nom absent du dépôt peut donc être chargé s'il existe dans le namespace Hub correspondant. La liste locale affichée dans la description n'est pas une allowlist d'exécution.

#### P0 — Provenance et version invisibles

Le contenu retourné ne précise pas s'il vient du Hub ou du disque, ni sa version, son environnement ou son hash. Un fallback Hub → local est silencieux. Deux sessions peuvent donc appliquer des instructions différentes tout en enregistrant seulement le même nom de skill.

#### P0 — Le garde-fou graphique est fail-open et non séquentiel

`run_graph` bloque seulement si `loaded_skills` n'est pas vide **et** que `graph_writer` en est absent (`tools/data_tools.py:655-662`). Donc :

- si aucun skill n'a jamais été chargé, `run_graph` reste autorisé ;
- `graph_planner` n'est pas exigé ;
- `graph_writer` chargé lors d'un ancien tour satisfait le contrôle ;
- la règle « le très prochain appel doit être `run_graph` » n'est pas vérifiée.

L'état actuel mesure « déjà chargé dans la session », pas « activé dans le bon ordre pendant ce tour ».

#### P1 — Préconditions externes incomplètement appliquées

Les tests garantissent une précondition explicite pour cinq skills de sources externes. Le middleware n'applique toutefois un blocage de chargement qu'aux skills EcoTaxa (`ecotaxa_navigation`, `ecotaxa_query`) lorsqu'un fichier est actif. Amundsen, Bio-ORACLE et OGSL restent disponibles et reposent sur le prompt pour respecter le gateway.

#### P1 — Skills trop volumineux

`ecotaxa_navigation` contient environ 8 503 tokens et `graph_writer` environ 10 213. Ce sont pratiquement de seconds system prompts. Leur taille diminue la saillance des règles principales et rend le workflow graphique incompatible avec la limite nominale de 40 k dans certains tours.

#### P1 — Instructions contradictoires entre skills

`environmental_join.md` indique à un endroit que l'enrichissement OGSL standard passe par `query_ogsl`, puis indique plus loin qu'il passe par `enrich_with_ogsl`. Ce type d'écart est difficile à détecter avec les tests actuels, qui cherchent principalement des chaînes de caractères attendues.

## 6. Audit des descriptions et du catalogue de tools

### 6.1 Inventaire réel

Le catalogue construit sans SQL contient 59 tools ; avec SQL, 62. Les tests du runtime le confirment (`tests/test_tool_catalog.py:124-152`).

| Famille runtime | Nombre |
|---|---:|
| EcoTaxa | 28 |
| EcoPart | 7 |
| Bio-ORACLE | 7 |
| Amundsen | 6 |
| Core | 4 |
| Données | 3 |
| Géographie | 2 |
| OGSL | 2 |
| **Total obligatoire** | **59** |
| SQL conditionnel | **+3** |

`TOOLS.md` annonce encore 55 tools obligatoires et 58 avec SQL. Son tableau récapitulatif annonce aussi 25 EcoTaxa et 6 EcoPart, alors que les listes et le catalogue ont évolué. `ARCHITECTURE.md` annonce 55 + 3. `SPEC.md`, `README.md` et `AGENTS.md` utilisent encore des estimations plus anciennes.

### 6.2 Points forts

- `tools/tool_catalog.py` est un seam unique de composition.
- Le catalogue rejette les noms dupliqués.
- Les métadonnées UI sont séparées des descriptions destinées au LLM.
- Chaque label UI est bilingue et masque le nom interne du tool.
- Les familles et identités de sources sont validées au démarrage.
- Les tools SQL sont ajoutés seulement lorsque la configuration est résolvable.

### 6.3 Hétérogénéité des descriptions

Les descriptions vont de 52 à 2 285 caractères :

- 9 descriptions font moins de 120 caractères ;
- 11 descriptions dépassent 1 000 caractères ;
- seulement 18 descriptions mentionnent explicitement un chargement préalable de skill ;
- seulement 3 descriptions contiennent le mot « confirmation » ou équivalent.

Les descriptions courtes concernent notamment `query_ecopart`, `query_amundsen_ctd`, plusieurs `list_*` et `preview_*`. Elles n'explicitent pas toujours :

- le coût ou la mutation de session ;
- la confirmation requise ;
- le moment où les préférer à un autre tool ;
- la variable persistée ;
- la source exacte et les préconditions.

À l'inverse, plusieurs tools EcoTaxa répètent plus de 1 000 caractères de routage. Cette information devrait être normalisée et partagée plutôt que dupliquée dans chaque schéma envoyé au modèle.

### 6.4 Confirmations coûteuses

Le prompt exige une confirmation avant `query_ecotaxa`, `query_ecopart`, `query_amundsen_ctd`, certains appels Bio-ORACLE, `export_deliverable` et d'autres opérations (`agents/copepod_system_prompt.py:151-164`).

Pourtant :

- `query_ecotaxa` n'a pas d'argument `confirmed` (`tools/copepod_sources.py:954-981`) ;
- `query_ecopart` n'a pas d'argument `confirmed` et utilise même `project_id=105` par défaut (`tools/ecopart_sources.py:631-642`) ;
- `query_amundsen_ctd` n'a pas d'argument `confirmed` (`tools/amundsen_sources.py:298-304`) ;
- `query_bio_oracle` n'a pas d'argument `confirmed` (`tools/bio_oracle_sources.py:515-534`) ;
- `export_deliverable` n'a pas d'argument `confirmed` (`tools/deliverable_tool.py:350-372`).

Quelques opérations récentes, comme `export_ecotaxa_samples`, l'enrichissement EcoPart distant, certains enrichissements Bio-ORACLE et `query_ogsl`, possèdent un contrôle exécutable. La politique CT-AG-06 est donc appliquée de façon non uniforme.

### 6.5 Tous les tools exposés à chaque tour

Le runtime déclare toutes les familles à la construction (`tools/tool_catalog.py:335-375`). Le middleware masque seulement EcoTaxa/EcoPart dans un cas précis. Cette stratégie :

- coûte environ 26 902 tokens de schémas à chaque appel ;
- augmente la compétition entre tools proches ;
- rend la sélection dépendante de descriptions longues ;
- expose des opérations lourdes même lorsqu'elles ne sont pas pertinentes.

## 7. Qualité des tests

La sélection suivante a été exécutée pendant l'audit :

```text
pytest -q tests/test_prompt_source_routing.py \
          tests/test_source_scope.py \
          tests/test_skill_tool.py \
          tests/test_tool_catalog.py

69 passed in 1.44s
```

Les tests sont utiles pour empêcher la disparition accidentelle de règles ou de métadonnées. Leur faiblesse principale est qu'ils vérifient souvent la présence d'une phrase plutôt que la cohérence du comportement global.

Exemple : un test exige que le prompt dise qu'un numéro de projet seul n'est pas un signal EcoTaxa, tandis qu'un autre exige que le code considère « projet 17498 » comme un signal. Les deux passent.

Il manque notamment des tests de propriétés transversales :

- une même entrée doit produire la même décision de source dans le prompt de référence et dans le middleware ;
- aucun tool lourd ne doit s'exécuter sans état de confirmation valide ;
- `run_graph` doit être impossible sans la séquence du tour courant ;
- un skill absent de l'allowlist locale ne doit jamais être chargé depuis le Hub ;
- le coût fixe prompt + schemas doit rester sous un seuil budgétaire ;
- la documentation générée doit refléter exactement le catalogue runtime.

## 8. Dette documentaire et legacy

### Écarts observés

- `agents/copepod_prompt.py` contient un ancien modèle d'exécution sans rapport avec le runtime actuel. Il est marqué déprécié dans certains documents, mais reste suffisamment complet pour être confondu avec une source active.
- `core/instruction_renderer/blocks/copepod_mode_analyse.py` et `copepod_mode_plan.py` conservent le vocabulaire de modes alors que la règle officielle dit qu'il n'existe aucun mode de session.
- `AGENTS.md` annonce environ 53 tools, 42 tests, un prompt d'environ 64 lignes, `create_react_agent` et un pull Hub. Le runtime actuel a 59 tools, un prompt de 172 lignes, `create_agent` et une source locale.
- `serve.py` commente encore que le redémarrage recharge le prompt depuis le Hub.
- `TOOLS.md` contient des totaux incohérents avec ses propres sections et le catalogue.

Ces écarts n'empêchent pas directement l'exécution, mais ils augmentent fortement le risque qu'une prochaine modification soit faite au mauvais endroit.

## 9. Recommandations priorisées

### P0 — À traiter en premier

#### 1. Réduire et contrôler le budget fixe

- Définir un budget CI : par exemple prompt + schemas ≤ 50 % de `MAX_CONTEXT_TOKENS`.
- Ne plus exposer les 59 tools à chaque tour. Activer dynamiquement une famille après une décision de source déterministe.
- Réduire les descriptions répétitives et déplacer les procédures longues dans des skills plus petits.
- Scinder `graph_writer` en contrats spécialisés chargés selon le type de figure.

#### 2. Créer une politique de source unique et exécutable

- Introduire un `SourcePolicy` structuré couvrant fichier, EcoTaxa, EcoPart, Amundsen, Bio-ORACLE, OGSL et SQL.
- Conserver explicitement `active_source`, `source_lock`, `lock_reason` et `released_at_turn` dans la session.
- Faire générer le bloc correspondant du prompt à partir de cette politique, au lieu de maintenir une regex et une prose indépendantes.
- Supprimer le numéro de projet générique des signaux EcoTaxa, ou modifier officiellement la règle métier ; ne pas garder les deux comportements.

#### 3. Imposer les confirmations dans le runtime

- Ajouter un mécanisme uniforme de confirmation avec portée, empreinte des arguments et expiration par tour.
- Refuser côté code tout appel lourd sans confirmation valide.
- Éviter un simple booléen réutilisable sur des arguments différents.
- Couvrir au minimum les opérations listées dans CT-AG-06.

#### 4. Fermer l'activation des skills

- Valider `skill_name` contre une allowlist locale avant tout accès Hub.
- Retourner une enveloppe avec `name`, `source`, `environment`, `version/hash` et `content`.
- Journaliser les divergences Hub/local et rendre le fallback visible dans l'observabilité.
- Prévoir un mode strict en production : version attendue obligatoire ou échec explicite.

#### 5. Représenter l'ordre des skills par tour

- Remplacer `loaded_skills: list[str]` par des événements horodatés et associés à un `turn_id`.
- Pour un graphe, imposer en code l'automate `planner → writer → run_graph` dans le même tour.
- Faire échouer `run_graph` lorsque l'état d'activation est vide ; le contrôle actuel doit être fail-closed.

### P1 — Consolidation

#### 6. Établir un registre déclaratif unique

Créer un registre versionné par tool contenant :

- famille et source ;
- coût (`light`, `conditional`, `heavy`) ;
- mutation de session ;
- confirmation ;
- skill requis ;
- préconditions ;
- variable persistée ;
- label UI ;
- description courte destinée au LLM.

Générer depuis ce registre le catalogue, l'inventaire `TOOLS.md`, les sections de confirmation et les tests de parité.

#### 7. Normaliser les skills

- Imposer un frontmatter commun : `name`, `version`, `triggers`, `forbidden_when`, `requires`, `next_tool`, `max_tokens`.
- Mettre les préconditions d'activation dans les métadonnées exécutables.
- Fixer une taille cible ; un skill de plus de 3 000 tokens doit être scindé ou justifié.
- Dédupliquer les règles générales déjà présentes dans le prompt.

#### 8. Corriger les contradictions de routage

- Remplacer « toute valeur numérique exige pandas » par « toute valeur dérivée ou non fournie par un tool spécialisé exige une exécution contrôlée ».
- Limiter le workflow `graph_planner` + `graph_writer` aux demandes visuelles.
- Clarifier le choix OGSL entre `query_ogsl` et `enrich_with_ogsl`.
- Définir une seule règle pour l'ordre « extraction puis skill » ou « skill puis extraction » selon chaque source.

#### 9. Ajouter des tests comportementaux

- Tests paramétrés de décisions de source sur des formulations ambiguës.
- Tests de refus réels des opérations lourdes.
- Tests de séquence des skills dans un tour.
- Tests de budget de contexte avec les descriptions réelles.
- Tests de cohérence entre registre, prompt généré, runtime et documentation.

### P2 — Nettoyage

- Archiver ou déplacer `agents/copepod_prompt.py` hors du package actif.
- Retirer ou renommer les blocs `copepod_mode_*` s'ils ne sont plus utilisés.
- Corriger `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, `ARCHITECTURE.md`, `SPEC.md`, `README.md`, `TOOLS.md` et le commentaire de `serve.py`.
- Déprécier clairement `scripts/dev/push_prompt.py` tant que le runtime ne consomme plus le prompt Hub, ou rétablir un chemin de lecture versionné et testé.

## 10. Plan de remédiation proposé

| Étape | Livrable | Critère de sortie |
|---|---|---|
| 1 | Registre réel des 59/62 tools | Inventaire généré, aucune divergence avec le catalogue |
| 2 | Tests de politiques transversales | Les contradictions actuelles échouent avant correction |
| 3 | Garde de confirmation centralisée | Aucun tool lourd exécutable sans confirmation liée aux arguments |
| 4 | SourcePolicy multi-source | Même décision pour prompt, middleware et tests |
| 5 | Activation de skills versionnée par tour | Allowlist stricte et automate graphique fail-closed |
| 6 | Réduction du contexte | Coût fixe sous le seuil CI choisi |
| 7 | Documentation générée/nettoyée | 59/62 partout, chemin du prompt exact, legacy isolé |

## 11. Conclusion

Le système est plus mature que ne le laisse entendre sa documentation : le catalogue est validé, les tools sont nombreux, les tests ciblés passent et plusieurs garde-fous réels existent. Sa faiblesse structurelle est toutefois claire : **les politiques critiques sont réparties entre prompt, skills, descriptions, tests et quelques contrôles Python sans source de vérité unique**.

La priorité n'est pas d'ajouter davantage de règles textuelles. Elle est de transformer les règles déjà stabilisées — choix de source, confirmation, activation de skill et séquence graphique — en politiques exécutables, versionnées et génératrices de documentation. Cette évolution réduira simultanément le coût de contexte, les contradictions et le risque de routage erroné.

## Annexe A — Fichiers examinés

- `agent.py`
- `agents/copepod_system_prompt.py`
- `agents/copepod_prompt.py`
- `agents/skills/*.md`
- `tools/tool_catalog.py`
- `tools/skill_tool.py`
- `tools/source_scope.py`
- `tools/session_context.py`
- `tools/data_tools.py`
- factories de sources dans `tools/*_sources.py`
- `tools/deliverable_tool.py`
- `scripts/dev/push_prompt.py`
- `scripts/dev/push_skills.py`
- `CONTEXT.md`, `ARCHITECTURE.md`, `TOOLS.md`, `SPEC.md`, `README.md`, `AGENTS.md`
- tests ciblés du prompt, du scope, des skills et du catalogue

## Annexe B — Limites de l'audit

- Le contenu distant actuel du LangSmith Context Hub n'a pas été comparé aux fichiers locaux ; l'audit porte sur le mécanisme de synchronisation et de chargement présent dans le code.
- Aucun appel réel aux sources scientifiques externes n'a été lancé.
- Le dépôt contenait déjà des modifications locales non liées à cet audit. Elles ont été conservées et n'ont pas été modifiées.
