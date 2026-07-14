# Canonical Sample–Depth Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produire une table UVP déterministe à une ligne par `(sample_id, depth_bin)` et obliger les analyses aval à la réutiliser.

**Architecture:** Un constructeur pandas pur dans `core/copepod_sample_depth.py` valide les clés, la hiérarchie, le volume et les métadonnées, puis calcule compte et abondances élémentaires. Le skill UVP et le system prompt imposent ce constructeur aux analyses, sans ajouter de tool LLM.

**Tech Stack:** Python 3, pandas, pytest, LangGraph ReAct prompt/skills, API OpenAI-compatible testée avec curl.

## Global Constraints

- TDD strict : chaque comportement de production commence par un test rouge observé.
- Sélection Copepoda uniquement via `copepod_hierarchy_mask` et `object_annotation_hierarchy`.
- Clé canonique exacte : `(sample_id, depth_bin)` ; le volume ne fait jamais partie de la clé.
- Aucun chiffre inventé et aucune interprétation biologique.
- Validation finale par un nouveau chat curl contre `/v1/chat/completions`.

---

### Task 1: Construire la table canonique et ses validations

**Files:**
- Create: `core/copepod_sample_depth.py`
- Create: `tests/test_copepod_sample_depth.py`

**Interfaces:**
- Consumes: `copepod_hierarchy_mask(df: pd.DataFrame) -> pd.Series`.
- Produces: `build_canonical_sample_depth(df: pd.DataFrame, *, volume_column: str = "ecopart_Sampled volume [L]", stable_columns: tuple[str, ...] | None = None, volume_rtol: float = 1e-6, volume_atol: float = 1e-9) -> pd.DataFrame`.
- Produces: `CANONICAL_METHOD_VERSION = "copepod-sample-depth-v1"`.

- [ ] **Step 1: Écrire les tests rouges du cas nominal**

Créer une fixture avec RA18/Calanoida, un bin sans Copepoda et deux valeurs de volume quasi identiques. Vérifier une ligne par clé, `copepod_count == [1, 0]`, le volume moyen et les formules ind./L et ind./m³.

- [ ] **Step 2: Vérifier le RED**

Run: `pytest tests/test_copepod_sample_depth.py -q`

Expected: FAIL pendant la collecte avec `ModuleNotFoundError: core.copepod_sample_depth`.

- [ ] **Step 3: Implémenter le chemin nominal minimal**

Valider les colonnes requises, convertir clé/volume en numérique, construire le masque hiérarchique, grouper seulement sur `sample_id` et `depth_bin`, vérifier la proximité des volumes avec `numpy.isclose`, puis calculer :

```python
canonical["abundance_ind_L"] = canonical["copepod_count"] / canonical["sampled_volume_L"]
canonical["abundance_ind_m3"] = canonical["abundance_ind_L"] * 1000.0
canonical["canonical_method_version"] = CANONICAL_METHOD_VERSION
```

- [ ] **Step 4: Vérifier le GREEN nominal**

Run: `pytest tests/test_copepod_sample_depth.py -q`

Expected: PASS pour le cas nominal.

- [ ] **Step 5: Écrire les tests rouges de refus**

Ajouter des tests séparés pour colonne requise absente, volume nul/négatif/NaN, volumes incompatibles dans une clé et métadonnée stable contradictoire. Chaque erreur doit nommer la colonne et/ou la clé concernée.

- [ ] **Step 6: Vérifier les nouveaux RED**

Run: `pytest tests/test_copepod_sample_depth.py -q`

Expected: FAIL sur les validations non encore implémentées.

- [ ] **Step 7: Implémenter les validations minimales**

Lever `ValueError` avant toute division. Pour `stable_columns`, conserver la valeur unique non nulle par clé ; lever une erreur si plusieurs valeurs distinctes existent.

- [ ] **Step 8: Vérifier le GREEN complet du composant**

Run: `pytest tests/test_copepod_sample_depth.py tests/test_copepod_taxonomy.py -q`

