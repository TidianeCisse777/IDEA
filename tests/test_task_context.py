"""Task-context continuity contracts for multi-turn analyses."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.context_working_set import build_working_set
from agents.exploration_state import (
    ResourceRecord,
    new_exploration_run,
    render_task_context,
)


def test_task_context_keeps_recent_user_instructions_for_short_followup():
    messages = [
        HumanMessage(
            content="Calcule séparément les mesures UVP et filet, sans jointure."
        ),
        AIMessage(content="Les deux tableaux resteront séparés."),
        HumanMessage(
            content="Limite-les aux profils et aux stations sur lesquels on travaille."
        ),
        AIMessage(content="Le périmètre sera limité aux sept stations retenues."),
        HumanMessage(content="Fais les deux tableaux."),
    ]
    run = new_exploration_run("Fais les deux tableaux.", ())

    context = render_task_context(run, messages=messages)

    assert "Objective: Fais les deux tableaux." in context
    assert "Recent user instructions" in context
    assert "sans jointure" in context
    assert "Limite-les aux profils et aux stations" in context
    assert "Les deux tableaux resteront séparés" not in context


def test_old_assistant_reference_cannot_become_primary_dataframe():
    resources = (
        ResourceRecord(
            resource_id="resource:df_wrong_join",
            kind="table",
            name="df_wrong_join",
            source="analysis:derived",
            persisted=True,
            age_turns=1,
        ),
        ResourceRecord(
            resource_id="resource:df_uvp_net_matches",
            kind="table",
            name="df_uvp_net_matches",
            source="analysis:derived",
            persisted=True,
            age_turns=0,
        ),
    )
    messages = [
        HumanMessage(content="Tente de récupérer l'abondance."),
        AIMessage(content="Résultat conservé dans `df_wrong_join`."),
        HumanMessage(content="Non, fais plutôt deux tableaux séparés."),
    ]

    working_set = build_working_set(resources, messages)

    assert working_set.names_for_role("primary") == ()
    stale = next(
        entry for entry in working_set.entries if entry.data_ref == "df_wrong_join"
    )
    assert stale.role == "recent"
    assert stale.authority == "assistant_reference"


def test_previous_turn_tool_output_is_not_primary_on_new_user_turn():
    resources = (
        ResourceRecord(
            resource_id="resource:df_wrong_join",
            kind="table",
            name="df_wrong_join",
            source="analysis:derived",
            persisted=True,
            age_turns=0,
        ),
        ResourceRecord(
            resource_id="resource:df_uvp_net_matches",
            kind="table",
            name="df_uvp_net_matches",
            source="analysis:derived",
            persisted=True,
            age_turns=1,
        ),
    )
    messages = [
        HumanMessage(content="Essaie d'ajouter l'abondance."),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "run_pandas",
                "args": {"code": "result = df_uvp_net_matches.copy()"},
                "id": "join-1",
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content="Jointure persistée.",
            name="run_pandas",
            tool_call_id="join-1",
            artifact={
                "status": "success",
                "persisted": True,
                "data_ref": "df_wrong_join",
                "summary": "51 lignes, abondance absente",
            },
        ),
        AIMessage(content="Résultat conservé dans `df_wrong_join`."),
        HumanMessage(content="Ne réutilise pas la jointure; fais deux tableaux."),
    ]

    working_set = build_working_set(resources, messages)

    assert working_set.names_for_role("primary") == ()
    previous_output = next(
        entry for entry in working_set.entries if entry.data_ref == "df_wrong_join"
    )
    assert previous_output.role == "recent"
    assert previous_output.authority == "tool"
