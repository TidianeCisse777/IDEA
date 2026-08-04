# EcoPart Persistent Demo Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist EcoTaxa→EcoPart correspondences and valid downloaded EcoPart TSVs so Filet–UVP reuses local data before a remote export.

**Architecture:** A dedicated SQLite manifest and content-addressed TSV files live under `data/ecopart_cache/`. EcoPart source tools check a fresh mapping and a compatible TSV first, while the existing dry-run, CTD audit, and remote-export confirmation remain intact.

**Tech Stack:** Python (`sqlite3`, `hashlib`, `shutil`, `argparse`), pandas, pytest, existing `EcopartClient` and `SessionStore`.

## Global Constraints

- Cache root: `ECOPART_CACHE_DIR`, default `data/ecopart_cache/`; all cache content stays ignored by Git.
- Valid TSV columns: `Profile`, `Depth [m]`, `Sampled volume [L]`; invalid input creates no cache artifact.
- Immutable TSV filename: SHA-256 content digest. Provenance is always `remote_export` or `local_import`.
- Mapping TTL: `ECOPART_RESOLUTION_CACHE_TTL_SECONDS`, default 30 days; transient errors receive a short TTL.
- The scientific join stays `(sample_id, depth_bin)` and cached data never bypasses the CTD audit or a remote export confirmation.

## File Structure

- `core/ecopart_cache.py`: manifest schema, TSV import/load/search and mapping persistence.
- `tools/ecopart_sources.py`: local-first resolution and enrichment; import after remote success.
- `scripts/warmup_ecopart_demo_cache.py`: explicit scan/import/resolve CLI.
- `tests/test_ecopart_cache.py`: filesystem and SQLite cache behavior.
- `tests/test_ecopart_sources.py`: confirmed enrichment reuses compatible TSV.
- `tests/test_warmup_ecopart_demo_cache.py`: dry-run and resolution CLI behavior.

## Task 1: Content-addressed TSV repository

**Files:** create `core/ecopart_cache.py`, create `tests/test_ecopart_cache.py`.

**Interfaces:**

- `import_ecopart_tsv(source: Path, *, provenance: str, ecopart_project_id: int | None = None, ecotaxa_project_id: int | None = None) -> CachedEcopartTsv`
- `find_ecopart_tsv(*, ecopart_project_id: int | None, profile_labels: set[str]) -> CachedEcopartTsv | None`
- `load_ecopart_tsv(entry: CachedEcopartTsv) -> pd.DataFrame`

~~~python
def import_ecopart_tsv(source: Path, *, provenance: str, ecopart_project_id: int | None = None,
                       ecotaxa_project_id: int | None = None) -> CachedEcopartTsv:
    columns = set(pd.read_csv(source, sep="\t", nrows=0).columns)
    missing = {"Profile", "Depth [m]", "Sampled volume [L]"} - columns
    if missing:
        raise ValueError("TSV EcoPart invalide : " + ", ".join(sorted(missing)))
    digest = _sha256_file(source)
    target = cache_files_dir() / f"{digest}.tsv"
    if not target.exists():
        shutil.copyfile(source, target)
    return _index_tsv(target, digest, provenance, ecopart_project_id, ecotaxa_project_id)
~~~

- [ ] **Step 1: Write failing import/idempotence test.** Create a valid TSV containing one `RA62` row. Import it twice. Assert identical SHA-256, exactly one file in `cache/files`, and `profiles == ("RA62",)`. This catches a cache that duplicates data or loses profile information.

- [ ] **Step 2: Verify red.** Run `pytest tests/test_ecopart_cache.py::test_import_ecopart_tsv_deduplicates_content_and_records_profiles -v`. Expect import failure because `core.ecopart_cache` does not exist.

- [ ] **Step 3: Implement minimally.** Read only the header before creating the cache root; reject missing required columns. Hash the original bytes with SHA-256, copy once to `files/<hash>.tsv`, read unique non-null profiles, and write `tsv_entries` plus `tsv_profiles` manifest rows. Return a frozen dataclass with digest, path, profiles, provenance, project IDs, rows, and imported timestamp.

- [ ] **Step 4: Verify green.** Run the same test; expect PASS.

