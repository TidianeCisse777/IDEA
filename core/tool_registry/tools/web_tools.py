from core.tool_registry.registry import Tool, registry

_code = '''def extract_web_query_response(web_query_response):
    # Find the first output message
    output_msg = next(
        (item for item in web_query_response.output if getattr(item, "type", None) == "message"),
        None
    )
    if not output_msg:
        return {"content": None, "urls": []}

    texts, urls = [], []
    for part in getattr(output_msg, "content", []):
        if getattr(part, "text", None):
            texts.append(part.text)
            for ann in getattr(part, "annotations", []) or []:
                if getattr(ann, "type", "") == "url_citation":
                    urls.append({"title": ann.title, "url": ann.url})
    return {"content": "\\n\\n".join(texts) if texts else None, "urls": urls}

def web_search(web_query):
    web_query_response = responses(
        model=LLM_MODEL,
        input=[
            {"role": "system", "content": "You are a concise research assistant that only searches the web and only responds with search results."},
            {"role": "user", "content": web_query}
        ],
        tools=[{
            "type": "web_search"  # enables web search with default medium context size
        }],
        stream=False
    )
    #return {"web_query_response": web_query_response}
    return extract_web_query_response(web_query_response)'''

registry.register(Tool(name="web_tools", tags=frozenset({"web"}), code=_code))
