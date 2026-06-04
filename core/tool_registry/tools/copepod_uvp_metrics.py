from core.tool_registry.registry import Tool, registry

_code = r'''
def resolve_uvp_m5_m6_inputs(columns=None, metadata=None, session_id=None, filename=None):
    """Resolve semantic inputs required for UVP MCA m5/m6 calculations.

    This tool does not calculate m5 or m6. It binds source columns to semantic
    roles and reports whether each metric can be calculated according to the
    MCA UVP script contract.

    Args:
        columns (list): Column descriptors from inspect_file() or plain names.
            If omitted, pass ``filename`` to auto-fetch from the session store.
        metadata (dict, optional): File metadata from inspect_file().
        session_id (str, optional): Session ID for tracing and store lookup.
        filename (str, optional): Basename of an already-inspected file.
            When provided and ``columns`` is absent, the structured inspection
            data is fetched from the session store automatically.

    Returns:
        dict: Role bindings, metric feasibility, warnings, and method contract.
    """
    if not columns and filename:
        try:
            import os as _os_r
            from core.session_store import session_store as _store_r
            _sk_r = _os_r.environ.get("IDEA_RUNTIME_SESSION_KEY") or session_id
            if _sk_r:
                _data = _store_r.read_inspection_data(_sk_r, filename)
                if _data:
                    columns = _data.get("columns", [])
                    metadata = metadata or _data.get("metadata", {})
        except Exception:
            pass
    if not columns:
        columns = []
    def _trace(res):
        try:
            import os as _os
            _sk = _os.environ.get("IDEA_RUNTIME_SESSION_KEY")
            from core.copepod_observability import trace_copepod_tool_call
            trace_copepod_tool_call(
                "resolve_uvp_m5_m6_inputs",
                session_key=session_id or _sk,
                input={
                    "n_columns": len(columns or []),
                    "metadata_keys": sorted((metadata or {}).keys()),
                },
                output={
                    "m5_feasible": res.get("metrics", {}).get("m5", {}).get("feasible"),
                    "m6_feasible": res.get("metrics", {}).get("m6", {}).get("feasible"),
                    "roles": {
                        k: v.get("column") for k, v in res.get("roles", {}).items()
                        if isinstance(v, dict)
                    },
                },
            )
        except Exception:
            pass
        return res

    def _column_names(raw_columns):
        names = []
        for col in raw_columns or []:
            if isinstance(col, dict):
                name = col.get("name")
            else:
                name = str(col)
            if name is not None and str(name).strip():
                names.append(str(name))
        return names

    col_names = _column_names(columns)
    lower_to_original = {c.lower(): c for c in col_names}

    def _bind(role, candidates, evidence, derivation=None, required_for=()):
        for candidate in candidates:
            original = lower_to_original.get(candidate.lower())
            if original:
                bound = {
                    "role": role,
                    "column": original,
                    "confidence": "high",
                    "evidence": evidence + [f"matched column '{original}'"],
                    "required_for": list(required_for),
                }
                if derivation:
                    bound["derivation"] = derivation
                return bound
        return None

    roles = {}

    role_specs = [
        (
            "profile_id",
            ["sample_id", "profile_id", "profile", "sample_profileid", "obj_orig_id"],
            ["Groups objects by UVP cast/profile."],
            None,
            ("m5", "m6"),
        ),
        (
            "sample_volume_l",
            [
                "sampled_volume",
                "sampled_volume_l",
                "sampled volume [l]",
                "ecopart_sampled_volume_l",
                "sample_volume_l",
            ],
            ["Volume sampled by EcoPart, required to convert counts to ind L-1."],
            None,
            ("m5", "m6"),
        ),
        (
            "taxon",
            [
                "object_annotation_category",
                "object_annotation_hierarchy",
                "txo_display_name",
                "taxon",
                "category",
                "classif_auto_name",
            ],
            ["Taxonomic field used to identify Copepoda categories."],
            None,
            ("m5", "m6"),
        ),
        (
            "depth_bin",
            ["depth_bin", "depth [m]", "ecopart_depth"],
            ["Depth bin used for surface and bottom windows."],
            None,
            ("m5", "m6"),
        ),
        (
            "large_copepod_length_pixels",
            [
                "object_major",
                "fre_major",
                "fre_axis_major_length",
                "object_feret",
                "fre_feret",
                "fre_feret_diameter_max",
            ],
            ["Pixel length source for m6; object_major/fre_major preferred by MCA script."],
            None,
            ("m6",),
        ),
        (
            "pixel_size_um",
            ["acq_pixel"],
            ["Pixel calibration; MCA script treats acq_pixel as microns per pixel."],
            None,
            ("m6",),
        ),
    ]

    for role, candidates, evidence, derivation, required_for in role_specs:
        bound = _bind(role, candidates, evidence, derivation, required_for)
        if bound:
            roles[role] = bound

    if "depth_bin" not in roles:
        derived_depth = _bind(
            "depth_bin",
            ["object_depth", "depth", "object_depth_min"],
            ["Depth can be binned to the 5 m MCA script convention."],
            "floor(depth / 5) * 5 + 2.5",
            ("m5", "m6"),
        )
        if derived_depth:
            roles["depth_bin"] = derived_depth

    ignored_for_m6_size = [
        c for c in col_names
        if c.lower() in {"taxon_size_category", "size_category", "object_annotation_size_category"}
    ]

    required = {
        "m5": ["profile_id", "depth_bin", "sample_volume_l", "taxon"],
        "m6": [
            "profile_id",
            "depth_bin",
            "sample_volume_l",
            "taxon",
            "large_copepod_length_pixels",
            "pixel_size_um",
        ],
    }

    def _metric_status(metric):
        missing = [role for role in required[metric] if role not in roles]
        return {
            "feasible": not missing,
            "required_roles": required[metric],
            "missing_roles": missing,
            "role_bindings": {
                role: roles[role]["column"] for role in required[metric] if role in roles
            },
        }

    warnings = []
    if ignored_for_m6_size:
        warnings.append(
            "Taxonomic size labels are ignored for m6; large copepods require pixel length and acq_pixel."
        )
    if "pixel_size_um" not in roles:
        warnings.append("m6 blocked without acq_pixel because >2 mm must be computed from image size.")
    if roles.get("taxon", {}).get("column") == "classif_auto_name":
        warnings.append("Taxonomy source is automatic prediction; document comparability limits.")

    result = {
        "method": "uvp_mca_m5_m6",
        "roles": roles,
        "metrics": {
            "m5": _metric_status("m5"),
            "m6": _metric_status("m6"),
        },
        "ignored_for_m6_size": ignored_for_m6_size,
        "warnings": warnings,
        "calculation_contract": {
            "m5_density_formula": "cop_dens = count_copepods / sampled_volume_l",
            "m6_size_formula": "copepod_size_um = object_major_or_fre_major * acq_pixel",
            "m6_threshold": "copepod_size_um > 2000",
            "surface_window": "depth_bin <= 50",
            "bottom_window": "depth_bin >= max_depth - 50",
            "vertical_summary": "metric = (surface_mean + bottom_mean) / 2",
        },
        "source": "Code - UVP_metrics_from_raw_data.R",
    }
    return _trace(result)


def calculate_uvp_m5_m6(data=None, resolved_inputs=None, session_id=None, filename=None):
    """Calculate UVP MCA m5/m6 from an object-level EcoTaxa table joined to volume.

    The calculation follows ``Code - UVP_metrics_from_raw_data.R``:
    m5 counts copepod objects per depth bin and divides by sampled volume.
    m6 first keeps copepods with ``object_major_or_fre_major * acq_pixel > 2000``
    microns, then applies the same density and vertical summary.
    """
    def _trace(res):
        try:
            import os as _os
            _sk = _os.environ.get("IDEA_RUNTIME_SESSION_KEY")
            from core.copepod_observability import trace_copepod_tool_call
            trace_copepod_tool_call(
                "calculate_uvp_m5_m6",
                session_key=session_id or _sk,
                input={"resolved_provided": resolved_inputs is not None},
                output={
                    "status": res.get("status"),
                    "n_records": len(res.get("records", [])),
                    "warnings": res.get("warnings", []),
                },
            )
        except Exception:
            pass
        return res

    import math

    try:
        import pandas as pd
    except Exception:
        return _trace({
            "status": "blocked",
            "records": [],
            "resolved": resolved_inputs,
            "warnings": ["pandas is required to calculate UVP m5/m6."],
        })

    if not data and filename:
        try:
            import os as _os_c
            from core.session_store import session_store as _store_c
            _sk_c = _os_c.environ.get("IDEA_RUNTIME_SESSION_KEY") or session_id
            if _sk_c:
                _fdata = _store_c.read_inspection_data(_sk_c, filename)
                if _fdata and _fdata.get("file_path"):
                    data = pd.read_csv(_fdata["file_path"], sep=None, engine="python", low_memory=False)
        except Exception:
            pass

    if hasattr(data, "copy") and hasattr(data, "columns"):
        df = data.copy()
    else:
        df = pd.DataFrame(data or [])

    if df.empty:
        return _trace({
            "status": "blocked",
            "records": [],
            "resolved": resolved_inputs,
            "warnings": ["No rows supplied for UVP m5/m6 calculation."],
        })

    if resolved_inputs is None:
        resolved_inputs = resolve_uvp_m5_m6_inputs(
            [{"name": str(c)} for c in df.columns],
            session_id=session_id,
        )

    m5_status = resolved_inputs.get("metrics", {}).get("m5", {})
    m6_status = resolved_inputs.get("metrics", {}).get("m6", {})
    warnings = list(resolved_inputs.get("warnings", []))

    if not m5_status.get("feasible"):
        return _trace({
            "status": "blocked",
            "records": [],
            "resolved": resolved_inputs,
            "warnings": warnings + ["m5 is not feasible; m6 depends on the same profile/depth/volume/taxon inputs."],
        })

    roles = resolved_inputs.get("roles", {})

    def _role_col(role):
        value = roles.get(role, {})
        return value.get("column") if isinstance(value, dict) else None

    profile_col = _role_col("profile_id")
    depth_col = _role_col("depth_bin")
    volume_col = _role_col("sample_volume_l")
    taxon_col = _role_col("taxon")
    length_col = _role_col("large_copepod_length_pixels")
    pixel_col = _role_col("pixel_size_um")

    work = df.copy()
    depth_role = roles.get("depth_bin", {})
    if isinstance(depth_role, dict) and depth_role.get("derivation"):
        numeric_depth = pd.to_numeric(work[depth_col], errors="coerce")
        work["_uvp_depth_bin"] = (numeric_depth / 5).apply(
            lambda value: math.floor(value) * 5 + 2.5 if pd.notna(value) else float("nan")
        )
        depth_use_col = "_uvp_depth_bin"
    else:
        depth_use_col = depth_col

    work["_uvp_depth_bin_numeric"] = pd.to_numeric(work[depth_use_col], errors="coerce")
    work["_uvp_volume_l"] = pd.to_numeric(work[volume_col], errors="coerce")

    copepod_terms = {
        "copepoda<multicrustacea",
        "calanoida",
        "heterorhabdidae",
        "calanus",
        "paraeuchaeta",
        "metridia",
        "female+eggs<paraeuchaeta",
        "copepoda eggs",
    }

    def _is_copepod(value):
        text = str(value or "").strip().lower()
        return text in copepod_terms or "copepoda" in text

    work["_uvp_is_copepod"] = work[taxon_col].apply(_is_copepod)
    valid_base = work[
        work["_uvp_is_copepod"]
        & work["_uvp_depth_bin_numeric"].notna()
        & work["_uvp_volume_l"].notna()
        & (work["_uvp_volume_l"] > 0)
    ].copy()

    def _first_existing(cols):
        for col in cols:
            if col in work.columns:
                return col
        return None

    station_col = _first_existing(["station", "sample_stationid", "station_id"])
    lat_col = _first_existing(["lat", "latitude", "object_lat", "obj_latitude"])
    lon_col = _first_existing(["lon", "longitude", "object_lon", "obj_longitude"])

    def _optional_first(frame, col):
        if col and col in frame.columns and not frame[col].dropna().empty:
            value = frame[col].dropna().iloc[0]
            try:
                if pd.isna(value):
                    return None
            except Exception:
                pass
            return value
        return None

    def _mean_or_none(values):
        cleaned = [float(v) for v in values if pd.notna(v)]
        if not cleaned:
            return None
        return sum(cleaned) / len(cleaned)

    def _density_by_bin(source, count_col, density_col):
        if source.empty:
            return pd.DataFrame(columns=[profile_col, "_uvp_depth_bin_numeric", "_uvp_volume_l", count_col, density_col])
        grouped = (
            source
            .groupby([profile_col, "_uvp_depth_bin_numeric", "_uvp_volume_l"], dropna=False)
            .size()
            .reset_index(name=count_col)
        )
        grouped[density_col] = grouped[count_col] / grouped["_uvp_volume_l"]
        return grouped

    m5_bins = _density_by_bin(valid_base, "tot_cop", "cop_dens")

    m6_bins = pd.DataFrame()
    if m6_status.get("feasible"):
        sized = valid_base.copy()
        sized["_uvp_size_um"] = (
            pd.to_numeric(sized[length_col], errors="coerce")
            * pd.to_numeric(sized[pixel_col], errors="coerce")
        )
        large = sized[sized["_uvp_size_um"] > 2000].copy()
        m6_bins = _density_by_bin(large, "large_cop_nb", "large_cop_dens")

    profile_values = list(dict.fromkeys(m5_bins[profile_col].tolist()))
    if not profile_values and not m6_bins.empty:
        profile_values = list(dict.fromkeys(m6_bins[profile_col].tolist()))

    records = []
    for profile in profile_values:
        profile_m5 = m5_bins[m5_bins[profile_col] == profile]
        source_rows = work[work[profile_col] == profile]
        max_depth = _mean_or_none([profile_m5["_uvp_depth_bin_numeric"].max()])

        if max_depth is None:
            m5_surface = None
            m5_bottom = None
            m5_value = None
        else:
            m5_surface = _mean_or_none(profile_m5.loc[profile_m5["_uvp_depth_bin_numeric"] <= 50, "cop_dens"])
            m5_bottom = _mean_or_none(profile_m5.loc[profile_m5["_uvp_depth_bin_numeric"] >= (max_depth - 50), "cop_dens"])
            m5_value = None if m5_surface is None or m5_bottom is None else (m5_surface + m5_bottom) / 2

        m6_surface = None
        m6_bottom = None
        m6_value = None
        if m6_status.get("feasible") and not m6_bins.empty:
            profile_m6 = m6_bins[m6_bins[profile_col] == profile]
            if not profile_m6.empty:
                m6_max_depth = _mean_or_none([profile_m6["_uvp_depth_bin_numeric"].max()])
                if m6_max_depth is not None:
                    m6_surface = _mean_or_none(profile_m6.loc[profile_m6["_uvp_depth_bin_numeric"] <= 50, "large_cop_dens"])
                    m6_bottom = _mean_or_none(profile_m6.loc[profile_m6["_uvp_depth_bin_numeric"] >= (m6_max_depth - 50), "large_cop_dens"])
                    m6_value = None if m6_surface is None or m6_bottom is None else (m6_surface + m6_bottom) / 2

        records.append({
            "sample_id": profile,
            "station": _optional_first(source_rows, station_col),
            "lat": _optional_first(source_rows, lat_col),
            "lon": _optional_first(source_rows, lon_col),
            "max_depth": max_depth,
            "m5_surface_mean_cop_dens": m5_surface,
            "m5_bottom_mean_cop_dens": m5_bottom,
            "m5_cop_dens": m5_value,
            "m6_surface_mean_largecop_dens": m6_surface,
            "m6_bottom_mean_largecop_dens": m6_bottom,
            "m6_largecop_dens": m6_value,
        })

    status = "ok" if m5_status.get("feasible") and m6_status.get("feasible") else "partial"
    return _trace({
        "status": status,
        "records": records,
        "resolved": resolved_inputs,
        "warnings": warnings,
        "method": resolved_inputs.get("method", "uvp_mca_m5_m6"),
        "source": "Code - UVP_metrics_from_raw_data.R",
    })
'''

registry.register(Tool(
    name="copepod_uvp_metrics",
    tags=frozenset({"copepod_uvp_metrics"}),
    code=_code,
))
