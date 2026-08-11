"""Entrypoint LangGraph Studio — exporte le graph copépodes sans checkpointer.

Studio gère sa propre persistance — on retire le MemorySaver ici.
En production (serve.py), le checkpointer AsyncSqliteSaver reste actif.
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
from tools.tool_catalog import build_tool_catalog

load_dotenv()

_THREAD_ID = "studio"

_llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL"),
    max_retries=2,
)

_tools = list(build_tool_catalog(_THREAD_ID).tools)

# Pas de checkpointer — Studio injecte le sien automatiquement
graph = create_agent(
    _llm,
    _tools,
    system_prompt=COPEPOD_SYSTEM_PROMPT,
)
