# Offline Cartography Implementation Plan

> **For agentic workers:** Execute this plan inline. The user explicitly waived test-first development; add regression coverage during implementation and run every verification before completion.

**Goal:** Make every fresh local or Docker installation render IDEA's existing Cartopy maps without runtime downloads and persist generated PNG files.

**Architecture:** Vendor the four Natural Earth 110m shapefiles already consumed by the graph templates. A focused runtime module validates and registers those files through Cartopy's `pre_existing_data_dir`, while a shared path module gives the graph producer and FastAPI server one persistent output directory.

**Tech Stack:** Python 3.13, Cartopy 0.25+, Matplotlib, FastAPI, Docker Compose, pytest.

## Global Constraints

- Support both `pip install -r requirements.txt` and Docker installations.
- Do not download cartographic assets at map-render time.
- Vendor only land, ocean, coastline, and national-boundary Natural Earth layers at 110m.
- Keep the 142 MB IHO source shapefile excluded.
- Do not trigger or bundle scientific source downloads.
- The user explicitly waived TDD for this implementation.

---

### Task 1: Vendor and validate the minimal Natural Earth assets

**Files:**
- Create: `core/cartography.py`
- Create: `assets/cartopy/README.md`
- Create: `assets/cartopy/shapefiles/natural_earth/{physical,cultural}/ne_110m_*`
- Modify: `.gitignore`
- Modify: `Dockerfile`
- Create: `tests/test_cartography.py`

**Interfaces:**
- Produces: `configure_offline_cartopy(data_dir: Path | None = None) -> Path`
- Produces: `validate_cartopy_assets(data_dir: Path | None = None) -> tuple[Path, ...]`

- [ ] Copy only the four required shapefile families from the local Cartopy cache and record their source and public-domain status.
- [ ] Implement an exact manifest for required extensions and a clear `CartographyAssetsError` on missing files.
- [ ] Configure `cartopy.config["pre_existing_data_dir"]` to the vendored root.
- [ ] Add regression tests for successful validation, missing-file diagnostics, and real rendering while every Cartopy downloader is blocked.
- [ ] Include the asset tree in Git and Docker outside `/app/data`, while preserving the existing exclusions for session data and IHO sources.
- [ ] Add a Docker build-time command that validates the baked assets.

### Task 2: Centralize and persist graph output

**Files:**
- Create: `core/runtime_paths.py`
- Modify: `tools/data_tools.py`
- Modify: `serve.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `tests/test_data_tools.py`
- Modify: `tests/test_serve_streaming.py`

**Interfaces:**
- Produces: `graphs_dir() -> Path`, resolved from `GRAPHS_DIR` or `<repo>/data/graphs`.
- Consumes: `configure_offline_cartopy()` immediately before graph execution.

- [ ] Replace the duplicated `/tmp/copepod_graphs` constants with the shared resolver.
- [ ] Configure Cartopy before executing user graph code.
- [ ] Set `GRAPHS_DIR=/app/data/graphs` in development and production Compose services so the existing `copepod_data` volume persists images.
- [ ] Add regression coverage proving producer/server path agreement and offline `run_graph` rendering.

### Task 3: Document and verify both installation paths

**Files:**
- Modify: `PARTAGE.md`
- Modify: `ARCHITECTURE.md`
- Modify: `TOOLS.md`

- [ ] Document the four bundled layers, offline behavior, persistence path, and distinction from scientific datasets and IHO build sources.
- [ ] Run focused cartography, graph, server, and configuration tests.
- [ ] Render a real map with an empty temporary Cartopy cache and a downloader that raises on any network attempt.
- [ ] Run `git diff --check`, inspect the vendored asset size, and run a Docker build when the local Docker daemon is available.
