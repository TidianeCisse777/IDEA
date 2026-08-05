"""Persisted progress resolution for the Net↔UVP demonstration workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from tools.session_store import SessionStore

NetUvpPhase = Literal[
    "no_file",
    "needs_subset",
    "needs_audit",
    "audited",
    "exported",
    "enriched",
    "joined",
]
CtdStatus = Literal["verified", "unavailable", "no_match", "unknown"]


@dataclass(frozen=True)
class NetUvpWorkflowProgress:
    """Persisted comparison state and the capabilities it safely unlocks."""

    phase: NetUvpPhase
    audit_ref: str | None
    selection_name: str | None
    ctd_status: CtdStatus
    allowed_capabilities: frozenset[str]
    message: str


@dataclass(frozen=True)
class _Record:
    key: str
    meta: dict[str, Any]

    @property
    def source(self) -> str:
        return str(self.meta.get("source") or "")

    @property
    def variable_name(self) -> str | None:
        value = self.meta.get("variable_name")
        return str(value) if value else None


def _records_for_thread(store: SessionStore, thread_id: str) -> tuple[_Record, ...]:
    """Read only successful records belonging exactly to one conversation."""
    prefix = f"{thread_id}:"
    records: list[_Record] = []
    try:
        keys = store.keys()
    except Exception:
        return ()
    for key in keys:
        if key != thread_id and not key.startswith(prefix):
            continue
        try:
            entry = store.get(key) or {}
        except Exception:
            continue
        meta = entry.get("meta") or {}
        if not isinstance(meta, dict):
            continue
        if meta.get("persisted") is False or str(meta.get("status") or "").lower() in {
            "blocked",
            "error",
            "failed",
        }:
            continue
        records.append(_Record(key=key, meta=meta))
    return tuple(records)


def _ctd_status(*records: _Record | None) -> CtdStatus:
    for record in records:
        if record is None:
            continue
        value = str(record.meta.get("ctd_verification") or "").lower()
        if value in {"verified", "unavailable", "no_match"}:
            return value  # type: ignore[return-value]
    return "unknown"


def _selection_matches_audit(selection: _Record, audit: _Record) -> bool:
    """Return whether a named selection belongs to this exact audit attempt."""
    audit_ref = audit.variable_name
    audit_net = audit.meta.get("net_variable_name")
    audit_fingerprint = audit.meta.get("net_dataframe_fingerprint")
    audit_ctd_status = _ctd_status(audit)
    expected_source = {
        "verified": "net_uvp_certified_selection",
        "unavailable": "net_uvp_exploratory_selection",
    }.get(audit_ctd_status)
    exploratory_opt_in = (
        audit_ctd_status != "unavailable"
        or (
            audit.meta.get("exploratory") is True
            and audit.meta.get("allow_unverified_ctd") is True
        )
    )
    return bool(
        expected_source
        and exploratory_opt_in
        and selection.source == expected_source
        and audit_ref
        and audit_net
        and audit_fingerprint
        and selection.meta.get("audit_variable") == audit_ref
        and selection.meta.get("net_variable_name") == audit_net
        and selection.meta.get("net_dataframe_fingerprint") == audit_fingerprint
    )


def _enrichment_matches_export(enrichment: _Record, exported: _Record) -> bool:
    """Require explicit input provenance before advancing an export to enriched."""
    export_ref = exported.variable_name
    if not export_ref:
        return False
    return any(
        enrichment.meta.get(field) == export_ref
        for field in ("source_variable", "export_variable", "input_variable")
    )


def _progress(
    phase: NetUvpPhase,
    *,
    audit_ref: str | None = None,
    selection_name: str | None = None,
    ctd_status: CtdStatus = "unknown",
) -> NetUvpWorkflowProgress:
    capabilities_by_phase = {
        "no_file": frozenset({"load_file"}),
        "needs_subset": frozenset({"prepare_subset", "inspect"}),
        "needs_audit": frozenset({"audit", "inspect"}),
        "audited": frozenset({"inspect", "visualize", "export"}),
        "exported": frozenset({"inspect", "visualize", "enrich"}),
        "enriched": frozenset({"inspect", "visualize", "join"}),
        "joined": frozenset({"inspect", "visualize", "export"}),
    }
    messages = {
        "no_file": "Aucune table filet persistée.",
        "needs_subset": "La table filet est prête; préparer le sous-ensemble d'audit.",
        "needs_audit": "Un sous-ensemble d'audit persiste et attend sa vérification UVP.",
        "audited": "L'audit filet↔UVP persiste; inspection, visualisation et export restent possibles.",
        "exported": "L'export UVP lié à l'audit persiste; l'enrichissement peut continuer.",
        "enriched": "L'export UVP enrichi persiste; la jointure contrôlée peut continuer.",
        "joined": "La comparaison filet↔UVP finale persiste.",
    }
    capabilities = capabilities_by_phase[phase]
    if phase == "audited" and ctd_status == "unavailable":
        capabilities = capabilities | {"prepare_provisional_export"}
    return NetUvpWorkflowProgress(
        phase=phase,
        audit_ref=audit_ref,
        selection_name=selection_name,
        ctd_status=ctd_status,
        allowed_capabilities=capabilities,
        message=messages[phase],
    )


def resolve_net_uvp_progress(
    store: SessionStore,
    thread_id: str,
) -> NetUvpWorkflowProgress:
    """Derive comparison readiness from persisted provenance only."""
    records = _records_for_thread(store, thread_id)
    file_records = [record for record in records if record.source.startswith("file")]
    if not file_records:
        return _progress("no_file")

    prepared = [
        record
        for record in records
        if record.source == "net_uvp_audit_subset"
    ]
    audits = [record for record in records if record.source == "net_uvp_match"]
    selections = [
        record
        for record in records
        if record.source
        in {"net_uvp_certified_selection", "net_uvp_exploratory_selection"}
    ]

    audited_inputs = {
        audit.meta.get("net_variable_name") for audit in audits
    }
    completed_scope_refs = {
        scope_ref
        for record in prepared
        if record.meta.get("net_uvp_audit_input") is True
        and record.variable_name in audited_inputs
        for scope_ref in record.meta.get("scope_refs", [])
        if isinstance(scope_ref, str)
    }
    prepared_waiting_for_audit = any(
        record.variable_name not in audited_inputs
        and record.variable_name not in completed_scope_refs
        for record in prepared
    )
    if prepared_waiting_for_audit:
        return _progress("needs_audit")
    if not audits:
        return _progress("needs_subset")

    audit = audits[0]
    audit_ref = audit.variable_name if audit else None
    selection = next(
        (record for record in selections if _selection_matches_audit(record, audit)),
        None,
    )
    selection_name = (
        str(selection.meta.get("selection_name"))
        if selection and selection.meta.get("selection_name")
        else None
    )
    ctd_status = _ctd_status(selection, audit)

    joined = next(
        (
            record
            for record in records
            if record.source == "net_uvp_ecopart_certified"
            and record.meta.get("audit_variable_name") == audit_ref
            and record.meta.get("net_variable_name")
            == audit.meta.get("net_variable_name")
            and record.meta.get("uvp_enriched_variable")
        ),
        None,
    )
    if joined is not None:
        return _progress(
            "joined",
            audit_ref=audit_ref,
            selection_name=selection_name,
            ctd_status=ctd_status,
        )

    exported = next(
        (
            record
            for record in records
            if record.source == "ecotaxa_export_campaign"
            and record.meta.get("selection_name") == selection_name
        ),
        None,
    )
    enriched = next(
        (
            record
            for record in records
            if record.source.startswith("join:ecotaxa")
            and exported is not None
            and _enrichment_matches_export(record, exported)
        ),
        None,
    )
    if exported is not None and enriched is not None:
        return _progress(
            "enriched",
            audit_ref=audit_ref,
            selection_name=selection_name,
            ctd_status=ctd_status,
        )
    if exported is not None:
        return _progress(
            "exported",
            audit_ref=audit_ref,
            selection_name=selection_name,
            ctd_status=ctd_status,
        )
    return _progress(
        "audited",
        audit_ref=audit_ref,
        selection_name=selection_name,
        ctd_status=ctd_status,
    )
