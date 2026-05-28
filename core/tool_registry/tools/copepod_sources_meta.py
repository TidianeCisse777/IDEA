from core.tool_registry.registry import Tool, registry

_code = '''
def list_available_sources(auth_token=None, session_id=None):
    """Return the list of known data sources with their activation status.

    Without auth_token, returns all sources with activated=False for API sources.
    With a valid EcoTaxa auth_token, attempts to query the API to confirm access
    and sets activated=True for reachable projects.

    Never returns a hardcoded list of project IDs — API sources are confirmed
    dynamically when credentials are provided.

    Use this when:
    - The user asks "quelles sources sont disponibles ?"
    - Before querying a source to check if credentials are needed
    - To explain what requires a login vs what is openly accessible

    Args:
        auth_token (str, optional): EcoTaxa API token. If provided, the function
            attempts to verify access to EcoTaxa projects via the API.
        session_id (str, optional): Session ID for Langfuse tracing.

    Returns:
        dict:
            sources — list of source dicts, each with:
                id                   — source identifier
                label                — human-readable name
                type                 — "local" | "api" | "rag_only"
                activated            — True if credentials verified
                requires_credentials — True if a login/token is needed
    """
    # Base metadata for all known source families.
    # Project IDs (e.g. 1165, 105) are metadata, not used to call the API here.
    base_sources = [
        {
            "id": "ecotaxa_1165",
            "label": "EcoTaxa UVP5 Amundsen 2018 (projet 1165)",
            "type": "api",
            "activated": False,
            "requires_credentials": True,
        },
        {
            "id": "ecotaxa_2331",
            "label": "EcoTaxa LOKI copépodes lipides (projet 2331)",
            "type": "api",
            "activated": False,
            "requires_credentials": True,
        },
        {
            "id": "ecopart_105",
            "label": "EcoPart UVP5 Amundsen 2018 (projet 105)",
            "type": "api",
            "activated": False,
            "requires_credentials": True,
        },
        {
            "id": "amundsen_ctd",
            "label": "CTD Amundsen 2018 via ERDDAP (CIOOS ca-cioos_ccin-12713)",
            "type": "api",
            "activated": False,
            "requires_credentials": False,
        },
        {
            "id": "ogsl",
            "label": "OGSL — Observatoire Global du Saint-Laurent",
            "type": "api",
            "activated": False,
            "requires_credentials": False,
        },
        {
            "id": "bio_oracle",
            "label": "Bio-ORACLE — variables environnementales marines",
            "type": "api",
            "activated": False,
            "requires_credentials": False,
        },
    ]

    if not auth_token:
        return {"sources": base_sources}

    # With an auth_token: try EcoTaxa API to verify access
    try:
        import requests
        ecotaxa_base = "https://ecotaxa.obs-vlfr.fr/api"
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = requests.get(
            f"{ecotaxa_base}/projects/search",
            params={"title_filter": "", "instrument_filter": ""},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            accessible_ids = {str(p["projid"]) for p in resp.json()}
            for s in base_sources:
                if s["type"] == "api" and "ecotaxa" in s["id"]:
                    # Extract project id from source id (e.g. "ecotaxa_1165" → "1165")
                    parts = s["id"].split("_")
                    proj_id = parts[-1] if parts else ""
                    if proj_id in accessible_ids:
                        s["activated"] = True
    except Exception:
        pass

    return {"sources": base_sources}


def describe_source(source_id, session_id=None):
    """Return a full description of a known data source.

    Provides content summary, join keys, known limitations and credential
    requirements for a given source ID. Returns a not-found signal for
    unknown source IDs without raising an exception.

    Use this when:
    - The user asks what a source contains or how to use it
    - You need to explain join keys between sources
    - Before recommending a source for a specific question

    Args:
        source_id (str): Source identifier (e.g. "ecotaxa_1165", "ecopart_105",
                         "amundsen_ctd", "ogsl", "bio_oracle").
        session_id (str, optional): Session ID for Langfuse tracing.

    Returns:
        dict:
            id                   — echoes source_id
            label                — human-readable name
            content_summary      — what this source contains
            join_keys            — list of columns that link this source to others
            known_limitations    — list of caveats
            requires_credentials — True if a login/token is needed
            found                — False if source_id is not recognised
    """
    SOURCES = {
        "ecotaxa_1165": {
            "id": "ecotaxa_1165",
            "label": "EcoTaxa UVP5 Amundsen 2018 (projet 1165)",
            "content_summary": (
                "Objets individuels classifiés par UVP5 durant la campagne Amundsen 2018. "
                "Contient les colonnes objet (morphométrie, profondeur, annotation taxonomique), "
                "les colonnes acq_* (calibration instrument) et sample_* (métadonnées profil). "
                "Clé de liaison vers EcoPart : obj_orig_id → Profile."
            ),
            "join_keys": ["obj_orig_id", "object_depth_min", "object_depth_max"],
            "known_limitations": [
                "Pas de volume échantillonné — utiliser EcoPart pour la concentration.",
                "Les annotations non validées (classif_qual != 'V') doivent être filtrées.",
                "acq_pixel requis pour convertir les mesures de pixels en mm.",
            ],
            "requires_credentials": True,
        },
        "ecotaxa_2331": {
            "id": "ecotaxa_2331",
            "label": "EcoTaxa LOKI copépodes lipides (projet 2331)",
            "content_summary": (
                "Copépodes imagés par LOKI avec annotations taxonomiques et données lipidiques. "
                "Source principale pour les espèces Calanus avec réserves lipidiques."
            ),
            "join_keys": ["obj_orig_id"],
            "known_limitations": [
                "Instrument LOKI — colonnes acq_* différentes de UVP5.",
                "Données lipidiques issues de mesures en laboratoire, pas directement dans EcoTaxa.",
            ],
            "requires_credentials": True,
        },
        "ecopart_105": {
            "id": "ecopart_105",
            "label": "EcoPart UVP5 Amundsen 2018 (projet 105)",
            "content_summary": (
                "Profils de particules agrégées et volume échantillonné par profil et tranche de profondeur. "
                "Contient 'Sampled volume [L]', 'Profile', 'Depth [m]' et spectres de taille LPM. "
                "Source obligatoire pour calculer des concentrations depuis EcoTaxa."
            ),
            "join_keys": ["Profile"],
            "known_limitations": [
                "Granularité par tranche de profondeur — join avec EcoTaxa nécessite "
                "une tolérance sur la profondeur (depth_delta_m).",
                "Profil EcoPart = sous-chaîne de obj_orig_id EcoTaxa "
                "(ex. ips_007_899 → ips_007).",
            ],
            "requires_credentials": True,
        },
        "amundsen_ctd": {
            "id": "amundsen_ctd",
            "label": "CTD Amundsen 2018 via ERDDAP (CIOOS ca-cioos_ccin-12713)",
            "content_summary": (
                "Profils CTD officiels de la campagne Amundsen 2018 : température (TE90), "
                "salinité (PSAL), oxygène (DOXY), fluorescence (FLOR) et turbidité. "
                "Accès via ERDDAP CIOOS. Résolution ~1 dbar."
            ),
            "join_keys": ["station", "latitude", "longitude", "depth"],
            "known_limitations": [
                "Accès ERDDAP — requêtes lentes sur grandes plages temporelles.",
                "La colonne station ne correspond pas directement à profile_id EcoPart "
                "— jointure nécessite une correspondance spatiale.",
            ],
            "requires_credentials": False,
        },
        "ogsl": {
            "id": "ogsl",
            "label": "OGSL — Observatoire Global du Saint-Laurent",
            "content_summary": (
                "Données océanographiques du Saint-Laurent et de l'Arctique canadien. "
                "Accès via API OGSL. Contient des séries temporelles de variables physiques "
                "et biologiques."
            ),
            "join_keys": ["latitude", "longitude", "time"],
            "known_limitations": [
                "Couverture variable selon les jeux de données disponibles.",
                "Résolution spatiale et temporelle à vérifier selon le dataset.",
            ],
            "requires_credentials": False,
        },
        "bio_oracle": {
            "id": "bio_oracle",
            "label": "Bio-ORACLE — variables environnementales marines",
            "content_summary": (
                "Variables environnementales marines à l'échelle globale : "
                "température, salinité, courants, concentration en chlorophylle. "
                "Disponible pour périodes historiques et scénarios futurs (SSP)."
            ),
            "join_keys": ["latitude", "longitude"],
            "known_limitations": [
                "Résolution spatiale ~ 5 arc-minutes — insuffisante pour des analyses à l'échelle d'une station.",
                "Les scénarios futurs (SSP) requièrent de préciser la période et le scénario.",
            ],
            "requires_credentials": False,
        },
    }

    if source_id not in SOURCES:
        return {
            "id": source_id,
            "label": "Unknown",
            "content_summary": f"Source \'{source_id}\' not found in known sources.",
            "join_keys": [],
            "known_limitations": [],
            "requires_credentials": False,
            "found": False,
        }

    result = dict(SOURCES[source_id])
    result["found"] = True
    return result


def plan_remote_source_request(request_text, source_hint=None, session_id=None):
    """Normalize an explicit remote-source request into a structured plan.

    The helper identifies OGSL vs Bio-ORACLE, extracts the most obvious
    parameters, and returns the missing fields together with the next step.
    It never performs a remote fetch itself.
    """
    import re

    text = (request_text or "").strip()
    lowered = text.lower()
    hint = (source_hint or "").strip().lower()

    def _match_source() -> str:
        if "bio_oracle" in hint or "bio-oracle" in hint or "bio oracle" in hint:
            return "bio_oracle"
        if "ogsl" in hint:
            return "ogsl"
        if "bio_oracle" in lowered or "bio-oracle" in lowered or "bio oracle" in lowered:
            return "bio_oracle"
        if "ogsl" in lowered or "saint-laurent" in lowered or "saint laurent" in lowered:
            return "ogsl"
        return "unknown"

    def _extract_period() -> dict:
        iso_dates = re.findall(r"(20\\d{2}-\\d{2}-\\d{2})", text)
        if len(iso_dates) >= 2:
            return {"start": iso_dates[0], "end": iso_dates[1]}
        years = re.findall(r"(20\\d{2})", text)
        if len(years) >= 2:
            return {"start": int(years[0]), "end": int(years[1])}
        return {}

    def _extract_variable_names() -> list[str]:
        candidates = []
        patterns = [
            r"variable\s+([a-zA-Z0-9_]+)",
            r"sur\s+la\s+variable\s+([a-zA-Z0-9_]+)",
            r"avec\s+([A-Za-z0-9_,\s]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw = match.group(1)
                normalized = (
                    raw.replace(" et ", ",")
                    .replace(" ET ", ",")
                    .replace(" Et ", ",")
                    .replace(" eT ", ",")
                )
                for part in re.split(r"[,/]", normalized):
                    token = part.strip().strip(".;:")
                    if token and len(token) <= 24:
                        candidates.append(token)
                break
        cleaned = []
        for item in candidates:
            if item and item.lower() not in {"le", "la", "les", "et", "sur", "pour"}:
                cleaned.append(item)
        return cleaned

    source_id = _match_source()
    period = _extract_period()
    variables = _extract_variable_names()
    parameters = {
        "request_text": text,
        "source_hint": source_hint,
    }
    missing_fields: list[str] = []

    if source_id == "bio_oracle":
        scenario = None
        scenario_match = re.search(r"\bssp\s*([0-9]{3})\b", text, re.IGNORECASE)
        if scenario_match:
            scenario = f"SSP{scenario_match.group(1)}"
        elif "scenario" in lowered or "scénario" in lowered or "scenar" in lowered:
            scenario = re.search(r"(ssp\s*[0-9]{3})", text, re.IGNORECASE)
            scenario = f"SSP{scenario.group(1)[-3:]}" if scenario else None

        zone = None
        zone_match = re.search(
            r"\b(zone|site|coordonn?es?|coordinates?)\b\s*[:=]?\s*(.+)",
            text,
            re.IGNORECASE,
        )
        if zone_match:
            zone = zone_match.group(2).strip().rstrip(".")
        elif any(token in lowered for token in ["latitude", "longitude", "lat", "lon", "coord"]):
            zone = "coordinates-specified"

        if scenario:
            parameters["scenario"] = scenario
        if period:
            parameters["period"] = period
        if variables:
            parameters["variable"] = variables[0]
            parameters["variables"] = variables
        if zone:
            parameters["zone"] = zone

        if "scenario" not in parameters:
            missing_fields.append("scenario")
        if "period" not in parameters:
            missing_fields.append("period")
        if "variable" not in parameters:
            missing_fields.append("variable")
        if "zone" not in parameters:
            missing_fields.append("zone")

    elif source_id == "ogsl":
        station = None
        if "station" in lowered:
            station = lowered.split("station", 1)[1].strip().split()[0].strip(",.;:")
        mission = None
        if "mission" in lowered:
            mission = lowered.split("mission", 1)[1].strip().split()[0].strip(",.;:")
        if station:
            parameters["station"] = station
        if mission:
            parameters["mission"] = mission
        if period:
            parameters["period"] = period
        if variables:
            parameters["variables"] = variables

        if "station" not in parameters and "mission" not in parameters:
            missing_fields.append("zone_or_station_or_mission")
        if "period" not in parameters:
            missing_fields.append("period")
        if not variables:
            missing_fields.append("variables")

    else:
        missing_fields.append("source")

    recommended_next_step = "ask_clarification" if missing_fields else "proceed"
    clarification_question = None
    if missing_fields:
        if source_id == "bio_oracle":
            clarification_question = "Quelle zone ou quelles coordonnées voulez-vous utiliser pour Bio-ORACLE ?"
        elif source_id == "ogsl":
            clarification_question = "Quelle zone, station ou mission OGSL voulez-vous utiliser ?"
        else:
            clarification_question = "Quelle source voulez-vous utiliser, OGSL ou Bio-ORACLE ?"
    elif source_id == "ogsl":
        recommended_next_step = "ask_clarification"
        clarification_question = "Quelle zone, station ou mission OGSL voulez-vous utiliser ?"

    return {
        "source_id": source_id,
        "intent": "fetch" if source_id != "unknown" else "clarify",
        "parameters": parameters,
        "missing_fields": missing_fields,
        "recommended_next_step": recommended_next_step,
        "clarification_question": clarification_question,
    }
'''

registry.register(Tool(
    name="copepod_sources_meta",
    tags=frozenset({"copepod_sources_meta"}),
    code=_code,
))
