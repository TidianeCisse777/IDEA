# Test case — phase pré-analyse (exploration → enrichissement → connaissance taxonomique)

Objectif : valider le parcours complet **avant toute analyse chiffrée**. L'agent
doit savoir explorer le fonds EcoTaxa read-only, préparer un enrichissement
EcoTaxa ↔ EcoPart sans télécharger sans confirmation, et répondre aux questions
de connaissance taxonomique via la KB / WoRMS — sans jamais confondre ces trois
registres.

> **Priorité n°1 de ce test case — les deux entrées d'enrichissement.**
> Tout le reste (connaissance taxonomique, profils) est secondaire. Ce qui doit
> marcher à tous les coups, ce sont les **deux chemins** qui mènent à un jeu
> enrichi :
>
> - **Chemin A — explorer EcoTaxa → enrichir** : on part de l'exploration, on
>   fige un scope EcoTaxa (`query_ecotaxa`), puis on enrichit avec EcoPart.
> - **Chemin B — charger un fichier → enrichir** : on part d'un fichier local
>   (`load_file`), puis on enrichit avec EcoPart (fichier EcoPart en session ou
>   téléchargement remote).
>
> Ces deux chemins convergent vers la **même jointure** `(sample_id, depth_bin)`.
> C'est le cœur à tester ; les étapes P8-A / P8-B / P9 ci-dessous en sont la
> version bout-en-bout. Détail d'implémentation : `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`.

Ce test case se lit comme **un seul parcours chaîné** (P0 → P9) : chaque étape
suppose que la précédente a réussi et laisse un contexte de session exploitable.
Chaque étape se colle telle quelle dans Open WebUI, un tour à la fois, sur le
**même thread**. Pour chaque étape, vérifier les tool calls visibles
(LangSmith / Open WebUI) puis la réponse finale.

Registres à ne pas mélanger :

| Registre | Question type | Tools attendus | Interdits typiques |
|---|---|---|---|
| Exploration EcoTaxa | « quels projets / samples / taxons » | `list/find/summarize/count_ecotaxa_*` | `query_ecotaxa` (export), KB |
| Enrichissement | « croise EcoTaxa avec EcoPart / CTD » | `join_ecotaxa_ecopart`, `enrich_ecotaxa_with_ecopart_remote` | enrichir sans confirmation |
| Connaissance taxonomique | « qu'est-ce que / où vit / synonyme de » | `query_copepod_knowledge_base`, `lookup_marine_taxonomy` | tools EcoTaxa |

## Source de vérité locale

> ⚠️ **Projet de référence changé le 2026-07-10.** L'ancien projet-exemple
> `14853` est **supprimé côté EcoTaxa** (`GET /api/projects/14853` → **404**,
> absent de `list_ecotaxa_projects`). Son cache local subsiste, donc les tools
> affichent encore ses métadonnées avec des stats live à **0** — piège. Le test
> est re-baseliné sur **`17498`**, encore accessible. Voir la section
> « Régression investiguée » plus bas.

