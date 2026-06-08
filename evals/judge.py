"""LLM-as-judge — GPT-4o via OpenRouter évalue les réponses de l'agent."""
import os
from openai import OpenAI

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        )
    return _client


JUDGE_SYSTEM = """You are an expert evaluator for a scientific copepod data assistant.
Evaluate the agent's response against the provided criteria.
Return a JSON object with:
- "score": float between 0.0 and 1.0 (1.0 = fully satisfies criteria)
- "reasoning": one sentence explaining the score
"""


def judge(response: str, criteria: str, model: str = "openai/gpt-4o") -> dict:
    """Évalue une réponse agent contre des critères. Retourne {score, reasoning}.

    Args:
        response: La réponse de l'agent à évaluer.
        criteria: Description du comportement attendu.
        model: Modèle judge (défaut gpt-4o via OpenRouter).

    Returns:
        {"score": float, "reasoning": str}
    """
    client = _get_client()
    prompt = f"""Criteria: {criteria}

Agent response:
{response}

Evaluate the response against the criteria."""

    result = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    import json
    content = result.choices[0].message.content
    parsed = json.loads(content)
    return {
        "score": float(parsed.get("score", 0.0)),
        "reasoning": parsed.get("reasoning", ""),
    }


def judge_with_image(response: str, image_b64: str, criteria: str, model: str = "openai/gpt-4o") -> dict:
    """Évalue une réponse agent + image contre des critères visuels.

    Args:
        response: La réponse textuelle de l'agent.
        image_b64: Image base64 PNG produite par run_graph.
        criteria: Description du comportement attendu.
        model: Modèle judge avec vision (défaut gpt-4o via OpenRouter).

    Returns:
        {"score": float, "reasoning": str}
    """
    client = _get_client()
    prompt = f"""Criteria: {criteria}

Agent text response:
{response}

Evaluate both the text response AND the image against the criteria."""

    result = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    import json
    content = result.choices[0].message.content
    parsed = json.loads(content)
    return {
        "score": float(parsed.get("score", 0.0)),
        "reasoning": parsed.get("reasoning", ""),
    }


def make_judge_evaluator(criteria_key: str = "criteria"):
    """Crée un évaluateur LangSmith qui appelle le judge GPT-4o.

    Args:
        criteria_key: Clé dans reference_outputs contenant les critères.

    Returns:
        Fonction évaluateur compatible LangSmith evaluate().
    """
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        response = outputs.get("response", "")
        criteria = reference_outputs.get(criteria_key, "")
        result = judge(response, criteria)
        return {
            "key": "llm_judge",
            "score": result["score"],
            "comment": result["reasoning"],
        }
    return evaluator
