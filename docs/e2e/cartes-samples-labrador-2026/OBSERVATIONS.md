# Observations — rejeu step-by-step (main corrigé)

Run : `thread=e2e-cartes-lab-a1`, `user=run-lab-a1`, modèle `gpt-5.4-mini`,
base OpenAI (⚠️ config validée = OpenRouter ; routage sensible au provider).
Chaque tour est lancé via `scripts/dev/e2e_turn.py` (un tour à la fois).

Légende sévérité : 🔴 bloquant · 🟠 majeur · 🟡 mineur/friction

---

## Tour 1 — charger le fichier
**User :** « Charge le fichier data/demo/neolabs_taxonomy_2014_2020.tsv »
- ✅ `load_file` → `df_file_neolabs_taxonomy_2014_2020`, 7093 × 82. Fichier vu et confirmé.
- 🟡 **I-0** : charge `neolabs_abundance_analysis` d'office au chargement, sans demande d'analyse. Pré-chargement spéculatif.

## Tour 2 — carte positions Baie de Baffin, taille = nb samples/position
**Outils :** `load_skill(graph_planner)` → `get_zone_info(Baie de Baffin)` →
`load_skill(ecotaxa_navigation)` → `run_graph`×4 → succès.
- ✅ **D-CL1 corrigé** : carte rendue en `station_map` (plus de « type non supporté »).
- ✅ **D-CL2 corrigé** : taille mappée sur `n_samples` (vraie variable), **aucun `abundance_ind_L` inventé**.
- ✅ Fichier utilisé (df), aucun tool EcoTaxa appelé.
- 🟡 **I-1** : 3 `run_graph` gâchés avant succès — itère sur le contrat
  (`position mapping is missing` → `position mapping must use longitude_latitude`).
  Le template `station_map` de `graph_writer` n'est pas assez explicite/saillant.