- [ ] **Step 5: Write failing invalid-input test.** Supply TSV with `Profile` and `Depth [m]`, but no volume. Assert `ValueError` mentions `Sampled volume` and `manifest.sqlite` does not exist. This catches validation happening after filesystem mutation.

- [ ] **Step 6: Implement pre-write validation and run `pytest tests/test_ecopart_cache.py -v`; expect PASS.**

- [ ] **Step 7: Commit.** Stage `core/ecopart_cache.py tests/test_ecopart_cache.py`; commit message `feat: add persistent EcoPart TSV cache`.

## Task 2: Fresh project mappings and deterministic cached-file selection

**Files:** modify `core/ecopart_cache.py`, modify `tests/test_ecopart_cache.py`.

**Interfaces:**

- `save_resolution(ecotaxa_project_id: int, *, ecopart_project_id: int | None, resolution: str, status: str, ttl_seconds: float) -> None`
- `load_resolution(ecotaxa_project_id: int, *, now: float | None = None) -> CachedEcopartResolution | None`
- `find_ecopart_tsv` ranks exact EcoPart project, then profile overlap, `remote_export`, newest import, then hash.

~~~python
def load_resolution(ecotaxa_project_id: int, *, now: float | None = None) -> CachedEcopartResolution | None:
    now = time.time() if now is None else now
    row = _connection().execute(
        "SELECT * FROM project_resolutions WHERE ecotaxa_project_id=? AND expires_at>?",
        (ecotaxa_project_id, now),
    ).fetchone()
    return CachedEcopartResolution.from_row(row) if row else None
~~~

- [ ] **Step 1: Write failing expiry test.** Save 17498→1063 with 60 seconds TTL; verify normal lookup returns 1063 and a lookup at `expires_at + 1` returns `None`. This catches a stale mapping being treated as permanent.

- [ ] **Step 2: Verify red.** Run `pytest tests/test_ecopart_cache.py::test_resolution_round_trip_expires -v`; expect missing API failure.

- [ ] **Step 3: Implement.** Add `project_resolutions` with project ID as primary key, `status`, result, method, cached time and expiry. `load_resolution` filters `expires_at > now`; expiry does not delete historical data.

- [ ] **Step 4: Verify green.** Run the expiry test; expect PASS.

- [ ] **Step 5: Write failing selection test.** Import an unscoped `local_import` TSV and an `ecopart_project_id=1063` `remote_export` TSV sharing profile `RA62`. Lookup for project 1063/profile RA62 must return the remote TSV. This catches a less authoritative local file winning merely by insertion order.

- [ ] **Step 6: Implement ordering and run `pytest tests/test_ecopart_cache.py -v`; expect PASS.**

- [ ] **Step 7: Commit.** Stage cache files; commit message `feat: persist EcoTaxa EcoPart resolutions`.

## Task 3: Cache-first source integration

**Files:** modify `tools/ecopart_sources.py` around imports, `_lookup_ecopart_project_for_ecotaxa`, and `enrich_ecotaxa_with_ecopart_remote`; modify `tests/test_ecopart_sources.py`.

**Interfaces:**

- `_lookup_ecopart_project_for_ecotaxa` reads `load_resolution` before its process/session caches and writes a fresh authoritative `filt_proj` result through `save_resolution`.
- `_store_cached_ecopart_dataset(thread_id, entry, *, ecotaxa_project_id, ecopart_project_id)` loads cache TSV into `df_ecopart_<id>` with metadata `cache_hit`, `cache_path`, `content_sha256`, and `cache_provenance`.
- With `confirmed=True`, enrichment calls `find_ecopart_tsv` before `start_export`. A remote success then calls `import_ecopart_tsv(..., provenance="remote_export")`.

~~~python
entry = find_ecopart_tsv(
    ecopart_project_id=ecopart_project_id,
    profile_labels=set(_candidate_ecotaxa_profile_labels(session_et["df"])),
)
if entry is not None:
    _store_cached_ecopart_dataset(thread_id, entry, ecotaxa_project_id=ecotaxa_project_id,
                                  ecopart_project_id=ecopart_project_id)
    return _perform_enrichment(thread_id, ecopart_project_id, ecotaxa_session=session_et)
~~~

