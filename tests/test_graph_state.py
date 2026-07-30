"""Tests TDD — contexte de retouche du dernier graphique."""


def test_graph_edit_reference_includes_last_script_and_plot_table(tmp_path):
    from tools.graph_state import graph_edit_reference
    from tools.session_store import SessionStore

    store = SessionStore(tmp_path)
    store.set(
        "graph-edit-thread:last_graph_state",
        None,
        {
            "code": "fig, ax = plt.subplots()\nax.legend()",
            "graph_id": "abc123",
            "plot_data_ref": "df_graph_plot",
        },
    )

    reference = graph_edit_reference(store, "graph-edit-thread")

    assert "LAST GRAPH AVAILABLE" in reference
    assert "df_graph_plot" in reference
    assert "ax.legend()" in reference
    assert "modify this script" in reference.lower()
    assert "reproduces the last validated render" in reference.lower()
    assert "use it only" in reference.lower()
    assert "do not use it" in reference.lower()
