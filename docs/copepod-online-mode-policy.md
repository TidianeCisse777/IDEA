# Copepod Online Mode Policy

## Current State

As of 2026-05-28, the online-source policy is implemented in three layers:

- backend persistence for a session-scoped `Mode En Ligne`;
- copepod prompt/runtime policy that only uses OGSL or Bio-ORACLE after explicit user intent;
- OGSL/Bio-ORACLE fetches are materialised as derived CSV files in the session uploads folder;
- UI controls in the account/settings surface with a visible `Mode En Ligne: ON/OFF` badge.

The initial allowlist is:

- OGSL
- Bio-ORACLE

## User Contract

The assistant may use an online source only when:

1. `Mode En Ligne` is enabled for the session.
2. The user explicitly requests OGSL or Bio-ORACLE.
3. If the request is incomplete, the assistant asks one targeted clarification question and waits.

The assistant must:

- prefer local files and local RAG when they already satisfy the task;
- avoid silent online fetches;
- materialise allowed remote data as derived CSV files in the session uploads folder;
- propose an allowed alternative when a requested source is unsupported or disabled;
- keep the source decision visible in the response.

## UI Contract

The user should be able to:

- enable or disable `Mode En Ligne` from the interface;
- see the current allowlist;
- understand whether the assistant will work locally or fetch online.

The UI currently exposes:

- `Mode En Ligne: ON/OFF` in the account/settings surface;
- the allowed source list returned by `GET /session/online-mode`.

## Backend Contract

The session routes now expose:

- `GET /session/online-mode`
- `PUT /session/online-mode`

The session store keeps the mode flag per copepod session key.

## Testing Contract

Before a live online-source test, validate:

```bash
pytest tests/test_copepod_profile.py tests/test_copepod_online_mode_policy.py tests/test_session_routes.py -q
npm test -- --runInBand frontend/__tests__/online_mode_ui.test.js
python scripts/evals/run_copepod_plan_mode_eval.py --live-online-mode --push-langfuse
```

Expected result:

- backend policy tests pass;
- copepod prompt tests mention the online-mode policy;
- UI test confirms the toggle and badge render correctly.
- the live online-mode eval verifies source-routing, clarification, and Langfuse trace logging.

## Next Live Test

The next real test should be a single explicit request, with `Mode En Ligne` enabled, such as:

- `va me chercher Bio-ORACLE pour le scénario SSP126 de 2020 à 2050 sur la variable si_mean`
- `va me chercher OGSL pour la station 12 entre 2024-01-01 et 2024-03-31 avec TE90 et PSAL`

Expected live behavior:

- if the request is explicit and complete, the assistant fetches the source and persists a derived CSV in the session uploads folder;
- if one required parameter is missing, the assistant asks one targeted clarification;
- if the source is not enabled, the assistant proposes an allowed alternative.
