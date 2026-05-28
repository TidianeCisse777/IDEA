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


def plan_remote_source_request(message, source_hint=None, session_id=None):
    """Plan a remote OGSL/Bio-ORACLE request from a natural-language message.

    This helper does not fetch data. It turns the user request into a
    structured plan that can be used by the runtime to ask for missing
    parameters, route the request to the right source, and later call the
    corresponding MCP connector.

    Use this when:
    - the user asks to fetch OGSL or Bio-ORACLE data in natural language;
    - you need to decide whether the request can proceed or needs clarification;
    - you want a structured payload for a future MCP request.

    Args:
        message (str): User request in natural language.
        source_hint (str, optional): Explicit source hint such as "ogsl" or
            "bio_oracle". When provided, it wins over message heuristics.
        session_id (str, optional): Session ID for Langfuse tracing.

    Returns:
        dict:
            source_id                — resolved source family or "unknown"
            source_label              — resolved human-readable label
            intent                    — "fetch" | "couple" | "describe" | "unknown"
            parameters                — parsed parameters for the remote source
            missing_fields            — list of missing parameters
            recommended_next_step     — "proceed" | "ask_clarification"
            clarification_question    — short question to ask the user next
            found                     — True if the source family is recognized
    """

    def _clean_text(value):
        return " ".join(str(value or "").replace("\\n", " ").split()).strip()

    def _source_from_hint_or_message(text, hint):
        hint_text = _clean_text(hint).lower().replace("-", "_")
        if hint_text in {"ogsl", "bio_oracle"}:
            return hint_text
        lowered = text.lower()
        if "bio-oracle" in lowered or "bio oracle" in lowered:
            return "bio_oracle"
        if "ogsl" in lowered or "saint-laurent" in lowered or "saint laurent" in lowered or "golfe du saint-laurent" in lowered or "golfe du saint laurent" in lowered:
            return "ogsl"
        return "unknown"

    def _extract_period(text, source_id):
        import re

        date_matches = re.findall(r"\\b(?:19|20)\\d{2}-\\d{2}-\\d{2}\\b", text)
        year_matches = [int(y) for y in re.findall(r"\\b(?:19|20)\\d{2}\\b", text)]

        if source_id == "ogsl":
            if len(date_matches) >= 2:
                return {"start": date_matches[0], "end": date_matches[1], "granularity": "date"}
            if len(year_matches) >= 2:
                return {"start": str(year_matches[0]), "end": str(year_matches[1]), "granularity": "year"}
        if source_id == "bio_oracle":
            if len(year_matches) >= 2:
                return {"start": year_matches[0], "end": year_matches[1], "granularity": "year"}
            if len(date_matches) >= 2:
                return {"start": date_matches[0], "end": date_matches[1], "granularity": "date"}
        return {"start": None, "end": None, "granularity": None}

    def _extract_station(text):
        import re

        match = re.search(r"\\bstation\\s+([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _extract_cruise_id(text):
        import re

        patterns = [
            r"\\b(?:mission|cruise|campagne|expedition|expédition)\\s+([A-Za-z0-9_./ -]{3,})",
            r"\\bcruiseID\\s*[:=]\\s*([A-Za-z0-9_./ -]{3,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                candidate = re.split(r"\\b(?:avec|sur|pour|entre|de|du|des|et|à|a)\\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0].strip()
                if candidate:
                    return candidate
        return None

    def _extract_zone(text):
        import re

        match = re.search(r"\\bzone\\s+([A-Za-z0-9À-ÿ _-]+)", text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            candidate = re.split(r"\\b(?:avec|sur|pour|entre|de|du|des|et|à|a)\\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            return candidate or None
        return None

    def _extract_scenario(text):
        import re

        lowered = text.lower()
        match = re.search(r"\\bssp\\s?(\\d{3})\\b", lowered, flags=re.IGNORECASE)
        if match:
            return f"SSP{match.group(1)}"
        if "historical" in lowered or "historique" in lowered:
            return "historical"
        return None

    def _extract_variables(text, source_id):
        import re

        lowered = text.lower()
        bio_vars = {
            "si_mean": "si_mean",
            "si": "si",
            "sst": "sst",
            "temperature": "temperature",
            "salinity": "salinity",
            "chlorophyll": "chlorophyll",
            "chl": "chl",
            "oxygen": "oxygen",
            "nitrate": "nitrate",
            "ph": "ph",
        }
        ogsl_vars = {
            "pres": "PRES",
            "te90": "TE90",
            "psal": "PSAL",
            "oxym": "OXYM",
            "flor": "FLOR",
            "doxy": "DOXY",
            "temp": "TEMP",
            "salinity": "salinity",
            "temperature": "temperature",
            "oxygen": "oxygen",
            "turb": "TURB",
        }
        candidates = bio_vars if source_id == "bio_oracle" else ogsl_vars
        found = []
        for var, canonical in candidates.items():
            pattern = rf"\\b{re.escape(var)}\\b"
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                found.append(canonical)
        unique = []
        for item in found:
            if item not in unique:
                unique.append(item)
        return unique

    def _clarification_question(source_id, missing_fields):
        if source_id == "bio_oracle":
            if "variable" in missing_fields:
                return "Quelle variable Bio-ORACLE voulez-vous extraire ?"
            if "scenario" in missing_fields:
                return "Quel scénario Bio-ORACLE faut-il utiliser ?"
            if "zone" in missing_fields:
                return "Quelle zone ou quelles coordonnées faut-il cibler ?"
            if "period" in missing_fields:
                return "Quelle période faut-il couvrir ?"
            if "output_format" in missing_fields:
                return "Quel format de sortie voulez-vous ?"
            return "Pouvez-vous préciser le contexte Bio-ORACLE ?"
        if source_id == "ogsl":
            if "period" in missing_fields:
                return "Quelle période OGSL faut-il couvrir ?"
            if "variables" in missing_fields:
                return "Quelles variables OGSL voulez-vous extraire ?"
            if "zone_or_station_or_mission" in missing_fields:
                return "Quelle station, mission ou zone OGSL faut-il cibler ?"
            if "output_format" in missing_fields:
                return "Quel format de sortie voulez-vous ?"
            return "Pouvez-vous préciser le contexte OGSL ?"
        if "source" in missing_fields:
            return "Quelle source voulez-vous utiliser: OGSL ou Bio-ORACLE ?"
        return "Pouvez-vous préciser le contexte attendu ?"

    text = _clean_text(message)
    source_id = _source_from_hint_or_message(text, source_hint)
    source_meta = describe_source(source_id) if source_id != "unknown" else {
        "id": "unknown",
        "label": "Unknown",
        "content_summary": "",
        "join_keys": [],
        "known_limitations": [],
        "requires_credentials": False,
        "found": False,
    }

    parameters = {
        "period": _extract_period(text, source_id),
        "station": _extract_station(text) if source_id == "ogsl" else None,
        "cruise_id": _extract_cruise_id(text) if source_id == "ogsl" else None,
        "zone": _extract_zone(text),
        "scenario": _extract_scenario(text) if source_id == "bio_oracle" else None,
        "variables": _extract_variables(text, source_id) if source_id in {"ogsl", "bio_oracle"} else [],
        "variable": None,
        "raw_message": text,
    }
    if source_id == "bio_oracle" and parameters["variables"]:
        parameters["variable"] = parameters["variables"][0]

    if source_id == "bio_oracle":
        intent = "fetch"
        missing_fields = []
        if not parameters["scenario"]:
            missing_fields.append("scenario")
        if not parameters["variables"]:
            missing_fields.append("variable")
        if not parameters["period"]["start"] or not parameters["period"]["end"]:
            missing_fields.append("period")
        if not parameters["zone"]:
            missing_fields.append("zone")
        if not parameters["zone"]:
            missing_fields.append("output_format")
    elif source_id == "ogsl":
        intent = "fetch"
        missing_fields = []
        if not parameters["period"]["start"] or not parameters["period"]["end"]:
            missing_fields.append("period")
        if not parameters["variables"]:
            missing_fields.append("variables")
        if not (parameters["station"] or parameters["zone"]):
            missing_fields.append("zone_or_station_or_mission")
        if not parameters["zone"]:
            missing_fields.append("output_format")
    else:
        intent = "unknown"
        missing_fields = ["source"]

    # de-duplicate while preserving order
    deduped_missing = []
    for field in missing_fields:
        if field not in deduped_missing:
            deduped_missing.append(field)

    recommended_next_step = "proceed" if not deduped_missing else "ask_clarification"

    return {
        "source_id": source_id,
        "source_label": source_meta.get("label", "Unknown"),
        "intent": intent,
        "parameters": parameters,
        "missing_fields": deduped_missing,
        "recommended_next_step": recommended_next_step,
        "clarification_question": _clarification_question(source_id, deduped_missing),
        "found": bool(source_meta.get("found", source_id != "unknown")),
    }
'''

registry.register(Tool(
    name="copepod_sources_meta",
    tags=frozenset({"copepod_sources_meta"}),
    code=_code,
))
