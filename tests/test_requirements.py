from pathlib import Path


def test_requirements_include_scikit_learn_for_ordination_workflows():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "scikit-learn" in requirements
