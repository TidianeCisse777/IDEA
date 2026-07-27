from pathlib import Path


def test_env_example_is_consumer_only_and_has_no_publisher_credentials():
    text = Path(".env.example").read_text(encoding="utf-8")

    assert "ECOTAXA_CACHE_MODE=consumer" in text
    assert "ECOTAXA_CACHE_RELEASE_REPOSITORY=TidianeCisse777/IDEA" in text
    assert "ECOTAXA_CACHE_RELEASE_TAG=ecotaxa-cache-current" in text
    for variable in (
        "ECOTAXA_USERNAME",
        "ECOTAXA_PASSWORD",
        "ECOTAXA_CACHE_AUTO_PUBLISH",
        "GITHUB_TOKEN",
    ):
        assert f"{variable}=" not in text
