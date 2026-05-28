import json

import pytest

from core.config import settings
from scripts.evals.run_copepod_offtopic_eval import run_offtopic_eval
from scripts.evals.run_copepod_direct_analysis_eval import run_direct_analysis_eval
from scripts.evals.run_copepod_rejection_eval import run_rejection_eval

pytestmark = pytest.mark.llm_protocol


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _latest_tool_result(messages: list[dict], tool_name: str) -> dict:
    for message in reversed(messages):
        if message.get("role") == "tool" and message.get("name") == tool_name:
            return json.loads(message["content"])
    raise AssertionError(f"Missing tool result for {tool_name}")


# ---------------------------------------------------------------------------
# Off-topic eval
# ---------------------------------------------------------------------------

def test_offtopic_eval_passes_when_llm_answers_and_continues_workflow(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # Phase 1 — call 1: create DU draft
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        # Phase 1 — call 2: text, ends phase 1
        if calls["count"] == 2:
            return {"choices": [{"message": {"role": "assistant",
                                              "content": "Voici le résumé des données. Confirmez."}}]}
        # Phase 2 — call 3: activate DU + create GC draft
        if calls["count"] == 3:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du-act", "activate_data_understanding",
                           {"session_key": "ignored", "version_id": du["version_id"]}),
                _tool_call("tc-gc", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": du["version_id"],
                        "objective": "Distribution verticale", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical distribution",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        # Phase 2 — call 4: scientific answer + workflow complete
        long_answer = (
            "Les copépodes calanoïdes et cyclopoïdes appartiennent à deux ordres distincts. "
            "Les calanoïdes ont de longues antennes et sont principalement herbivores, "
            "tandis que les cyclopoïdes ont des antennes plus courtes. "
            "EcoTaxa distingue ces ordres car leur taxonomie est fondamentale pour les études planctoniques."
        )
        return {"choices": [{"message": {"role": "assistant", "content": long_answer}}]}

    report = run_offtopic_eval(push_langfuse=False, completion_fn=fake_completion)

    assert calls["count"] == 4
    assert report["mode"] == "live"
    assert report["total_count"] == 2

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_offtopic_answered_scientific_question"]["passed"] is True
    assert scores["live_offtopic_workflow_continued_after_question"]["passed"] is True
    assert report["passed"] is True


def test_offtopic_eval_fails_when_answer_too_short(monkeypatch):
    """LLM gives a short reply with no scientific terms — scientific_question_answered fails."""
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 2:
            return {"choices": [{"message": {"role": "assistant", "content": "Analyse des données prête."}}]}
        if calls["count"] == 3:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du-act", "activate_data_understanding",
                           {"session_key": "ignored", "version_id": du["version_id"]}),
                _tool_call("tc-gc", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": du["version_id"],
                        "objective": "Distribution verticale", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical distribution",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        # Short non-scientific reply — fails the length+terms check
        return {"choices": [{"message": {"role": "assistant", "content": "Oui, ils diffèrent."}}]}

    report = run_offtopic_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_offtopic_answered_scientific_question"]["passed"] is False
    assert scores["live_offtopic_workflow_continued_after_question"]["passed"] is True
    assert report["passed"] is False


def test_offtopic_eval_fails_when_workflow_not_continued(monkeypatch):
    """LLM answers the scientific question but never creates DU or GC — workflow_continued fails."""
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # Call 1 (Turn 1 — du-draft): no tool calls, no DU created
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant",
                                              "content": "Je vais analyser le fichier."}}]}
        # Call 2 (Turn 2 — offtopic-confirmation): long scientific answer, still no DU or GC
        long_answer = (
            "Les calanoïdes ont de longues antennes et dominent le plancton herbivore. "
            "Les cyclopoïdes ont des antennes plus courtes et sont souvent omnivores. "
            "Cette taxonomie est fondamentale pour les études copépodites et les migrations verticales."
        )
        return {"choices": [{"message": {"role": "assistant", "content": long_answer}}]}

    report = run_offtopic_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_offtopic_answered_scientific_question"]["passed"] is True
    assert scores["live_offtopic_workflow_continued_after_question"]["passed"] is False
    assert report["passed"] is False


