from pathlib import Path


def test_requirements_include_scikit_learn_for_ordination_workflows():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "scikit-learn" in requirements


def test_requirements_include_mcp_ecotaxa_dependencies():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "fastmcp>=3.0.0,<4.0.0" in requirements
    assert "apscheduler>=3.11.0,<4.0.0" in requirements
    assert "vcrpy>=7.0.0,<8.0.0" in requirements
