from pathlib import Path

import yaml


WORKFLOW_PATH = Path(".github/workflows/docker-build.yml")


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def test_docker_build_uses_inline_registry_cache() -> None:
    workflow = load_workflow()
    build_steps = workflow["jobs"]["build"]["steps"]
    build_push = next(
        step for step in build_steps if step.get("uses") == "docker/build-push-action@v6"
    )

    assert build_push["with"]["cache-from"] == (
        "type=registry,ref=ghcr.io/${{ env.OWNER }}/copepod-agent:latest"
    )
    assert build_push["with"]["cache-to"] == "type=inline"


def test_new_push_cancels_obsolete_build() -> None:
    workflow = load_workflow()

    assert workflow["concurrency"] == {
        "group": "copepod-agent-${{ github.ref }}",
        "cancel-in-progress": True,
    }


def test_langsmith_sync_is_not_in_docker_build_workflow() -> None:
    workflow = load_workflow()

    assert set(workflow["jobs"]) == {"build"}