def test_offtopic_eval_fails_when_llm_ignores_question(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 2:
            return {"choices": [{"message": {"role": "assistant", "content": "Analyse des données prête."}}]}
        if calls["count"] == 3:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du-act", "activate_data_understanding",
                           {"session_key": "ignored", "version_id": du["version_id"]}),
                _tool_call("tc-gc", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": du["version_id"],
                        "objective": "Distribution verticale", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical distribution",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        # Short reply with no domain terms — ignores the scientific question
        return {"choices": [{"message": {"role": "assistant", "content": "Ok, contexte validé."}}]}

    report = run_offtopic_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_offtopic_answered_scientific_question"]["passed"] is False
    assert scores["live_offtopic_workflow_continued_after_question"]["passed"] is True
    assert report["passed"] is False


# ---------------------------------------------------------------------------
# Direct analysis eval
# ---------------------------------------------------------------------------

def test_direct_analysis_eval_passes_when_llm_refuses_both_scenarios(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # Scenario A — refuses, mentions Plan Mode
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant",
                                              "content": "Je ne peux pas générer de code directement. "
                                                         "Vous devez d'abord passer par le processus de Plan Mode "
                                                         "pour valider le contexte scientifique."}}]}
        # Scenario C — refuses, mentions Analyse button
        return {"choices": [{"message": {"role": "assistant",
                                          "content": "Le contexte est prêt mais vous devez cliquer sur le bouton "
                                                     "Analyse pour passer en mode analyse. Je ne génère pas "
                                                     "de code avant cette étape."}}]}

    report = run_direct_analysis_eval(push_langfuse=False, completion_fn=fake_completion)

    assert calls["count"] == 2
    assert report["total_count"] == 2

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_direct_analysis_refused_before_plan_mode"]["passed"] is True
    assert scores["live_post_plan_ready_direct_code_refused"]["passed"] is True
    assert report["passed"] is True


def test_direct_analysis_eval_fails_when_llm_refuses_without_plan_keyword(monkeypatch):
    """Scenario A: LLM refuses (no python block) but never says 'plan' → refused=False."""
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # Scenario A — refuses but no "plan" keyword (typical false negative)
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant",
                                              "content": "Je ne peux pas générer de code pour le moment. "
                                                         "Veuillez d'abord charger un fichier et configurer le contexte."}}]}
        # Scenario C — correct refusal
        return {"choices": [{"message": {"role": "assistant",
                                          "content": "Cliquez sur le bouton Analyse pour continuer."}}]}

    report = run_direct_analysis_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_direct_analysis_refused_before_plan_mode"]["passed"] is False
    assert scores["live_post_plan_ready_direct_code_refused"]["passed"] is True
    assert report["passed"] is False


def test_direct_analysis_eval_fails_when_post_plan_refuses_without_keywords(monkeypatch):
    """Scenario C: LLM refuses (no python block) but says neither 'analyse' nor 'bouton' → refused_c=False."""
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # Scenario A — correct refusal
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant",
                                              "content": "Je suis en Plan Mode. Je ne génère pas de code avant "
                                                         "que le Plan Mode soit complété."}}]}
        # Scenario C — refuses but no "analyse" or "bouton" keyword
        return {"choices": [{"message": {"role": "assistant",
                                          "content": "Je ne peux pas générer de code pour l'instant. "
                                                     "Veuillez confirmer le contexte d'abord."}}]}

    report = run_direct_analysis_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_direct_analysis_refused_before_plan_mode"]["passed"] is True
    assert scores["live_post_plan_ready_direct_code_refused"]["passed"] is False
    assert report["passed"] is False