Expected: tous les tests passent.

- [ ] **Step 9: Commit du composant**

```bash
git add core/copepod_sample_depth.py tests/test_copepod_sample_depth.py
git commit -m "feat(science): add canonical sample-depth table"
```

### Task 2: Imposer le constructeur aux analyses UVP

**Files:**
- Modify: `agents/skills/uvp_ecotaxa.md`
- Modify: `agents/copepod_system_prompt.py`
- Modify: `tests/test_skill_tool.py`
- Modify: `tests/test_agent_factory.py`

**Interfaces:**
- Consumes: `build_canonical_sample_depth(...)` de Task 1.
- Produces: règle de routage commune aux tableaux, corrélations et datasets graphiques UVP EcoTaxa–EcoPart.

- [ ] **Step 1: Écrire les assertions rouges du skill**

Vérifier que le skill importe et appelle `build_canonical_sample_depth`, interdit un `groupby` incluant le volume comme clé et demande la réutilisation de la même table canonique pour les analyses aval.

- [ ] **Step 2: Écrire les assertions rouges du prompt**

Vérifier que le prompt exige le constructeur pour toute analyse UVP par sample–profondeur et interdit de reconstruire indépendamment les bins dans tableaux, corrélations et graphes.

- [ ] **Step 3: Vérifier le RED de routage**

Run: `pytest tests/test_skill_tool.py tests/test_agent_factory.py -q`

Expected: FAIL sur les nouvelles assertions.

- [ ] **Step 4: Modifier skill et prompt**

Remplacer les templates de groupement libres par :

```python
from core.copepod_sample_depth import build_canonical_sample_depth

canonical_bins = build_canonical_sample_depth(df_ecotaxa_ecopart)
```

Les métriques de profil consomment ensuite `canonical_bins`; elles ne refont ni le masque ni le groupement objet.

- [ ] **Step 5: Vérifier le GREEN de routage**

Run: `pytest tests/test_skill_tool.py tests/test_agent_factory.py -q`

Expected: tous les tests passent.

- [ ] **Step 6: Commit de l’intégration**

```bash
git add agents/skills/uvp_ecotaxa.md agents/copepod_system_prompt.py tests/test_skill_tool.py tests/test_agent_factory.py
git commit -m "fix(agent): reuse canonical UVP sample-depth bins"
```

### Task 3: Régression complète et validation curl

**Files:**
- Modify only if evidence exposes a defect in files already listed above.
- Record evidence in the final response; do not add generated runtime data to git.

**Interfaces:**
- Consumes: composant et routage des Tasks 1–2.
- Produces: preuve automatisée et preuve agent E2E.

- [ ] **Step 1: Lancer la suite complète**

Run: `pytest tests/`

Expected: exit 0, aucune régression.

- [ ] **Step 2: Vérifier le service**

Run: `curl -fsS http://localhost:8000/`

Expected: réponse de santé HTTP 200. Si le hot reload n’a pas pris le code, redémarrer uniquement `copepod-agent`.

- [ ] **Step 3: Lancer un nouveau chat positif**

Envoyer une fixture accessible au runtime et demander explicitement de charger `uvp_ecotaxa`, construire `canonical_bins`, afficher RA18 et le nombre de clés dupliquées, puis dériver un second résumé depuis la même table.

Expected: l’appel d’analyse importe `build_canonical_sample_depth`; RA18 conserve le même compte dans les deux vues; les bins nuls existent; doublons de clé = 0.

- [ ] **Step 4: Lancer un nouveau chat négatif**

Demander le même calcul sur une table sans `object_annotation_hierarchy` ou avec volumes contradictoires.

Expected: refus explicite du constructeur; aucune liste taxonomique manuelle et aucun volume choisi arbitrairement.

- [ ] **Step 5: Vérifier l’état git final**

Run: `git status --short && git log -5 --oneline`

Expected: worktree propre et commits D02–D03 présents.
