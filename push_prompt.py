"""Pousse le system prompt copépodes vers LangSmith Hub.

Le prompt contient des accolades littérales (ex. `{south, west, north, east}`
dans les exemples de tool returns) qui seraient interprétées comme variables
en f-string. On utilise le format mustache (variables = `{{var}}`) pour
conserver les `{...}` littéraux et n'expose qu'une seule variable d'entrée :
`{{input}}` côté human.
"""
from dotenv import load_dotenv
load_dotenv()

from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        COPEPOD_SYSTEM_PROMPT, template_format="mustache",
    ),
    ("human", "{{input}}"),
], template_format="mustache")

client = Client()
url = client.push_prompt("copepod-system-prompt", object=prompt)
print(f"Prompt poussé : {url}")
