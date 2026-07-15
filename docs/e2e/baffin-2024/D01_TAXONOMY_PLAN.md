# D01 Strict Copepoda Hierarchy Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer les listes manuelles de taxons par un masque Copepoda strict fondé sur `object_annotation_hierarchy`.

**Architecture:** Une fonction pure dans `core/copepod_taxonomy.py` valide la colonne requise et compare les nœuds complets de la hiérarchie. Le skill UVP importe cette fonction dans le code `run_pandas`; aucune résolution réseau ni liste locale de descendants n'est utilisée.

**Tech Stack:** Python 3.13, pandas, pytest, LangGraph/FastAPI pour la validation curl.

## Global Constraints

- TDD strict : observer l'échec avant l'implémentation.
- `object_annotation_hierarchy` est obligatoire.
- Aucun fallback par mots-clés, liste manuelle, EcoTaxa ou WoRMS.
- Aucun calcul d'abondance, de bin ou de corrélation dans D01.

---

### Task 1: Résolveur hiérarchique pur

**Files:**
- Create: `core/copepod_taxonomy.py`
- Create: `tests/test_copepod_taxonomy.py`

**Interfaces:**
- Consumes: `pandas.DataFrame` contenant `object_annotation_hierarchy`.
- Produces: `copepod_hierarchy_mask(df: pd.DataFrame, hierarchy_column: str = "object_annotation_hierarchy") -> pd.Series`.

- [ ] **Step 1: Write the failing tests**

```python
def test_copepod_hierarchy_mask_includes_descendants_and_excludes_substrings():
    df = pd.DataFrame({"object_annotation_hierarchy": [
        "Biota>Animalia>Arthropoda>Copepoda>Calanoida",
        "Biota>Animalia>NotCopepoda>Example",
        None,
    ]})
    assert copepod_hierarchy_mask(df).tolist() == [True, False, False]

def test_copepod_hierarchy_mask_requires_hierarchy_column():
    with pytest.raises(ValueError, match="object_annotation_hierarchy"):
        copepod_hierarchy_mask(pd.DataFrame({"object_annotation_category": ["Calanoida"]}))
```

- [ ] **Step 2: Run tests to verify RED**

Run: `pytest tests/test_copepod_taxonomy.py -q`

Expected: collection/import failure because `core.copepod_taxonomy` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
import re
import pandas as pd

_HIERARCHY_SEPARATOR = re.compile(r"\s*[>|;/]\s*")

def copepod_hierarchy_mask(df, hierarchy_column="object_annotation_hierarchy"):
    if hierarchy_column not in df.columns:
        raise ValueError(
            "Sélection Copepoda refusée : la colonne "
            f"`{hierarchy_column}` est requise."
        )
    def belongs(value):
        if pd.isna(value):
            return False
        return any(node.casefold() == "copepoda" for node in _HIERARCHY_SEPARATOR.split(str(value).strip()))
    return df[hierarchy_column].map(belongs).astype(bool)
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `pytest tests/test_copepod_taxonomy.py -q`

Expected: all tests pass.

### Task 2: Routage du skill UVP

**Files:**
- Modify: `agents/skills/uvp_ecotaxa.md`
- Test: `tests/test_skill_tool.py`

**Interfaces:**
- Consumes: `copepod_hierarchy_mask` de Task 1.
- Produces: templates d'analyse qui importent le helper et refusent une table sans hiérarchie.

- [ ] **Step 1: Write the failing skill-content test**

```python
def test_uvp_skill_requires_strict_hierarchy_resolver():
    content = Path("agents/skills/uvp_ecotaxa.md").read_text()
    assert "from core.copepod_taxonomy import copepod_hierarchy_mask" in content
    assert "copepod_keywords" not in content
    assert "cop_cats =" not in content
```

- [ ] **Step 2: Run test to verify RED**

Run: `pytest tests/test_skill_tool.py::test_uvp_skill_requires_strict_hierarchy_resolver -q`

Expected: failure because manual lists are still present.

- [ ] **Step 3: Replace manual filters in the skill**

Every copepod template starts with:

```python
from core.copepod_taxonomy import copepod_hierarchy_mask

cop = df.loc[copepod_hierarchy_mask(df)].copy()
```

The prose explicitly requires a refusal when the hierarchy column is missing.

- [ ] **Step 4: Run targeted tests**

Run: `pytest tests/test_copepod_taxonomy.py tests/test_skill_tool.py tests/test_agent_factory.py -q`

Expected: all pass.

### Task 3: Validation réelle par curl

**Files:**
- No production file changes.

**Interfaces:**
- Consumes: running agent at `http://localhost:8000`.
- Produces: captured evidence that RA18/Calanoida is included through hierarchy only.

- [ ] **Step 1: Start a fresh validation conversation**

Use a stable chat id dedicated to D01 and load/export a small EcoTaxa dataset containing the three project-14859 samples if it is not already available.

- [ ] **Step 2: Ask for a strict taxonomy audit**

Prompt: `Compte les objets Copepoda des trois samples en utilisant exclusivement object_annotation_hierarchy. N'utilise aucune liste de noms.`

Expected: the agent imports the resolver, includes Calanoida through its hierarchy and reports RA18 consistently.

- [ ] **Step 3: Validate explicit refusal**

Run the resolver against a derived table without `object_annotation_hierarchy`.

Expected: refusal naming the missing column; no keyword fallback.

- [ ] **Step 4: Run regression suite and commit**

Run: `pytest tests/`

Expected: 0 failures.

Commit: `fix(taxonomy): require hierarchy for Copepoda selection`.
