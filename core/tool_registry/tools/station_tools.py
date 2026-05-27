from core.tool_registry.registry import Tool, registry

_code = '''def extract_text_from_station_response(response_dict):
    r = response_dict.get("station_query_response")
    if r is None or not hasattr(r, "output"):
        return None

    for item in r.output:
        if getattr(item, "type", None) == "message":
            for c in getattr(item, "content", []):
                if hasattr(c, "text"):
                    return c.text

    return None

def get_station_info(station_query):
    # LiteLLM
    station_query_response = responses(
        model=LLM_MODEL,
        input=[
            {"role": "system", "content": station_list_appendix},
            {"role": "user", "content": station_query}
        ],
        stream=False
    )
    return extract_text_from_station_response(
        {"station_query_response": station_query_response}
    )'''

registry.register(Tool(name="station_tools", tags=frozenset({"core", "station"}), code=_code))
