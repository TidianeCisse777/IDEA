# Abundance Analysis Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verrouiller les datasets de corrélation UVP avec les bins nuls par défaut et empêcher toute production implicite de m5/m6.

**Architecture:** Une fonction pandas pure valide la table canonique et prépare les colonnes abondance–environnement sans calculer de statistique. Le skill UVP et le system prompt imposent cette fonction et séparent l'abondance élémentaire des métriques m5/m6 explicitement demandées.

**Tech Stack:** Python 3, pandas, numpy, pytest, prompt/skills LangGraph, API OpenAI-compatible via curl.

## Global Constraints

- La source obligatoire est `df_canonical_sample_depth`, version `copepod-sample-depth-v1`.
- Les seules unités élémentaires acceptées sont `abundance_ind_L` et `abundance_ind_m3`.
- Les zéros sont inclus par défaut ; `presence_only=True` exige une demande utilisateur explicite.
- m5/m6 ne sont jamais produits depuis une demande générique.
- Aucun coefficient, p-value ou interprétation biologique dans le préparateur.

---

### Task 1: Préparateur déterministe abondance–environnement

**Files:**
- Create: `core/copepod_abundance_analysis.py`
- Create: `tests/test_copepod_abundance_analysis.py`

**Interfaces:**
- Consumes: table retournée par `build_canonical_sample_depth`.
- Produces: `prepare_environment_correlation(canonical: pd.DataFrame, environmental_columns: tuple[str, ...], *, abundance_column: str = "abundance_ind_L", presence_only: bool = False) -> pd.DataFrame`.
- Produces attrs: `n_initial`, `n_retained`, `n_zero_abundance`, `n_missing_environment`, `presence_only`, `abundance_column`.

- [ ] **Step 1: Écrire le test rouge nominal**

Construire une table canonique de trois bins avec abondances `[0.01, 0.0, 0.02]` et température complète. Vérifier que les trois lignes et le zéro restent présents, que seules les colonnes clés + abondance + environnement sont retournées et que les attrs valent `3, 3, 1, 0, False`.

- [ ] **Step 2: Vérifier le RED**

Run: `pytest tests/test_copepod_abundance_analysis.py -q`

Expected: FAIL avec `ModuleNotFoundError: core.copepod_abundance_analysis`.

- [ ] **Step 3: Implémenter le chemin nominal minimal**

Valider version, colonnes et unité ; convertir abondance/environnement avec `pd.to_numeric`; conserver les zéros ; retourner une copie portant les attrs documentés.

- [ ] **Step 4: Vérifier le GREEN nominal**

Run: `pytest tests/test_copepod_abundance_analysis.py -q`

Expected: PASS du test nominal.

- [ ] **Step 5: Écrire les tests rouges des variantes et refus**

Ajouter des tests séparés pour `presence_only=True`, environnement manquant/non numérique, table non canonique, unité inconnue, abondance négative/non finie, liste environnementale vide et colonne absente.

- [ ] **Step 6: Vérifier les nouveaux RED**

Run: `pytest tests/test_copepod_abundance_analysis.py -q`

Expected: FAIL sur les validations manquantes.

- [ ] **Step 7: Implémenter les validations minimales**

Lever `ValueError` avec le champ fautif. Retirer seulement les environnements manquants, puis appliquer le filtre positif uniquement lorsque `presence_only=True`.

- [ ] **Step 8: Vérifier et committer**

Run: `pytest tests/test_copepod_abundance_analysis.py tests/test_copepod_sample_depth.py -q`

```bash
git add core/copepod_abundance_analysis.py tests/test_copepod_abundance_analysis.py
git commit -m "feat(science): add abundance correlation contract"
```

### Task 2: Routage sans m5 implicite

**Files:**
- Modify: `agents/skills/uvp_ecotaxa.md`
- Modify: `agents/copepod_system_prompt.py`
- Modify: `tests/test_skill_tool.py`
- Modify: `tests/test_agent_factory.py`

**Interfaces:**
- Consumes: `prepare_environment_correlation` de Task 1 et `df_canonical_sample_depth` de D02–D03.
- Produces: règles explicites générique/per-bin, présence seulement et m5/m6 explicite.

- [ ] **Step 1: Écrire les assertions rouges du skill et du prompt**

Exiger l'import du préparateur, l'inclusion par défaut des zéros, l'annonce de `n`/bins nuls, l'interdiction de m5/m6 générique et l'autorisation limitée aux mots `m5`, `m6` ou surface+fond/premiers+derniers 50 m.

- [ ] **Step 2: Vérifier le RED**

Run: `pytest tests/test_skill_tool.py tests/test_agent_factory.py -q`

Expected: FAIL sur les nouvelles assertions.

- [ ] **Step 3: Réécrire les règles contradictoires**

Retirer les formulations qui font de m5 le défaut de « densité/abondance/top stations ». Ajouter le template :

```python
from core.copepod_abundance_analysis import prepare_environment_correlation

analysis_df = prepare_environment_correlation(
    df_canonical_sample_depth,
    ("amundsen_temperature",),
)
```

m5/m6 restent dans une section explicit-only.

- [ ] **Step 4: Vérifier et committer**

Run: `pytest tests/test_skill_tool.py tests/test_agent_factory.py -q`

```bash
git add agents/skills/uvp_ecotaxa.md agents/copepod_system_prompt.py tests/test_skill_tool.py tests/test_agent_factory.py
git commit -m "fix(agent): require explicit UVP profile metrics"
```

### Task 3: Régression complète et preuves curl

**Files:**
- No production files unless runtime evidence exposes a regression.

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: preuves automatisées et E2E multi-tour.

- [ ] **Step 1: Lancer la suite complète**

Run: `pytest tests/ -q`

Expected: exit 0.

- [ ] **Step 2: Chat curl corrélation par défaut**

Créer/persister la table canonique de fixture, puis demander une relation température–abondance générique. Inspecter le checkpoint : le code doit appeler `prepare_environment_correlation(..., presence_only=False)` ou omettre l'option, conserver RA18/217.5 à zéro et annoncer `n=3`, `1` zéro sur la fixture complète pertinente.

- [ ] **Step 3: Tour curl présence seulement**

Demander explicitement les bins positifs. Vérifier `presence_only=True`, zéro exclu et effectif réduit annoncé.

- [ ] **Step 4: Chats curl métrique générique et m5 explicite**

Une demande générique doit utiliser `abundance_ind_L`/`abundance_ind_m3` sans m5/m6. Un chat séparé nommé m5 doit pouvoir charger la recette, la nommer et expliquer surface+fond.

- [ ] **Step 5: Vérifier l'état git**

Run: `git status --short && git log -8 --oneline`

Expected: worktree propre et commits D04–D06 présents.
