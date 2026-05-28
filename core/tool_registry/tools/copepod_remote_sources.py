from core.tool_registry.registry import Tool, registry

_code = '''
def _clean_text(value):
    return " ".join(str(value or "").replace("\\n", " ").split()).strip()

def _coerce_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None

def _normalize_year_bound(value, is_start):
    if value is None:
        return None
    if isinstance(value, int):
        return f"{value:04d}-01-01T00:00:00Z"
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 4 and text.isdigit():
        return f"{text}-01-01T00:00:00Z"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text}T00:00:00Z"
    if text.endswith("Z"):
        return text
    return text + "T00:00:00Z"

def _bio_oracle_variable_spec(variable):
    aliases = {
        "si": ("si", "si_mean"),
        "si_mean": ("si", "si_mean"),
        "silicate": ("si", "si_mean"),
        "no3": ("no3", "no3_mean"),
        "no3_mean": ("no3", "no3_mean"),
        "nitrate": ("no3", "no3_mean"),
        "so": ("so", "so_mean"),
        "so_mean": ("so", "so_mean"),
        "salinity": ("so", "so_mean"),
        "thetao": ("thetao", "thetao_mean"),
        "thetao_mean": ("thetao", "thetao_mean"),
        "temperature": ("thetao", "thetao_mean"),
        "sst": ("thetao", "thetao_mean"),
        "sws": ("sws", "sws_mean"),
        "sws_mean": ("sws", "sws_mean"),
        "sea water speed": ("sws", "sws_mean"),
        "swd": ("swd", "swd_mean"),
        "swd_mean": ("swd", "swd_mean"),
        "siconc": ("siconc", "siconc_mean"),
        "siconc_mean": ("siconc", "siconc_mean"),
        "sea ice cover": ("siconc", "siconc_mean"),
        "sithick": ("sithick", "sithick_mean"),
        "sithick_mean": ("sithick", "sithick_mean"),
        "sea ice thickness": ("sithick", "sithick_mean"),
        "phyc": ("phyc", "phyc_mean"),
        "phyc_mean": ("phyc", "phyc_mean"),
        "chlorophyll": ("phyc", "phyc_mean"),
        "chl": ("phyc", "phyc_mean"),
    }
    key = _clean_text(variable).lower()
    if key in aliases:
        return {"dataset_code": aliases[key][0], "variable_name": aliases[key][1]}
    return None

def _parse_erddap_csv(text):
    import csv
    from io import StringIO

    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return []
    reader = csv.DictReader(StringIO("\\n".join([lines[0]] + lines[2:])))
    rows = []
    for row in reader:
        clean_row = {}
        for key, value in row.items():
            clean_row[key] = value
        rows.append(clean_row)
    return rows

def _fetch_bio_oracle_preview(plan, latitude, longitude, session_id=None):
    import requests

    params = (plan or {}).get("parameters") or {}
    variable = params.get("variable") or (params.get("variables") or [None])[0]
    variable_spec = _bio_oracle_variable_spec(variable)
    if not variable_spec:
        return {
            "status": "unsupported_variable",
            "source_id": "bio_oracle",
            "source_label": "Bio-ORACLE — variables environnementales marines",
            "plan": plan,
            "supported_variables": [
                "si_mean", "no3_mean", "so_mean", "thetao_mean", "sws_mean", "swd_mean", "siconc_mean", "sithick_mean", "phyc_mean",
            ],
            "clarification_question": "Quelle variable Bio-ORACLE faut-il extraire ?",
        }

    scenario = _clean_text(params.get("scenario")).lower().replace("-", "")
    if scenario in {"historical", "historique", "baseline"}:
        scenario_slug = "baseline_2000_2020"
    else:
        scenario_slug = scenario or "ssp126"
        if not scenario_slug.startswith("ssp"):
            scenario_slug = f"ssp{scenario_slug}"
        scenario_slug = f"{scenario_slug}_2020_2100"

    period = params.get("period") or {}
    start = _normalize_year_bound(period.get("start"), True)
    end = _normalize_year_bound(period.get("end"), False)
    if not start or not end:
        return {
            "status": "needs_clarification",
            "source_id": "bio_oracle",
            "source_label": "Bio-ORACLE — variables environnementales marines",
            "plan": plan,
            "clarification_question": "Quelle période faut-il couvrir ?",
        }

    lat = _coerce_float(latitude)
    lon = _coerce_float(longitude)
    if lat is None or lon is None:
        return {
            "status": "needs_clarification",
            "source_id": "bio_oracle",
            "source_label": "Bio-ORACLE — variables environnementales marines",
            "plan": plan,
            "clarification_question": "Quelles coordonnées latitude/longitude faut-il cibler ?",
        }

    dataset_id = f"{variable_spec['dataset_code']}_{scenario_slug}_depthmean"
    url = (
        f"https://erddap.bio-oracle.org/erddap/griddap/{dataset_id}.csv"
        f"?{variable_spec['variable_name']}[({start}):1:({end})][({lat})][({lon})]"
    )

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    rows = _parse_erddap_csv(response.text)

    return {
        "status": "ok",
        "source_id": "bio_oracle",
        "source_label": "Bio-ORACLE — variables environnementales marines",
        "plan": plan,
        "dataset_id": dataset_id,
        "request_url": url,
        "row_count": len(rows),
        "rows": rows,
    }

def _fetch_ogsl_preview(plan, session_id=None):
    import requests
    from urllib.parse import quote

    params = (plan or {}).get("parameters") or {}
    cruise_id = _clean_text(params.get("cruise_id"))
    station = _clean_text(params.get("station"))
    period = params.get("period") or {}
    start = _normalize_year_bound(period.get("start"), True)
    end = _normalize_year_bound(period.get("end"), False)
    if not start or not end:
        return {
            "status": "needs_clarification",
            "source_id": "ogsl",
            "source_label": "OGSL — Observatoire global du Saint-Laurent",
            "plan": plan,
            "clarification_question": "Quelle période OGSL faut-il couvrir ?",
        }
    if not cruise_id and not station:
        return {
            "status": "needs_clarification",
            "source_id": "ogsl",
            "source_label": "OGSL — Observatoire global du Saint-Laurent",
            "plan": plan,
            "clarification_question": "Quelle mission, croisière ou station OGSL faut-il cibler ?",
        }

    columns = [
        "cruiseID",
        "cruise_start_date",
        "cruise_end_date",
        "cruise_chief_scientist",
        "platform_name",
        "instrument",
        "stationID",
        "cast_number",
        "time",
        "latitude",
        "longitude",
        "PRES",
        "TE90",
        "PSAL",
        "ASAL",
        "FLOR",
        "OXYM",
        "PSAR",
        "SIGT",
        "TRAN",
    ]
    filters = []
    if cruise_id:
        filters.append(f'cruiseID=%22{quote(cruise_id)}%22')
    if station:
        filters.append(f'stationID=%22{quote(station)}%22')
    filters.append(f"time>={quote(start)}")
    filters.append(f"time<={quote(end)}")

    dataset_id = "ismerSgdeCtd"
    url = (
        f"https://erddap.ogsl.ca/erddap/tabledap/{dataset_id}.csv?"
        f"{','.join(columns)}&{'&'.join(filters)}"
    )

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    rows = _parse_erddap_csv(response.text)

    return {
        "status": "ok",
        "source_id": "ogsl",
        "source_label": "OGSL — Observatoire global du Saint-Laurent",
        "plan": plan,
        "dataset_id": dataset_id,
        "request_url": url,
        "row_count": len(rows),
        "rows": rows,
    }

def fetch_remote_source_preview(message, source_hint=None, latitude=None, longitude=None, session_id=None):
    """Fetch a small preview from a remote environmental source.

    The function currently implements Bio-ORACLE preview fetches and returns a
    structured clarification payload when the request is incomplete.
    """
    plan = plan_remote_source_request(message, source_hint=source_hint, session_id=session_id)
    if plan.get("source_id") != "bio_oracle":
        if plan.get("source_id") == "ogsl":
            return _fetch_ogsl_preview(plan, session_id=session_id)
        return {
            "status": "unsupported_source",
            "plan": plan,
            "clarification_question": "Ce MVP prend en charge Bio-ORACLE et OGSL. Voulez-vous reformuler la source ?",
        }

    return _fetch_bio_oracle_preview(plan, latitude, longitude, session_id=session_id)
'''

registry.register(Tool(
    name="copepod_remote_sources",
    tags=frozenset({"copepod_remote_sources"}),
    code=_code,
))
