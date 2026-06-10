"""Smoke test — vérifie que LangChain + OpenRouter + LangSmith sont bien câblés."""
from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

llm = ChatOpenAI(model="openai/gpt-5.4-mini")

print("Envoi d'un message test...")
response = llm.invoke([HumanMessage(content="Réponds juste 'OK LangChain fonctionne' en français.")])
print(f"Réponse : {response.content}")
print("\nVérifie LangSmith → https://smith.langchain.com → projet 'copepod-agent'")
