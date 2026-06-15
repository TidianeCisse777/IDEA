# MCP EcoTaxa M2 Catalogue Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add nine read-only tools to navigate EcoTaxa projects, samples, acquisitions, objects, and taxonomy without the future SQLite cache.

**Architecture:** Thin HTTP methods mirror EcoTaxa OpenAPI 0.0.45. Pure modules in `core/ecotaxa_browser/` own validation and normalization; FastMCP wrappers delegate to those public functions. Every tool stays below three EcoTaxa requests.

**Tech Stack:** Python 3.13, requests, VCR.py, FastMCP 3.4, pytest.

---

### Task 1: Project detail tracer bullet
- [x] RED: test `get_project(project_id)` through its public core interface.
- [x] GREEN: add raw project detail/stats methods and normalized core response.
- [x] Verify offline with a sanitized VCR cassette.

### Task 2: Sample navigation
- [x] RED-GREEN: `list_project_samples(project_id, page, page_size)`.
- [x] RED-GREEN: `get_sample(sample_id)`.

### Task 3: Acquisition navigation
- [x] RED-GREEN: `list_project_acquisitions(project_id)`.
- [x] RED-GREEN: `get_acquisition(acquisition_id)`.

### Task 4: Object navigation
- [x] RED-GREEN: `list_sample_objects(...)` in two requests.
- [x] RED-GREEN: contextual `get_object(object_id)` in exactly three requests.

### Task 5: Taxonomy navigation
- [x] RED-GREEN: `taxonomy_node(None|taxon_id)`.
- [x] RED-GREEN: `search_taxa(query)` via `/taxon_set/search`.

### Task 6: FastMCP facade
- [x] Register and call all nine M2 tools with JSON-serializable results.

### Task 7: Validation and documentation
- [x] Run focused tests, Docker walkthrough, and full-suite comparison.
- [x] Update the PRD with evidence-backed gates.
- [x] Inspect cassettes for secrets, then commit and push.
