# EcoTaxa Project Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight EcoTaxa project preview tool and route informational project requests to it instead of launching full exports.

**Architecture:** `EcotaxaClient.preview_project()` combines project metadata, classification summary, and a ten-object query into a normalized structure. `preview_ecotaxa_project` renders that structure as Markdown without touching the analysis session, while prompt and skill contracts assign distinct intents to list, preview, and export tools.

**Tech Stack:** Python 3.13, requests, LangChain tools, pytest, unittest.mock, Markdown.

---

### Task 1: Client Preview Contract

**Files:**
- Modify: `tools/ecotaxa_client.py`
- Test: `tests/test_copepod_sources.py`

- [ ] Write a failing test asserting the metadata GET, summary POST, limited query POST, and normalized result.
- [ ] Run the single test and confirm failure because `preview_project` is absent.
- [ ] Implement `preview_project(project_id, limit=10)` with fields `obj.orig_id,obj.objdate,obj.depth_min,txo.display_name`.
- [ ] Run the test and confirm it passes.

### Task 2: LangChain Preview Tool

**Files:**
- Modify: `tools/copepod_sources.py`
- Test: `tests/test_copepod_sources.py`

- [ ] Write failing tests for tool registration, Markdown rendering, empty objects, controlled errors, and no session mutation.
- [ ] Run the tests and confirm failure because the tool is absent.
- [ ] Implement `preview_ecotaxa_project(project_id)` and return it with the existing source tools.
- [ ] Run the tests and confirm they pass.

### Task 3: Agent Routing

**Files:**
- Modify: `agents/copepod_system_prompt.py`
- Modify: `agents/skills/ecotaxa_query.md`
- Test: `tests/test_agent_factory.py`
- Test: `tests/test_copepod_sources.py`

- [ ] Write failing contract tests for list/preview/export routing.
- [ ] Run the tests and confirm the routing text is incomplete.
- [ ] Add explicit examples and prohibit full export for preview-only requests.
- [ ] Run the tests and confirm they pass.

### Task 4: Verification and Reload

**Files:**
- Verify all modified files.

- [ ] Run focused tests for source tools, agent factory, CLI, and streaming.
- [ ] Run `git diff --check`.
- [ ] Call the preview tool against project `14622`.
- [ ] Restart `com.neolab.idea.serve` and verify `/docs` returns `200`.