Valeurs **live capturées le 2026-07-10** (volatiles : `17498` est en cours
d'annotation, à rafraîchir si le test dérive) :

- Projet `17498` : instrument UVP6, V `357440`, P `1878169`, D `3`, U `0`.
- `count_ecotaxa_taxa(project_ids=[17498], taxa=["copépodes"])` →
  `Copepoda<Multicrustacea` / `25828` : V `1204`, P `23400`, total `24604`.
- Samples `17498000001/2/3` : P `95509 / 12781 / 7398` (V `1435 / 801 / 177`).

Les valeurs EcoPart / enrichissement ne sont **pas figées** ici : sur les données
démo, EcoTaxa et EcoPart doivent être de la **même campagne** pour matcher (voir
`docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`). Le test valide le **routage et les garde-fous**,
pas un taux de match numérique.

---

## P0 — cadrage : de quoi dispose l'agent

Prompt :
> Avant de commencer, quelles sources de données tu peux explorer pour les copépodes ?

Route attendue :
- Aucune, ou au plus `load_skill(...)`.

Critère de réussite :
- Réponse descriptive (EcoTaxa, EcoPart, Amundsen CTD, Bio-ORACLE, fichiers,
  KB) sans lancer d'export ni de requête lourde.
- Pas de `query_ecotaxa`, pas d'enrichissement, pas de nom interne de tool
  exposé.

## P1 — découverte des projets accessibles

Prompt :
> Quels projets EcoTaxa sont accessibles ?

Route attendue :
- `list_ecotaxa_projects`

Critère de réussite :
- Liste de projets avec IDs/titres.
- Pas de `query_ecotaxa`, pas de `run_pandas`.
- Comme la liste vient du compte live, ne pas figer le nombre exact.

## P2 — cadrage géographique / temporel

Prompt :
> Liste les samples EcoTaxa en Baie de Baffin en 2024.

Route attendue :
- `load_skill("ecotaxa_navigation")`
- `get_zone_info(zone_name="Baie de Baffin")`
- `find_ecotaxa_samples_in_region(zone_name="Baie de Baffin", date_range={"from": "2024-01-01", "to": "2024-12-31"})`

Critère de réussite :
- Table de 62 samples (`sample_id`, projet, lat/lon, dates, instrument).
- Breakdown : `17498` = 56, `14859` = 3, `14853` = 3.
- Pas de `polygon_wkt`, pas de bbox globale `-90/-180/90/180`.
- Pas de `query_ecotaxa`.

## P3 — profil d'un projet candidat

Prompt :
> Fais-moi un état des lieux du projet 17498 : combien de samples, quel instrument, et les comptes validés / prédits.

Route attendue :
- `load_skill("ecotaxa_navigation")`
- `summarize_ecotaxa_projects(project_ids=[17498])` (ou variante singulier)

Critère de réussite :
- Instrument UVP6, `V=357440`, `P=1878169` (valeurs live 2026-07-10, volatiles).
- V/P/D/U pas tous à 0 (contraste avec `14853`, projet mort → 0 partout).
- Pas de `query_ecotaxa`. Ne pas demander de ratio calculé ici (sinon
  `run_pandas` devient légitime).

## P4 — connaissance taxonomique : la KB, pas EcoTaxa

Prompt :
> Qu'est-ce que Calanus hyperboreus et où vit cette espèce ?

Route attendue :
- `query_copepod_knowledge_base(query="Calanus hyperboreus ...")`
- éventuellement `lookup_marine_taxonomy(name="Calanus hyperboreus")` pour la
  validation du nom.

Critère de réussite :
- La réponse vient de la KB / WoRMS, **pas** d'un projet EcoTaxa.
- Aucun tool EcoTaxa (`count_ecotaxa_taxa`, `find_ecotaxa_observations`, …)
  déclenché pour une question de définition.
- Pas de valeur d'abondance inventée : une question « qu'est-ce que » ne produit
  pas de chiffres de comptage.

## P5 — validation d'un nom de taxon (WoRMS)

Prompt :
> Le nom "Calanus finmarchicus" est-il valide, et quelle est sa classification ?

Route attendue :
- `lookup_marine_taxonomy(name="Calanus finmarchicus")`

Critère de réussite :
- Statut (`accepted` / synonyme) + rang + lignée (kingdom → genus) issus de
  WoRMS.
- L'agent distingue « nom valide » (taxonomie) de « présent dans tel projet »
  (exploration EcoTaxa) — il ne bascule pas sur `count_ecotaxa_taxa`.

## P6 — pont taxonomie → exploration

Prompt :
> Et dans le projet 17498, combien de copépodes sont validés ?

Route attendue :
- `load_skill("ecotaxa_navigation")`
- `count_ecotaxa_taxa(project_ids=[17498], taxa=["copépodes"])`

Critère de réussite :
- Résolution vers `Copepoda<Multicrustacea` / `25828`.
- `validés=1204`, `prédits=23400`, total `24604` (live 2026-07-10, volatiles).
- Ici **oui** un tool EcoTaxa (la question porte sur un projet), contrairement à
  P4/P5 : c'est le test que l'agent route selon l'intention, pas selon le mot
  « copépode ».
- Pas de `query_copepod_knowledge_base`, pas de `query_ecotaxa`.

## P7 — scan des samples avant de préparer l'enrichissement

Prompt :
> Scanne les samples 17498000001, 17498000002 et 17498000003 avant qu'on aille plus loin.

Route attendue :
- `load_skill("ecotaxa_navigation")`
- `summarize_ecotaxa_samples(sample_ids=[17498000001, 17498000002, 17498000003])`

Critère de réussite :
- V/P/D/U + total + top taxa par sample.
- Prédits par sample : `17498000001=95509`, `17498000002=12781`,
  `17498000003=7398` (validés `1435 / 801 / 177`, live 2026-07-10).
- Pas de `query_ecotaxa_sample`, pas de `query_ecotaxa`.

---

# ★ Cœur du test — enrichir par les deux entrées

Les 3 workflows réels (cf. `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`), à couvrir :

| # | Situation de départ | Tool | Remote ? | Chemin |
|---|---|---|---|---|
| 1 | EcoTaxa **et** EcoPart déjà en session (2 fichiers, ou `query_ecotaxa` + `query_ecopart`) | `join_ecotaxa_ecopart` | non | A ou B |
| 2 | Fichier EcoTaxa chargé, EcoPart **pas** en session | `enrich_ecotaxa_with_ecopart_remote` | oui | B |
| 3 | EcoTaxa exporté via `query_ecotaxa`, EcoPart pas en session | `enrich_ecotaxa_with_ecopart_remote` | oui | A |

Jouer **P8-A puis P9** (chemin exploration), *ou* **P8-B puis P9** (chemin
fichier). Idéalement les deux, sur deux threads distincts.

## P8-A — Chemin A : exploration EcoTaxa → figer le scope → enrichir

Prérequis : contexte projet/samples 17498 établi (P3/P7) sur le même thread.

**Règle dure : l'enrichissement doit passer par les tools d'exploration EcoTaxa
AVANT l'export.** L'ordre attendu dans le parcours est
`exploration → query_ecotaxa → enrich`. Un enrichissement qui saute directement
à `query_ecotaxa` sans étape d'exploration est un échec.

Étape A.0 — exploration (obligatoire, cadre le projet) :
> Fais-moi un résumé du projet 17498.

Route attendue :
- `summarize_ecotaxa_project(project_id=17498)` (ou autre tool d'exploration
  read-only sur 17498).

Étape A.1 — figer le scope EcoTaxa (workflow 3, full remote) :
> Exporte les copépodes du projet 17498 pour qu'on puisse les enrichir.

Route attendue :
- `query_ecotaxa(project_id=17498, ...)` — pose la session `{thread}:ecotaxa`
  avec `meta.project_id=17498`. Appelé **après** l'exploration A.0.
- Confirmation attendue avant l'export (CT-AG-06) si l'agent la traite comme
  opération lourde.

Étape A.2 — enrichir :
> Maintenant enrichis-les avec les profils EcoPart correspondants.

Route attendue :
- `load_skill(...)` (ex. `environmental_join` / `ecopart_query`)
- `enrich_ecotaxa_with_ecopart_remote()` **appelé sans ID EcoPart** — il relit
  `meta.project_id` laissé par `query_ecotaxa`.

Critère de réussite (P8-A) :
- **Ordre respecté** : un tool d'exploration (`summarize_ecotaxa_project` / autre)
  apparaît **avant** `query_ecotaxa`, lui-même **avant**
  `enrich_ecotaxa_with_ecopart_remote`. C'est asserté en dur (`expect_order`).
- L'agent **ne redemande pas l'ID EcoPart** : résolution automatique via
  `meta.project_id`, puis fallback bbox (`object_lat/lon`) / labels de profil.
- Il **annonce l'opération lourde** (téléchargement) et **demande confirmation**
  (CT-AG-06) avant de lancer réellement.
- Il ne re-dérive pas la donnée EcoTaxa : il réutilise le scope de session.
- Pas de présentation d'un résultat comme acquis avant exécution.

## P8-B — Chemin B : charger un fichier → enrichir

Ce chemin **ne suppose aucune exploration préalable** — c'est un thread neuf.

Étape B.1 — charger le fichier EcoTaxa :
> Charge ce fichier EcoTaxa. *(joindre / pointer un TSV EcoTaxa)*

Route attendue :
- `load_file(...)` → met le DataFrame EcoTaxa en session.

Étape B.2 — enrichir. Deux variantes selon ce que l'utilisateur a en main :

- **B.2a — EcoPart aussi en session** (workflow 1, jointure locale) : après un
  second `load_file` d'un fichier EcoPart (ou `query_ecopart`) :
  > Enrichis le fichier EcoTaxa avec le fichier EcoPart chargé.
  - Route attendue : `join_ecotaxa_ecopart()` — **pas** de remote.

- **B.2b — EcoPart pas en session** (workflow 2, remote) :
  > Enrichis ce fichier EcoTaxa avec les profils EcoPart correspondants.
  - Route attendue : `enrich_ecotaxa_with_ecopart_remote()` — télécharge EcoPart,
    résolution du projet via bbox `object_lat/lon` ou labels de profil (pas de
    `meta.project_id` ici puisqu'on n'est pas passé par `query_ecotaxa`).

Critère de réussite (P8-B) :
- Le bon tool selon la session : `join_ecotaxa_ecopart` si EcoPart est **déjà
  là**, `enrich_ecotaxa_with_ecopart_remote` sinon. **Ne pas** re-télécharger si
  la donnée est déjà chargée.
- Variante remote (B.2b) : opération lourde → **confirmation** (CT-AG-06).
- Aucune valeur EcoPart inventée si la résolution du projet échoue → l'agent
  demande alors un ID au lieu de bluffer.

## P9 — exécution + honnêteté du taux de match (commun A et B)

Prérequis : P8-A ou P8-B, l'utilisateur confirme.

Prompt :
> Oui, vas-y.

Route attendue :
- exécution réelle de `enrich_ecotaxa_with_ecopart_remote(...)` (chemins A / B.2b)
  ou `join_ecotaxa_ecopart(...)` (chemin B.2a).

Critère de réussite :
- La réponse **rapporte le taux de match** (« X matchées sur un bin EcoPart »).
- Si 0 ou faible match (ex. campagnes différentes), l'agent **avertit
  explicitement** et ne présente pas une table pleine de `NaN` — ni des
  métriques qui en dériveraient — comme un succès.
- Clé de jointure `(sample_id, depth_bin)` ; colonnes EcoPart préfixées
  `ecopart_` et **préservées, pas moyennées** ; aucun volume inventé sur les bins
  non couverts par le cast.
- **Aucune analyse chiffrée n'est encore lancée** : le parcours s'arrête au jeu
  enrichi prêt à l'emploi. m5/m6 et compagnie sont hors périmètre (ce sont les
  analyses).

