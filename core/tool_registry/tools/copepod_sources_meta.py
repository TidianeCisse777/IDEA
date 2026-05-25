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
'''

registry.register(Tool(
    name="copepod_sources_meta",
    tags=frozenset({"copepod_sources_meta"}),
    code=_code,
))
