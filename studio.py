"""Entrypoint LangGraph Studio — exporte le graph copépodes sans checkpointer.

Studio gère sa propre persistance — on retire le MemorySaver ici.
En production (serve.py), le checkpointer AsyncSqliteSaver reste actif.
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
from tools.data_tools import make_tools
from tools.bio_oracle_sources import make_bio_oracle_tools
from tools.amundsen_sources import make_amundsen_tools
from tools.ecopart_sources import make_ecopart_tools
from tools.copepod_sources import make_source_tools
from tools.sql_workspace import make_sql_tools
from tools.rag_tool import make_rag_tool
from tools.skill_tool import make_skill_tool

load_dotenv()

_THREAD_ID = "studio"

_llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL"),
    max_retries=2,
)

_tools = (
    make_tools(_THREAD_ID)
    + make_source_tools(_THREAD_ID)
    + make_bio_oracle_tools(_THREAD_ID)
    + make_amundsen_tools(_THREAD_ID)
    + make_ecopart_tools(_THREAD_ID)
    + [make_rag_tool(), make_skill_tool()]
)
try:
    _tools += make_sql_tools(_THREAD_ID)
except ValueError:
    pass

# Pas de checkpointer — Studio injecte le sien automatiquement
graph = create_react_agent(
    _llm,
    _tools,
    prompt=COPEPOD_SYSTEM_PROMPT,
)
