from pathlib import Path


def test_graph_skills_require_a_single_light_theme_without_dark_templates():
    writer = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8")
    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8")

    assert "## Light theme (mandatory for all graphs)" in writer
    assert "#ffffff" in writer
    assert "#f8fafc" in writer
    assert "plt.style.use(" not in writer
    assert "dark_background" not in writer
    assert "#1a1a1a" not in writer
    assert "#2d2d2d" not in writer
    assert "#1a3a5c" not in writer
    assert 'color="white"' not in writer
    assert "color='white'" not in writer
    assert 'colors="white"' not in writer
    assert "colors='white'" not in writer
    assert "Confidence:" not in writer
    assert "confidence_label" not in writer
    assert "## Uncertainty rendering" not in writer
    assert "### Zoom to data" in writer
    assert "def padded_extent" in writer
    assert "Confidence:" not in planner
    assert "Uncertainty assessment" not in planner