- [ ] **Step 1: Write failing local-reuse test.** Seed a persistent TSV for project 1063/profile `ips_007`, session EcoTaxa project 17498 with `ips_007_1`, and a fake linked client whose `start_export` raises. Invoke confirmed enrichment. Assert no exception, local-cache wording, and session EcoPart metadata contains the seeded SHA-256. This catches an accidental remote request despite a valid local cache.

- [ ] **Step 2: Verify red.** Run `pytest tests/test_ecopart_sources.py::test_confirmed_enrichment_uses_compatible_tsv_without_starting_export -v`; expect the current remote-export path to fail via the fake.

- [ ] **Step 3: Implement the branch.** Resolve project mapping, derive profile labels with `_candidate_ecotaxa_profile_labels`, find a cache candidate, load and store it, then use the existing `_perform_enrichment`. Apply only after `confirmed=True`; dry-run text and confirmation behavior stay unchanged.

- [ ] **Step 4: Verify green.** Run the same local-reuse test; expect PASS.

- [ ] **Step 5: Write failing remote-persistence test.** Use a fake client that returns an `ips_007` TSV. Confirm enrichment, then assert a new lookup for 1063/ips_007 returns an entry with `remote_export`. This catches a remote export that is not reusable next time.

- [ ] **Step 6: Import each successful remote download before returning its artifact. Run `pytest tests/test_ecopart_sources.py -q`; expect PASS.**

- [ ] **Step 7: Commit.** Stage `tools/ecopart_sources.py tests/test_ecopart_sources.py`; commit message `feat: reuse persistent EcoPart TSV cache`.

## Task 4: Explicit warmup CLI and Filet–UVP coverage

**Files:** create `scripts/warmup_ecopart_demo_cache.py`, create `tests/test_warmup_ecopart_demo_cache.py`, modify `tests/test_enrichment_workflows_integration.py`, `.env.example`, and `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`.

**Interfaces:** `python scripts/warmup_ecopart_demo_cache.py --tsv-root /tmp/copepod_downloads --tsv-root data/demo --resolve-ecotaxa-cache data/ecotaxa_cache.sqlite --apply`.

~~~python
parser.add_argument("--tsv-root", action="append", type=Path, default=[])
parser.add_argument("--resolve-ecotaxa-cache", type=Path)
parser.add_argument("--apply", action="store_true")
if not args.apply:
    return _report_header_only(args.tsv_root)
~~~

- [ ] **Step 1: Write failing dry-run test.** A root containing one valid TSV should return zero, print `1 TSV EcoPart valide`, and not create a cache. This catches an accidental write or network access in dry-run.

- [ ] **Step 2: Verify red.** Run `pytest tests/test_warmup_ecopart_demo_cache.py::test_warmup_dry_run_reports_valid_tsv_without_creating_cache -v`; expect missing CLI failure.

- [ ] **Step 3: Implement CLI.** `--tsv-root` is repeatable; `--resolve-ecotaxa-cache` is optional; `--apply` defaults false. Dry-run reads headers only. Apply imports valid files then reads `projects_cache` and, after `EcopartClient.login`, resolves each project via `search_samples(ecotaxa_project_id=...)` and `get_sample_metadata`; it persists only authoritative matching IDs and logs counts, never values or credentials.

- [ ] **Step 4: Verify green.** Run dry-run test; expect PASS.

- [ ] **Step 5: Write apply/resolution test.** Seed an EcoTaxa SQLite with 17498, inject a fake client returning EcoPart 1063, run apply, then assert `load_resolution(17498).ecopart_project_id == 1063` and a valid TSV was imported. Verify it fails first, then implement and rerun `pytest tests/test_warmup_ecopart_demo_cache.py -v` to PASS.

- [ ] **Step 6: Write Filet–UVP integration test.** Seed 17498→1063 and a compatible TSV, run confirmed enrichment, and assert tool provenance has `cache_hit is True`. Verify red before exposing provenance, then green after preserving cache fields in the result artifact.

- [ ] **Step 7: Document variables and command, run `pytest tests/test_ecopart_cache.py tests/test_warmup_ecopart_demo_cache.py tests/test_ecopart_sources.py tests/test_enrichment_workflows_integration.py -q && git diff --check`; expect PASS. Commit `feat: warm persistent EcoPart demo cache`.**