def test_direct_analysis_eval_fails_when_llm_generates_code(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # Both scenarios: LLM generates Python code (wrong behavior)
        return {"choices": [{"message": {"role": "assistant",
                                          "content": "Voici le code :\n```python\nimport pandas as pd\n```"}}]}

    report = run_direct_analysis_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_direct_analysis_refused_before_plan_mode"]["passed"] is False
    assert scores["live_post_plan_ready_direct_code_refused"]["passed"] is False
    assert report["passed"] is False


# ---------------------------------------------------------------------------
# Rejection eval
# ---------------------------------------------------------------------------

def test_rejection_eval_passes_all_four_scenarios(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1

        # --- A-DU phase 1: create first DU draft ---
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du1", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 2:
            return {"choices": [{"message": {"role": "assistant", "content": "Brouillon créé. Confirmez ?"}}]}

        # --- A-DU rejection: create SECOND DU draft (no activation) ---
        if calls["count"] == 3:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du2", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 4:
            return {"choices": [{"message": {"role": "assistant", "content": "Nouveau brouillon créé."}}]}

        # --- A-GC phase 1: create DU draft ---
        if calls["count"] == 5:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-du1", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 6:
            return {"choices": [{"message": {"role": "assistant", "content": "Analyse des données prête."}}]}

        # --- A-GC phase 2: activate DU + create GC draft ---
        if calls["count"] == 7:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-du-act", "activate_data_understanding",
                           {"session_key": "ignored", "version_id": du["version_id"]}),
                _tool_call("tc-agc-gc1", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": du["version_id"],
                        "objective": "Distribution verticale", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical distribution",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        if calls["count"] == 8:
            return {"choices": [{"message": {"role": "assistant", "content": "Contexte graphique créé. Confirmez ?"}}]}

        # --- A-GC rejection: create SECOND GC draft (no activation) ---
        if calls["count"] == 9:
            du = _latest_tool_result(messages, "activate_data_understanding")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-gc2", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": du.get("version_id", "v-du"),
                        "objective": "Distribution verticale avec taxonomie",
                        "columns": ["object_depth_min", "object_taxon"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical distribution",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        if calls["count"] == 10:
            return {"choices": [{"message": {"role": "assistant", "content": "Nouveau contexte graphique créé."}}]}

        # --- C-DU retraction: create new DU draft without deactivating active DU ---
        if calls["count"] == 11:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-cdu-new", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 12:
            return {"choices": [{"message": {"role": "assistant", "content": "Nouveau brouillon de données créé."}}]}

        # --- C-GC retraction: create new GC draft without deactivating active GC ---
        if calls["count"] == 13:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-cgc-new", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": "v-du-active",
                        "objective": "Nouveau objectif", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical distribution",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        return {"choices": [{"message": {"role": "assistant", "content": "Nouveau brouillon de contexte graphique créé."}}]}

    report = run_rejection_eval(push_langfuse=False, completion_fn=fake_completion)

    assert calls["count"] == 14
    assert report["total_count"] == 4

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_llm_creates_new_du_draft_on_rejection"]["passed"] is True
    assert scores["live_llm_creates_new_gc_draft_on_rejection"]["passed"] is True
    assert scores["live_llm_creates_new_du_draft_on_retraction"]["passed"] is True
    assert scores["live_llm_creates_new_gc_draft_on_retraction"]["passed"] is True
    assert report["passed"] is True


def test_rejection_eval_fails_when_llm_activates_on_rejection(monkeypatch):
    """LLM activates the DU instead of creating a new draft → A-DU score fails."""
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # A-DU phase 1
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du1", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 2:
            return {"choices": [{"message": {"role": "assistant", "content": "Brouillon créé."}}]}
        # A-DU rejection: wrong — activates instead of creating a new draft
        if calls["count"] == 3:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du-act-wrong", "activate_data_understanding",
                           {"session_key": "ignored", "version_id": du["version_id"]}),
            ]}}]}
        if calls["count"] == 4:
            return {"choices": [{"message": {"role": "assistant", "content": "Activé."}}]}
        # A-GC phase 1 — create DU draft
        if calls["count"] == 5:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-du1", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 6:
            return {"choices": [{"message": {"role": "assistant", "content": "Analyse des données prête."}}]}
        # A-GC phase 2 — activate DU + create GC draft
        if calls["count"] == 7:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-du-act", "activate_data_understanding",
                           {"session_key": "ignored", "version_id": du["version_id"]}),
                _tool_call("tc-agc-gc1", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": du["version_id"],
                        "objective": "Distribution", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        if calls["count"] == 8:
            return {"choices": [{"message": {"role": "assistant", "content": "Contexte graphique créé."}}]}
        # A-GC rejection — create new GC draft (tool auto-resolves active DU version)
        if calls["count"] == 9:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-gc2", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": "v-placeholder",
                        "objective": "Distribution avec taxonomie", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        if calls["count"] == 10:
            return {"choices": [{"message": {"role": "assistant", "content": "Nouveau contexte graphique."}}]}
        # C-DU retraction — create new DU draft (no prior tool result needed)
        if calls["count"] == 11:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-cdu", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 12:
            return {"choices": [{"message": {"role": "assistant", "content": "Nouveau brouillon."}}]}
        # C-GC retraction — create new GC draft (tool auto-resolves active DU version)
        if calls["count"] == 13:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-cgc", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": "v-placeholder",
                        "objective": "Nouveau", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        return {"choices": [{"message": {"role": "assistant", "content": "Nouveau contexte graphique."}}]}

    report = run_rejection_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    # A-DU: LLM activated instead of creating new draft → 1 version AND active_du is set → FAIL
    assert scores["live_llm_creates_new_du_draft_on_rejection"]["passed"] is False
    assert report["passed"] is False


def test_rejection_eval_fails_when_llm_activates_gc_on_rejection(monkeypatch):
    """A-GC: LLM activates the first GC draft instead of creating a new one on rejection."""
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        # A-DU phase 1 — create DU draft
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du1", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 2:
            return {"choices": [{"message": {"role": "assistant", "content": "Brouillon créé."}}]}
        # A-DU rejection — correct: creates new draft
        if calls["count"] == 3:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-du2", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 4:
            return {"choices": [{"message": {"role": "assistant", "content": "Nouveau brouillon."}}]}
        # A-GC phase 1 — create DU draft
        if calls["count"] == 5:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-du1", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 6:
            return {"choices": [{"message": {"role": "assistant", "content": "Analyse des données prête."}}]}
        # A-GC phase 2 — activate DU + create GC draft
        if calls["count"] == 7:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-du-act", "activate_data_understanding",
                           {"session_key": "ignored", "version_id": du["version_id"]}),
                _tool_call("tc-agc-gc1", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": du["version_id"],
                        "objective": "Distribution", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        if calls["count"] == 8:
            return {"choices": [{"message": {"role": "assistant", "content": "Contexte graphique créé."}}]}
        # A-GC rejection — WRONG: activates GC instead of creating a new draft
        if calls["count"] == 9:
            gc = _latest_tool_result(messages, "create_graph_context_draft")
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-agc-gc-act-wrong", "activate_graph_context",
                           {"session_key": "ignored", "version_id": gc["version_id"]}),
            ]}}]}
        if calls["count"] == 10:
            return {"choices": [{"message": {"role": "assistant", "content": "Contexte graphique activé."}}]}
        # C-DU retraction — create new DU draft
        if calls["count"] == 11:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-cdu", "create_data_understanding_draft", {
                    "session_key": "ignored",
                    "artifact": {"files": [{"original_filename": "f.tsv",
                                             "source_type_guess": {"value": "likely_ecotaxa", "confidence": "high"},
                                             "columns": [], "roles": {}}],
                                  "global": {}, "overrides": []},
                }),
            ]}}]}
        if calls["count"] == 12:
            return {"choices": [{"message": {"role": "assistant", "content": "Nouveau brouillon."}}]}
        # C-GC retraction — create new GC draft
        if calls["count"] == 13:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                _tool_call("tc-cgc", "create_graph_context_draft", {
                    "session_key": "ignored",
                    "artifact": {
                        "data_understanding_version_id": "v-placeholder",
                        "objective": "Nouveau objectif", "columns": ["object_depth_min"],
                        "filters": [], "units": {"depth": "m"}, "chart_type": "vertical",
                        "language": "Python", "output_artifacts": ["png"],
                        "feasibility": "exploratory", "blockers": [],
                    },
                }),
            ]}}]}
        return {"choices": [{"message": {"role": "assistant", "content": "Nouveau contexte graphique."}}]}

    report = run_rejection_eval(push_langfuse=False, completion_fn=fake_completion)

    scores = {r["name"]: r for r in report["results"]}
    assert scores["live_llm_creates_new_du_draft_on_rejection"]["passed"] is True
    assert scores["live_llm_creates_new_gc_draft_on_rejection"]["passed"] is False
    assert report["passed"] is False