- 🟡 **I-2** : `load_skill(ecotaxa_navigation)` chargé sans raison sur une demande
  100 % fichier — réflexe EcoTaxa (pas passé à l'acte, mais bruit + risque de dérive).

## Tour 3 — carte positions mer du Labrador, couleur = nb de taxons 🔴
**Outils :** `load_skill(ecotaxa_navigation)` → `get_zone_info(mer du Labrador)` →
`find_ecotaxa_samples_in_region(Mer du Labrador)` → « Aucun sample ».
- 🔴 **D-CL3 REPRODUIT** : fichier chargé (avec `latitude`/`longitude`/`sample_id`),
  demande « les échantillons situés dans la mer du Labrador » → l'agent interroge
  **EcoTaxa** au lieu du fichier, répond « Aucun sample dans le cache EcoTaxa » +
  URL EcoTaxa cassée `https://ecotaxa.obs-vlfr.fr/prj/`. **Faux** : le fichier a
  des samples du Labrador. Le fichier n'est ni vu ni utilisé.
- **Cause racine (mesurée)** : ma règle « Loaded-file scope precedence » (l.37) est
  présente MAIS le prompt pousse `find_ecotaxa_samples_in_region` **19×** + 2
  « default for named zones → EcoTaxa », et **aucune** route EcoTaxa-zone n'est
  gatée sur « aucun fichier chargé ». La précédence est noyée. Aggravé par
  `gpt-5.4-mini` sur base OpenAI (suivi d'instructions < config OpenRouter validée).
- 🟠 **I-3** : URL EcoTaxa vide `.../prj/` émise comme « source » — citation cassée.
- **Fix visé** : gater CHAQUE route EcoTaxa-zone/samples sur l'absence de fichier
  chargé (pas seulement ajouter un override), + court-circuit « fichier chargé +
  'samples/positions/échantillons' → filter_dataframe_by_zone » en tête de routage.

## Tour 4 — consigne « TSV only, aucune méthode EcoTaxa » ✅
**Outils :** aucun. Réponse : « Oui. J'utiliserai uniquement le fichier .tsv
chargé et n'utiliserai aucun outil, skill ou méthode EcoTaxa. »
- ✅ Acquiescement direct, pas d'esquive (D-CL4 OK sur ce tour).

## Tour 5 — carte positions Labrador, APRÈS la consigne TSV-only 🔴🔴
**Outils :** `load_skill(ecotaxa_navigation)` → `get_zone_info` →
`find_ecotaxa_samples_in_region` → « Aucun sample indexé ».
- 🔴🔴 **D-CL3 « hard lock » INEFFICACE** : l'agent a acquiescé au tour 4 puis a
  chargé le skill EcoTaxa **interdit** et appelé le tool EcoTaxa **interdit** au
  tour 5. Fichier ignoré, mauvaise réponse. C'est la séquence exacte de la rage prof.
- **Conclusion** : le verrou de périmètre par *prose de prompt* ne tient pas — le
  modèle l'ignore d'un tour à l'autre (aucun état de verrou n'est réellement porté).
  **Un fix robuste doit être au niveau code** : quand un fichier est chargé et/ou
  le périmètre est verrouillé, retirer/court-circuiter les tools EcoTaxa/EcoPart
  (middleware ou garde dans le tool), pas seulement l'écrire dans le prompt.
- **Confound** : run sur `gpt-5.4-mini` + base OpenAI ; la config *validée* est
  OpenRouter (suivi d'instructions potentiellement meilleur). À re-tester là-bas
  avant de conclure que SEUL le code peut régler ça — mais la robustesse code
  reste souhaitable quel que soit le provider.

## Tour 6 — « quel est le nom du fichier ? » ✅
**Outils :** aucun. Réponse : `data/demo/neolabs_taxonomy_2014_2020.tsv`.
- ✅ **D-CL4 corrigé** : réponse directe, aucune esquive vers un skill (le transcript esquivait).

## Tour 7 — « ajoute la côte » 🟠
**Outils :** `load_skill(graph_planner)` + `load_skill(graph_writer)` → `run_graph`.
- 🟠 **I-4** : produit un `run_graph` **placeholder vide** (« Static placeholder;
  no active source variables or map layer were available ») au lieu de refaire la
  carte Labrador depuis le fichier avec les côtes. Conséquence directe de D-CL3
  (le tour 5 n'a jamais construit de carte fichier → rien à enrichir).
- Mieux que le transcript (il ne déserte pas), mais résultat vide/inutile.

---

# Synthèse du run

| Tour | Défaut visé | Résultat |
|---|---|---|
| 1 charge fichier | — | ✅ (I-0 skill spéculatif) |
| 2 Baffin positions+taille | D-CL1, D-CL2 | ✅ **corrigés** (station_map, `n_samples`, 0 abondance inventée) ; I-1, I-2 |
| 3 Labrador couleur=taxa | D-CL3 | 🔴 **reproduit** (dérive EcoTaxa, fichier ignoré) ; I-3 URL vide |
| 4 consigne TSV-only | D-CL4 | ✅ acquiescement propre |
| 5 Labrador positions post-consigne | D-CL3 hard-lock | 🔴🔴 **reproduit** (viole le verrou juste accepté) |
| 6 nom du fichier | D-CL4 | ✅ **corrigé** (réponse directe) |
| 7 ajoute la côte | conséquence D-CL3 | 🟠 placeholder vide (I-4) |

## Verdict
- **Fixes CODE confirmés en live** : D-CL1 (`station_map`) + D-CL2 (plus d'abondance
  inventée), tour 2. D-CL4 (métadonnées/esquive), tour 6.
- **Fix PROMPT de D-CL3 INEFFICACE** : dérive EcoTaxa aux tours 3 et 5, y compris
  après consigne explicite. La *prose* ne verrouille pas le périmètre — le modèle
  l'ignore. **Prochain fix = enforcement CODE** : quand un fichier est chargé et/ou
  le périmètre est verrouillé, retirer les tools EcoTaxa/EcoPart du toolset exposé,
  ou les court-circuiter (garde renvoyant « périmètre fichier, utilise
  filter_dataframe_by_zone »).
- **Confound provider** : `gpt-5.4-mini`/OpenAI vs OpenRouter validé — à recontrôler.

## Défauts mineurs cumulés
- **I-0** : pré-chargement spéculatif de `neolabs_abundance_analysis` au load.
- **I-1** : 3 `run_graph` gâchés à trouver la forme `station_map` (template pas assez saillant).
- **I-2** : `load_skill(ecotaxa_navigation)` réflexe sur demandes 100 % fichier (tours 2,3,5).
- **I-3** : URL EcoTaxa vide `.../prj/` citée comme source.
- **I-4** : placeholder vide au lieu d'un vrai rendu (tour 7).

---

## Rejeu post-garde `b2` — tour Baffin

- ✅ Le DataFrame chargé est utilisé et filtré par le polygone IHO : `1570` lignes.
- ✅ La tentative de charger `ecotaxa_navigation` est bloquée par le garde de périmètre ;
  aucun outil EcoTaxa/EcoPart n'est exécuté.
- 🔴 Les deux appels de rendu sont bloqués par `position mapping is missing` :
  1. premier contrat sans mapping `position` ;
  2. second contrat avec `{x: longitude, y: latitude}` au lieu de
     `{variable: longitude_latitude}`.
- 🔴 **Hallucination de succès** : malgré deux résultats de tool en échec et aucune
  nouvelle image écrite dans `data/graphs/`, la réponse finale affirme que
  `![graph](sandbox:/graphs/graph.png)` existe.
- 🟠 Le driver persistait auparavant seulement le DataFrame, pas l'historique LangGraph
  entre processus (`MemorySaver`). Il utilise désormais le checkpointer SQLite et un
  test de régression prouve la persistance inter-processus.

## Rejeu post-garde `b2` — tour Labrador couleur = nombre de taxons

- ✅ La tentative de charger `ecotaxa_navigation` est bloquée ; aucun outil externe
  EcoTaxa/EcoPart n'est exécuté.
- ✅ Le filtre retourne `0` ligne et l'agent refuse finalement de fabriquer une carte.
  Cette conclusion est factuellement correcte : même la bbox large de la Mer du
  Labrador contient `0/7093` ligne du TSV.
- 🔴 **Chaînage involontaire des filtres** : `filter_dataframe_by_zone` repart du
  dernier DataFrame actif (le sous-ensemble Baffin de `1570` lignes), pas du TSV
  original. Le résultat persistant est donc nommé
  `df_in_mer_du_labrador_baie_de_baffin` avec `n_out=1570`, au lieu d'être filtré
  depuis les `7093` lignes chargées. Le résultat Labrador est juste par coïncidence ;
  une zone présente dans le TSV mais absente du sous-ensemble précédent produirait
  un faux négatif.
- 🟠 Après l'échec attendu de `run_graph` sur un DataFrame vide, l'agent appelle
  `run_pandas` en annonçant inspecter la table « broader loaded », mais utilise
  `base = df`, qui désigne encore le sous-ensemble actif. La formulation surestime
  donc la portée réelle de la vérification.

## Rejeu post-garde `b2` — verrou explicite TSV uniquement

- ✅ Aucun nouvel outil ni skill n'est appelé pendant ce tour.
- ✅ Réponse directe : l'agent confirme limiter toutes les analyses au TSV et ne
  plus utiliser de méthode EcoTaxa.
- ⏳ La solidité inter-tour de cet engagement sera vérifiée par la prochaine demande
  Labrador sur le même checkpoint SQLite.

## Rejeu post-garde `b2` — Labrador après verrou TSV

- ✅ **Verrou inter-tour confirmé** : aucun skill EcoTaxa et aucun outil
  EcoTaxa/EcoPart n'est tenté dans le nouveau processus.
- ✅ Chemin exclusivement local : `get_zone_info` → `filter_dataframe_by_zone` →
  skills graphiques → `run_graph`.
- ✅ Réponse finale honnête : `0` ligne, donc aucune carte ne peut être produite.
- 🔴 Le chaînage involontaire des filtres persiste : le filtre repart du sous-ensemble
  Labrador déjà vide (`n_out=0`) et crée
  `df_in_mer_du_labrador_mer_du_labrador`, pas du TSV original de `7093` lignes.
- 🟠 L'agent connaît `n_in=0` mais charge quand même les deux skills graphiques et
  appelle `run_graph`, qui échoue nécessairement sur le DataFrame vide. Il devrait
  s'arrêter immédiatement avec la limite factuelle.

## Rejeu post-garde `b2` — « quel est le nom du fichier ? »

- 🔴 **D-CL4 toujours présent avec une vraie mémoire multi-tour** : l'agent répond
  `df_in_mer_du_labrador_mer_du_labrador`, nom de variable du dernier sous-ensemble,
  au lieu de `data/demo/neolabs_taxonomy_2014_2020.tsv`.
- **Cause observée dans le store** : chaque `filter_dataframe_by_zone` remplace le
  `df` actif et toute sa `meta`. Après les filtres successifs, la session contient
  seulement `source=filter_by_zone:Mer du Labrador`,
  `parent_source=filter_by_zone:Mer du Labrador` et
  `variable_name=df_in_mer_du_labrador_mer_du_labrador`. La source du fichier
  original n'est plus accessible dans la capsule active.
- L'ancien run qui déclarait D-CL4 corrigé utilisait en réalité un `MemorySaver`
  recréé à chaque commande ; il ne testait donc pas cette accumulation d'état et
  constituait un faux positif.

## Rejeu post-garde `b2` — « ajoute la côte à cette carte »

- ✅ Aucun outil EcoTaxa/EcoPart n'est appelé et aucune image fictive n'est annoncée.
- ✅ La réponse finale reconnaît qu'aucune ligne n'est disponible et refuse la
  modification.
- 🟠 L'agent ne reconnaît pas immédiatement qu'aucune carte valide n'existe dans
  l'historique. Il recharge `graph_planner` et `graph_writer`, puis appelle
  `run_graph` sur le sous-ensemble vide avant de formuler la limite déjà connue.
- La réponse parle de « la carte actuelle », alors que le tour Baffin avait seulement
  halluciné un lien après deux contrats bloqués et que les tours Labrador n'ont créé
  aucune image. L'état devrait distinguer explicitement un artefact graphique validé
  d'une simple tentative de rendu.
