"""Pousse le system prompt copépodes vers LangSmith Hub."""
from dotenv import load_dotenv
load_dotenv()

from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(COPEPOD_SYSTEM_PROMPT),
    ("human", "{input}"),
])

client = Client()
url = client.push_prompt("copepod-system-prompt", object=prompt)
print(f"Prompt poussé : {url}")
