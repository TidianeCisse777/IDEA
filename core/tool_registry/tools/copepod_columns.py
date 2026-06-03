from core.tool_registry.registry import Tool, registry

_code = '''
def describe_column(column_name, source_hint=None, session_id=None):
    """Return the definition, unit, confidence and critical notes for a column name.

    Queries the RAG knowledge base (colonnes_instruments.md, colonnes_sources.md,
    colonnes_labo.md) to find the authoritative definition. Never invents a
    definition — returns confidence="unknown" when the column is not found.

    Use this when:
    - The user asks "que signifie <column_name> ?"
    - You need to verify a column's unit before a calculation
    - You need to explain a morphometric or instrument column

    Args:
        column_name (str): Exact column name (e.g. "acq_pixel", "object_feret").
        source_hint (str, optional): Narrow the search (e.g. "ecotaxa", "ecopart").
        session_id (str, optional): Session ID for Langfuse tracing.

    Returns:
        dict:
            column          — echoes column_name
            definition      — human-readable description
            unit            — unit string or None
            confidence      — "reliable" | "exploratory" | "unusable" | "unknown"
            critical_notes  — list of important caveats
            rag_doc_ref     — source document filename (e.g. "colonnes_instruments.md")
            source_file     — same as rag_doc_ref
    """
    import re

    def _trace(res):
        try:
            import os as _os
            _sk = _os.environ.get("IDEA_RUNTIME_SESSION_KEY")
            from core.copepod_observability import trace_copepod_tool_call
            trace_copepod_tool_call(
                "describe_column",
                session_key=_sk,
                input={"column_name": column_name, "source_hint": source_hint},
                output={
                    "confidence": res.get("confidence"),
                    "unit": res.get("unit"),
                    "rag_doc_ref": res.get("rag_doc_ref"),
                },
            )
        except Exception:
            pass
        return res

    if not column_name or not column_name.strip():
        return {
            "column": column_name,
            "definition": "Empty column name.",
            "unit": None,
            "confidence": "unknown",
            "critical_notes": [],
            "rag_doc_ref": None,
            "source_file": None,
        }

    _NOT_FOUND = {
        "column": column_name,
        "definition": f"Column \'{column_name}\' not found in knowledge base.",
        "unit": None,
        "confidence": "unknown",
        "critical_notes": [],
        "rag_doc_ref": None,
        "source_file": None,
    }

    query = f"{column_name} signification unité définition"
    if source_hint:
        query += f" {source_hint}"

    try:
        from core.copepod_rag.query import query_copepod_rag
        # top_k=30: methodes_calcul.md chunks (formulae mentioning a column
        # name inline) tend to crowd the top of the result list. The actual
        # definition row in colonnes_labo.md / colonnes_instruments.md can
        # sit as deep as position 8–12 depending on the column. The
        # downstream code sorts results by doc priority (colonnes_labo.md
        # first) and stops at the first chunk that yields an actual table
        # row, so the extra results are cheap.
        results = query_copepod_rag(query, top_k=30, session_id=session_id)
    except Exception:
        return _trace(_NOT_FOUND)

    def _clean_cell(value):
        return re.sub("[*`]+", "", value).strip()

    def _normalise_unit(value):
        unit = _clean_cell(value)
        if not unit or unit in {"-", "—", "–", "None"}:
            return None
        return unit

    def _row_definition(content):
        """Return (definition, unit) from common RAG markdown table layouts."""
        for line in content.splitlines():
            if "`" + column_name.lower() + "`" not in line.lower():
                continue
            cells = [_clean_cell(c) for c in line.strip().strip("|").split("|")]
            if len(cells) < 3:
                continue
            col_idx = next((i for i, c in enumerate(cells) if c.lower() == column_name.lower()), None)
            if col_idx is None:
                continue

            # Supported layouts:
            # | Colonne | Description | Unité |
            # | Colonne | Type | Unité | Description |
            # | # | Colonne | Description | Unité |
            after = cells[col_idx + 1 :]
            if len(after) >= 3:
                return after[2], _normalise_unit(after[1])
            if len(after) >= 2:
                return after[0], _normalise_unit(after[1])
        return None

    exact_rows = []
    for index, r in enumerate(results):
        content = r.get("content", "")
        parsed = _row_definition(content)
        if parsed:
            exact_rows.append((0 if r.get("doc") == "colonnes_labo.md" else 1, index, r, parsed, content))

    for _, _, r, (raw_def, unit), content in sorted(exact_rows, key=lambda item: (item[0], item[1])):
        # Remove markdown bold markers
        definition = re.sub("[*]+", "", raw_def).strip()

        critical_notes = _extract_critical_notes(column_name, definition, content)

        return _trace({
            "column": column_name,
            "definition": definition,
            "unit": unit,
            "confidence": "reliable",
            "critical_notes": critical_notes,
            "rag_doc_ref": r.get("doc"),
            "source_file": r.get("doc"),
        })

    # Column name appears in a chunk but not as a table row
    for r in results:
        if column_name.lower() in r.get("content", "").lower():
            return _trace({
                "column": column_name,
                "definition": f"Mentioned in {r.get('title', r.get('doc', 'RAG'))}.",
                "unit": None,
                "confidence": "exploratory",
                "critical_notes": [],
                "rag_doc_ref": r.get("doc"),
                "source_file": r.get("doc"),
            })

    return _trace(_NOT_FOUND)


def _extract_critical_notes(column_name, definition, chunk_content):
    """Extract critical caveats for a column from its definition and surrounding text."""
    notes = []
    col_lower = column_name.lower()
    def_lower = definition.lower()

    # acq_pixel: required for pixel→mm conversion
    if "acq_pixel" in col_lower:
        notes.append(
            "acq_pixel requis pour convertir les mesures objet de pixels en mm — "
            "toujours vérifier que la valeur est non nulle avant calcul de taille."
        )

    # process_pixel: also a pixel dimension
    if "process_pixel" in col_lower:
        notes.append("process_pixel est la dimension pixel après Zooprocess — "
                     "utiliser acq_pixel pour les mesures brutes.")

    # Columns flagged as key or required
    if "clé" in def_lower or "requis" in def_lower or "★" in definition:
        notes.append(definition)

    # Morphometric columns in pixels: need conversion
    if any(k in col_lower for k in ["object_area", "object_feret", "object_major",
                                     "object_minor", "object_esd", "object_width"]):
        notes.append(
            "Mesure en pixels — diviser par acq_pixel pour obtenir des mm."
        )

    return notes


def check_column_for_calc(column_roles, calculation, session_id=None):
    """Check whether the semantic roles required for a calculation are present.

    Works on the OUTPUT of infer_column_roles() — roles, not exact column names.
    This allows the tool to work on any file regardless of column naming conventions.

    Typical flow:
        1. inspect_file(path)           → get column descriptors
        2. infer_column_roles(columns)  → get role assignments
        3. For unknown columns: describe_column(name) → add context
        4. check_column_for_calc(roles, "concentration") → feasibility check

    The LLM decides what the unmatched columns mean — this tool only checks
    whether the required semantic roles are covered.

    Args:
        column_roles (dict): Output of infer_column_roles() with a "roles" key.
                             Each role entry has: role, column, confidence, evidence.
        calculation (str): Calculation name. Supported: "concentration", "biovolume",
                           "biomasse", "lipid_index", "esd_mm".
        session_id (str, optional): Session ID for Langfuse tracing.

    Returns:
        dict:
            feasible        — True if all required roles are covered
            required_roles  — semantic roles needed for this calculation
            present_roles   — roles found in column_roles
            missing_roles   — roles absent from column_roles
            role_hints      — for each missing role: what kind of column provides it
            blocking_reason — human-readable explanation when feasible=False, else None
    """
    # Required SEMANTIC ROLES per calculation (source-agnostic)
    REQUIRED = {
        "concentration": {
            "roles": ["sample_volume", "depth", "profile_id"],
            "hints": {
                "sample_volume": (
                    "Volume échantillonné — ex. 'Sampled volume [L]' dans EcoPart, "
                    "ou toute colonne dont le RAG confirme qu'elle contient un volume en L ou m³."
                ),
                "depth":         "Profondeur — ex. 'object_depth_min', 'Depth [m]'.",
                "profile_id":    "Identifiant de profil — ex. 'Profile' (EcoPart), 'obj_orig_id' (EcoTaxa).",
            },
        },
        "biovolume": {
            "roles": ["size_or_morphometry", "pixel_calibration"],
            "hints": {
                "size_or_morphometry": (
                    "Surface ou dimension de l'objet — ex. 'object_area', 'object_esd'."
                ),
                "pixel_calibration": (
                    "Dimension d'un pixel en mm — acq_pixel (ou process_pixel). "
                    "Requis pour convertir les mesures pixels en mm."
                ),
            },
        },
        "biomasse": {
            "roles": ["sample_volume", "depth", "profile_id", "size_or_morphometry", "pixel_calibration"],
            "hints": {
                "sample_volume":       "Volume échantillonné (EcoPart).",
                "depth":               "Profondeur.",
                "profile_id":          "Identifiant profil.",
                "size_or_morphometry": "Surface objet pour calcul de biovolume.",
                "pixel_calibration":   "acq_pixel pour conversion pixels → mm.",
            },
        },
        "lipid_index": {
            "roles": ["lab_measurement"],
            "hints": {
                "lab_measurement": (
                    "Mesures de laboratoire (lipides, masse sèche, carbone) — "
                    "fichier labo requis, non présent dans EcoTaxa/EcoPart."
                ),
            },
        },
        "esd_mm": {
            "roles": ["size_or_morphometry", "pixel_calibration"],
            "hints": {
                "size_or_morphometry": "Diamètre ou surface objet — ex. 'object_esd', 'object_area'.",
                "pixel_calibration":   "acq_pixel pour la conversion pixels → mm.",
            },
        },
    }

    calc_lower = calculation.lower().strip()

    if calc_lower not in REQUIRED:
        return {
            "feasible": False,
            "required_roles": [],
            "present_roles": [],
            "missing_roles": [],
            "role_hints": {},
            "blocking_reason": (
                f"Calcul '{calculation}' non reconnu. "
                f"Calculs supportés : {', '.join(REQUIRED.keys())}."
            ),
        }

    spec = REQUIRED[calc_lower]
    required_roles = spec["roles"]

    # Extract present roles from the column_roles dict
    if isinstance(column_roles, dict):
        roles_list = column_roles.get("roles", [])
    else:
        roles_list = []

    present_role_names = {r["role"] for r in roles_list if isinstance(r, dict)}

    present = [r for r in required_roles if r in present_role_names]
    missing = [r for r in required_roles if r not in present_role_names]

    feasible = len(missing) == 0
    blocking_reason = None
    role_hints = {}

    if not feasible:
        role_hints = {r: spec["hints"][r] for r in missing}
        hints_text = " | ".join(f"{r}: {spec['hints'][r]}" for r in missing)
        blocking_reason = (
            f"Calcul de {calculation} impossible — rôle(s) sémantique(s) manquant(s) : "
            f"{', '.join(missing)}. "
            f"Indices : {hints_text}"
        )

    return {
        "feasible": feasible,
        "required_roles": required_roles,
        "present_roles": present,
        "missing_roles": missing,
        "role_hints": role_hints,
        "blocking_reason": blocking_reason,
    }
'''

registry.register(Tool(
    name="copepod_columns",
    tags=frozenset({"copepod_columns"}),
    code=_code,
))
