"""RAG tool LangChain — documentation selected from the active data profile."""
from langchain_core.tools import tool

from core.fish_larvae_rag.query import query_fish_larvae_rag
from core.copepod_rag.query import query_copepod_rag
from tools.session_store import default_store
from tools.tool_result import empty, error, success


def make_rag_tool(thread_id: str | None = None):
    """Create a RAG tool that follows the active biological profile."""

    @tool(response_format="content_and_artifact")
    def query_copepod_knowledge_base(question: str) -> str:
        """Interroge la documentation scientifique adaptée aux données actives.
        Utilise cet outil pour répondre aux questions sur :
        - la signification des colonnes et unités
        - les méthodes d'analyse et de collecte
        - la taxonomie et les protocoles documentés
        - le choix et la préparation d'un graphique scientifique
        - les règles et la sémantique documentées du cache EcoTaxa
        Ne remplace pas l'analyse de données réelles — utilise run_pandas pour ça.
        """
        try:
            active = default_store.get(thread_id) if thread_id else None
            profile = ((active or {}).get("meta") or {}).get("domain_profile") or {}
            is_fish_larvae = profile.get("name") == "fish_larvae"
            chunks = query_fish_larvae_rag(question, top_k=3) if is_fish_larvae else query_copepod_rag(question, top_k=3)
            source = "local fish-larvae knowledge base" if is_fish_larvae else "local copepod knowledge base"
            if not chunks:
                return empty(
                    "Aucun résultat trouvé dans la base de connaissances.",
                    provenance={"source": source},
                    method="semantic retrieval",
                )
            parts = []
            for c in chunks:
                parts.append(f"**{c['title']}** (Source : {c['doc']})\n{c['content']}")
            summary = "\n\n---\n\n".join(parts)
            return success(
                summary,
                provenance={
                    "source": source,
                    "documents": [str(chunk.get("doc", "")) for chunk in chunks],
                },
                method="semantic retrieval",
                metrics={"chunks": len(chunks)},
            )
        except Exception as e:
            return error(
                f"Base de connaissances indisponible : {e}",
                retryable=True,
                provenance={"source": "local fish-larvae knowledge base" if 'is_fish_larvae' in locals() and is_fish_larvae else "local copepod knowledge base"},
                method="semantic retrieval",
            )

    return query_copepod_knowledge_base
