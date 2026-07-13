# EcoPart Confirmation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empêcher tout export, téléchargement ou changement de session pendant le dry-run de l'enrichissement EcoTaxa–EcoPart, tout en conservant l'auto-chargement après confirmation.

**Architecture:** L'interface LangChain reste inchangée. Le tool sépare son chemin de planification sans effet de bord de son chemin d'exécution confirmé; l'auto-chargement EcoTaxa est déplacé derrière le garde `confirmed`.

**Tech Stack:** Python 3.13, LangChain tools, pandas, pytest, `unittest.mock`.

## Global Constraints

- Respecter CT-AG-06 : aucune opération coûteuse avant confirmation explicite.
- TDD : test en échec avant modification de l'implémentation.
- Ne pas modifier la jointure canonique `(sample_id, depth_bin)`.
- Ne pas déplacer le routage métier hors de `agents/copepod_system_prompt.py`.
- Ne jamais exposer de credentials.

---

### Task 1: Verrouiller le dry-run sans EcoTaxa en session

**Files:**
- Modify: `tests/test_ecopart_sources.py`
- Modify: `tools/ecopart_sources.py`

**Interfaces:**
- Consumes: `make_ecopart_tools(thread_id)` et le tool existant `enrich_ecotaxa_with_ecopart_remote(ecotaxa_project_id, ecopart_project_id, confirmed)`.
- Produces: invariant `confirmed=False` sans appel à `EcotaxaClient`/export EcoPart et sans écriture dans le store.

- [ ] **Step 1: Write the failing regression test**

Ajouter un test qui vide les clés du thread, invoque le tool avec
`ecotaxa_project_id=14853` et `confirmed=False`, puis vérifie :

```python
mock_et.start_export.assert_not_called()
mock_et.wait_for_job.assert_not_called()
mock_et.download_tsv.assert_not_called()
mock_ep.start_export.assert_not_called()
mock_ep.download_tsv.assert_not_called()
assert _store.get("thread-dry-autoload") is None
assert _store.get("thread-dry-autoload:ecotaxa") is None
assert "dry-run" in result.lower()
assert "sera exporté après confirmation" in result
```

- [ ] **Step 2: Run the regression test and confirm the current violation**

Run:

```bash
pytest tests/test_ecopart_sources.py::test_enrich_remote_dry_run_with_project_does_not_auto_load_ecotaxa -v
```

Expected: FAIL because `EcotaxaClient.start_export` is called before the confirmation guard.

- [ ] **Step 3: Move auto-load behind the confirmation guard**

Dans `enrich_ecotaxa_with_ecopart_remote`, traiter l'absence de session ainsi :

```python
session_et = _store.get(f"{thread_id}:ecotaxa")
if session_et is None and not confirmed:
    if ecotaxa_project_id is None:
        return "Données EcoTaxa manquantes ..."
    return (
        f"Plan d'enrichissement EcoPart (dry-run) — projet EcoTaxa "
        f"{ecotaxa_project_id}.\n"
        f"Après confirmation, le projet EcoTaxa {ecotaxa_project_id} sera "
        "exporté, puis le projet EcoPart correspondant sera téléchargé ..."
    )

if session_et is None and ecotaxa_project_id is not None:
    _ensure_ecotaxa_project_loaded(thread_id, int(ecotaxa_project_id))
    session_et = _store.get(f"{thread_id}:ecotaxa")
```

Le texte final doit conserver `confirmed=True`, annoncer explicitement que rien
n'a été téléchargé et ne pas instancier de client avant le retour du dry-run.

- [ ] **Step 4: Run the focused dry-run tests**

Run:

```bash
pytest tests/test_ecopart_sources.py -k "dry_run" -v
```

Expected: PASS for the existing loaded-session dry-run and the new no-session dry-run.

- [ ] **Step 5: Run the confirmed auto-load test**

Run:

```bash
pytest tests/test_ecopart_sources.py::test_enrich_remote_auto_loads_ecotaxa_when_project_named_but_not_in_session -v
```

Expected: PASS; the confirmed path still calls the EcoTaxa export once and completes the join.

- [ ] **Step 6: Commit the implementation slice**

```bash
git add tests/test_ecopart_sources.py tools/ecopart_sources.py
git commit -m "fix(ecopart): enforce confirmation before auto-load"
```

### Task 2: Vérifier tous les workflows EcoTaxa–EcoPart

**Files:**
- Verify: `tests/test_ecopart_sources.py`
- Verify: `tests/test_enrichment_workflows_integration.py`
- Verify: `tests/test_agent_factory.py`

**Interfaces:**
- Consumes: implémentation corrigée du Task 1.
- Produces: preuve que les workflows local, distant et full remote restent compatibles avec le contrat agent.

- [ ] **Step 1: Run the complete EcoPart unit suite**

```bash
LANGCHAIN_TRACING_V2=false pytest tests/test_ecopart_sources.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run enrichment integration tests**

```bash
LANGCHAIN_TRACING_V2=false pytest tests/test_enrichment_workflows_integration.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run the agent construction tests**

```bash
LANGCHAIN_TRACING_V2=false pytest tests/test_agent_factory.py -q
```

Expected: all tests pass and the EcoPart tool remains registered.

- [ ] **Step 4: Inspect the final diff and status**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional files or commits are present.
