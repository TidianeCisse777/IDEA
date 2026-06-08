"""RAG tool LangChain — base de connaissances copépodes (slice 3)."""
from langchain_core.tools import tool

from core.copepod_rag.query import query_copepod_rag


def make_rag_tool():
    """Crée le tool RAG copépodes. Crash au démarrage si ChromaDB manquant."""

    @tool
    def query_copepod_knowledge_base(question: str) -> str:
        """Interroge la base de connaissances sur les copépodes marins.
        Utilise cet outil pour répondre aux questions sur :
        - la signification des colonnes EcoTaxa/EcoPart/CTD
        - les méthodes d'analyse (morphométrie, taxonomie, lipides)
        - les espèces de copépodes et leur écologie
        - les protocoles de collecte Amundsen
        Ne remplace pas l'analyse de données réelles — utilise run_pandas pour ça.
        """
        try:
            chunks = query_copepod_rag(question, top_k=3)
            if not chunks:
                return "Aucun résultat trouvé dans la base de connaissances."
            parts = []
            for c in chunks:
                parts.append(f"**{c['title']}** (Source : {c['doc']})\n{c['content']}")
            return "\n\n---\n\n".join(parts)
        except Exception as e:
            return f"Base de connaissances indisponible : {e}"

    return query_copepod_knowledge_base