---

## Garde-fous transverses (à vérifier sur tout le parcours)

| Contrainte | Où ça compte | Attendu |
|---|---|---|
| CT-AG-06 confirmation op lourde | P8/P9 | Pas d'enrichissement/export sans « oui » explicite |
| CT-AG-26 ton clinique | partout | Pas de « je / moi / en tant qu'IA » ; format Résultat / Source / Méthode / Limite / Prochaine action |
| Pas de valeur inventée | P4, P9 | Tout chiffre vient d'un tool ; pas d'abondance sans comptage |
| KB ≠ EcoTaxa routing | P4/P5 vs P6 | Définition → KB/WoRMS ; « dans le projet X » → EcoTaxa |
| Pas de nom interne de tool exposé | partout | Réponses sans nom de fonction |
| Pas de bbox monde / `polygon_wkt` | P2 | Filtrage par zone nommée résolue |

## Rattachement à l'existant

- Étapes exploration (P1–P3, P6, P7) : cousines de `E0/E4/E6/E9` dans
  `docs/ecotaxa_exploration_ui_tests.md` et des evals `EX-*`
  (`evals/eval_ecotaxa_exploration*.py`).
- Étapes enrichissement (P8–P9) : couvertes côté implémentation par
  `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md` et
  `tests/test_enrichment_workflows_integration.py` ; ce test case en ajoute la
  version **parcours utilisateur** (confirmation + honnêteté du taux de match).
