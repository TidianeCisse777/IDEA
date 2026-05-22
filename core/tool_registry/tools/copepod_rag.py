from core.tool_registry.registry import Tool, registry

_code = '''
def query_copepod_knowledge_base(question, session_id=None, top_k=3):
    """Search the copepod domain knowledge base for relevant information.

    Use this when you need to understand:
    - What a column name means (e.g. acq_pixel, classif_qual, depth_min)
    - How to compute a biological metric (ESD, biovolume, carbon biomass)
    - What an online source provides and how to query it
    - Species biology for Calanus glacialis vs hyperboreus vs finmarchicus

    The LLM is free to call this at any point — before, during, or after
    using other tools. Results are chunks from 5 domain docs.

    Args:
        question (str): Natural language question in French or English.
        session_id (str, optional): Session ID for Langfuse tracing.
        top_k (int): Number of chunks to return (default 3).

    Returns:
        list[dict]: Top-k chunks with keys:
            chunk_id, doc, title, content, score (cosine distance, lower=better)
    """
    import sys
    import importlib.util
    from pathlib import Path

    rag_path = Path(__file__).parent.parent.parent / "core" / "copepod_rag" / "query.py"
    if not rag_path.exists():
        return [{"error": f"RAG module not found at {rag_path}"}]

    spec = importlib.util.spec_from_file_location("copepod_rag_query", rag_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return mod.query_copepod_rag(question, top_k=top_k, session_id=session_id)
'''

registry.register(Tool(
    name="copepod_rag",
    tags=frozenset({"copepod_rag"}),
    code=_code
))
