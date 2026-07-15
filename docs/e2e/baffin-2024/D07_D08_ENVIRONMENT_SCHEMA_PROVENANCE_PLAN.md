# Environment Schema and Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Résoudre les colonnes environnementales avant réseau et attacher une provenance Amundsen structurée, validée et visible à chaque enrichissement réussi.

**Architecture:** Deux composants purs vivent dans `core/environment_resolver/`: un schéma résolu immuable et un constructeur de provenance JSON. Le shell `run_point_enrichment` résout une fois le schéma et le transmet à l'issue ; l'épilogue Amundsen construit, stocke et affiche la provenance.

**Tech Stack:** Python 3, dataclasses, pandas, pytest, LangChain tools, curl/OpenAI-compatible API.

## Global Constraints

- Priorité temps exacte : `object_date`, `sampledatetime`, puis les alias existants.
- Tout override absent est refusé avant `_fetch_amundsen_bbox`.
- Une réussite Amundsen exige dataset, URL HTTP(S), date UTC, paramètres, schéma, variables et couverture cohérente.
- Le même dictionnaire de provenance est stocké et rendu.
- Aucun credential ni nom interne de tool dans la réponse utilisateur.

---

### Task 1: Contrat pur de résolution de schéma

**Files:**
- Create: `core/environment_resolver/schema.py`
- Modify: `core/environment_resolver/column_detection.py`
- Modify: `core/environment_resolver/__init__.py`
- Create: `tests/test_environment_schema.py`

**Interfaces:**
- Produces: `ResolvedEnvironmentSchema` avec `to_dict()`.
- Produces: `resolve_environment_schema(dataframe, *, latitude_column=None, longitude_column=None, time_column=None, depth_column=None, require_time=True, require_depth=False)`.

- [ ] Écrire les tests rouges : priorité `object_date`, fallback `sampledatetime`, overrides case-insensitive, override absent, colonnes requises absentes, profondeur optionnelle.
- [ ] Run: `pytest tests/test_environment_schema.py -q` — Expected: import failure.
- [ ] Implémenter la dataclass, la résolution explicite/détectée et ajouter `sampledatetime` en seconde position temporelle.
- [ ] Run: `pytest tests/test_environment_schema.py tests/test_environment_resolver.py -q` — Expected: PASS.
- [ ] Commit:

```bash
git add core/environment_resolver tests/test_environment_schema.py
git commit -m "feat(enrichment): add deterministic schema resolver"
```

### Task 2: Contrat pur de provenance

**Files:**
- Create: `core/environment_resolver/provenance.py`
- Modify: `core/environment_resolver/__init__.py`
- Create: `tests/test_enrichment_provenance.py`

**Interfaces:**
- Produces: `build_enrichment_provenance(*, source, dataset_id, dataset_url, completed_at, parameters, resolved_schema, variables, coverage) -> dict`.

- [ ] Écrire le test rouge nominal avec date UTC et couverture `8/10`, puis les refus dataset/URL/date/taux/statuts incohérents.
- [ ] Run: `pytest tests/test_enrichment_provenance.py -q` — Expected: import failure.
- [ ] Implémenter validation et sérialisation déterministes.
- [ ] Run: `pytest tests/test_enrichment_provenance.py -q` — Expected: PASS.
- [ ] Commit:

```bash
git add core/environment_resolver tests/test_enrichment_provenance.py
git commit -m "feat(enrichment): add structured provenance contract"
```

### Task 3: Intégration au shell et à Amundsen

**Files:**
- Modify: `tools/point_enrichment.py`
- Modify: `tools/amundsen_sources.py`
- Modify: `tests/test_amundsen_sources.py`
- Modify: `tests/test_point_enrichment.py`

**Interfaces:**
- `EnrichmentOutcome.resolved_schema: ResolvedEnvironmentSchema | None`.
- Meta dataset: `provenance` identique au bloc rendu.

- [ ] Écrire les tests rouges : `object_date` résolu, override `sampledatetime` absent sans fetch, provenance complète dans meta/réponse, URL/dataset obligatoires.
- [ ] Run: `pytest tests/test_point_enrichment.py tests/test_amundsen_sources.py -q` — Expected: nouvelles assertions FAIL.
- [ ] Remplacer la détection dispersée du shell par `resolve_environment_schema`; transporter le résultat dans `EnrichmentOutcome`.
- [ ] Construire la provenance Amundsen après couverture, la stocker avant rendu et afficher `Provenance :` + `Source : <URL>`.
- [ ] Run: `pytest tests/test_point_enrichment.py tests/test_amundsen_sources.py -q` — Expected: PASS.
- [ ] Commit:

```bash
git add tools/point_enrichment.py tools/amundsen_sources.py tests/test_point_enrichment.py tests/test_amundsen_sources.py
git commit -m "fix(amundsen): resolve schema and persist provenance"
```

### Task 4: Régression et curl

**Files:**
- No production changes unless runtime evidence identifies a tested defect.

- [ ] Run: `pytest tests/ -q` — Expected: exit 0.
- [ ] Chat curl positif sur fixture `object_date` : vérifier colonnes résolues, provenance, URL, couverture et meta de session.
- [ ] Chat curl négatif avec `time_column="sampledatetime"` absent : vérifier refus et absence de fetch dans trace/runtime.
- [ ] Run: `git status --short && git log -10 --oneline` — Expected: worktree propre.