- Étapes taxonomiques (P4–P5) : s'appuient sur `tools/rag_tool.py`
  (`query_copepod_knowledge_base`) et `tools/taxonomy_tool.py`
  (`lookup_marine_taxonomy`, validé par `tests/test_taxonomy_lookup_tool.py`).

## Exécution

Manuel dans Open WebUI (un tour par étape, même thread) comme
`docs/ecotaxa_exploration_ui_tests.md`. Pour une version scriptée API-level,
réutiliser le runner :

```bash
python scripts/run_ecotaxa_exploration_ui_tests.py --base-url http://localhost:8000
```

(les étapes P8/P9 multi-turn nécessitent un thread partagé — cf. dispatcher
multi-turn de `evals/eval_ecotaxa_exploration_extra.py`).

---

## Régression investiguée (2026-07-10) — résultats du premier run

Runner : `scripts/run_preanalyse_test_case.py`. Contexte : agent live sur `:8000`.

**État final : 10/10 verts** : P1, P3, P4, P5, P6, P7, P8A, P8Ba, P8Bb, P9.
(P8Ba : routage LLM probabiliste mais fiable après fix — 7/8 runs verts, voir
ci-dessous.)

**Root cause du bloc « stats à 0 »** : le projet `14853` (exemple canonique
historique) est **supprimé côté EcoTaxa** — `GET /api/projects/14853` → **404**,
et il n'apparaît plus dans `list_ecotaxa_projects`. Le cache local
(`data/ecotaxa_cache.sqlite`) garde ses métadonnées, donc `summarize_*` /
`count_*` / sample stats affichaient la métadonnée périmée + des comptes live à
**0**, sans signaler la disparition. Vérifié : les projets `17498`, `42`, `14622`
renvoient des données normalement (HTTP 200). Ce n'est **pas** une régression de
code ni d'auth. Correctif : test re-baseliné sur `17498` + valeurs live fraîches.

**Pourquoi P9 restait rouge après le re-baseline (3 couches, toutes corrigées)** :

1. **`14853` était l'exemple canonique** du system prompt (×2) et du skill
   `ecotaxa_navigation` (×5). Projet mort → le modèle le rappelait par réflexe.
   **Corrigé** : remplacé par `17498` dans les deux fichiers (prompt rechargé par
   WatchFiles ; skill lu en local via `SKILL_PREFER_LOCAL=true`).
2. **Mémoires long-terme périmées** : 34 mémoires (sur 323) référençaient `14853`
   (« Amundsen 2024 leg 5 → 14853 », etc.), injectées dans le system message par
   le pre_model_hook, et **ré-écrites à chaque run** qui émettait `14853` (cercle
   vicieux). **Corrigé** : purge des 34 (`delete from store where value like
   '%14853%'`) + le runner utilise désormais un **user_id unique par run**
   (`RUN_USER_ID`) pour rester hermétique aux mémoires accumulées.
3. **Bug du runner** : les prompts du cas P9 disaient encore `14853` (un
   `replace_all` incomplet). **Corrigé** → P9 passe.

**Findings ouverts (hors périmètre, à décider)** :

- **Cache local périmé non détecté** : un projet 404 côté EcoTaxa devrait être
  signalé (« projet introuvable, cache local périmé »), pas rendu avec des stats
  à 0. Garde-fou de robustesse à ajouter dans `summarize_*`.
- **Mémoire vs données volatiles** : le système de mémoire stocke des faits
  périssables (project_id ↔ campagne) sans les invalider quand EcoTaxa change.
  À réfléchir (TTL sur les mémoires « data-grounded », ou ne pas mémoriser
  d'IDs de projet).
- **P8Ba — workflow 1 non-déterministe — ✅ RÉSOLU (2026-07-10).** Cause :
  collision de triggers. Le prompt listait « enrichis EcoTaxa avec EcoPart »
  comme trigger du **workflow 2 (remote)** ; quand EcoPart était pourtant déjà
  en session mais que l'user disait « enrichis », le verbe tirait vers le
  téléchargement remote au lieu de la jointure locale. Fix : durci le prompt
  pour que **le facteur décisif soit l'état de session (EcoPart chargé ou non),
  jamais le verbe** — « enrichis » n'override plus l'in-session check, et un
  garde-fou explicite « ne jamais télécharger un EcoPart quand un est déjà
  chargé » dans le workflow 2. Vérifié : 7/8 runs verts après fix (routage LLM
  probabiliste, mais l'agent appelle désormais fiablement `join_ecotaxa_ecopart`
  puis relaye l'avertissement 0-match campagne).
- **P8Bb — gate CT-AG-06 sur l'enrich remote — ✅ RÉSOLU (2026-07-10).**
  `enrich_ecotaxa_with_ecopart_remote` a maintenant un paramètre
  `confirmed=False` (défaut) qui renvoie un dry-run (projet EcoPart résolu + plan
  de jointure) **sans télécharger** ; l'exécution réelle exige `confirmed=True`,
  aligné sur `export_ecotaxa_samples`. Prompt mis à jour (deux-temps dry-run →
  confirmation → `confirmed=True`). Tests : `test_ecopart_sources.py`
  (`test_enrich_remote_dry_run_by_default_does_not_download` + 7 tests
  d'exécution passés en `confirmed=True`) et `test_enrichment_workflows_
  integration.py`. P8Bb passe désormais.
