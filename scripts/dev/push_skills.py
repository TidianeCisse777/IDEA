"""Pousse tous les skills locaux vers LangSmith Context Hub (production + staging)."""
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client
from langsmith.schemas import FileEntry

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "agents" / "skills"
load_dotenv(REPO_ROOT / ".env")
client = Client()


def _hub_name(stem: str) -> str:
    return f"copepod-{stem.replace('_', '-')}"


def push_skill(stem: str, content: str, env: str) -> str:
    hub_name = _hub_name(stem)
    identifier = f"{hub_name}:{env}"
    client.push_skill(
        identifier,
        files={"SKILL.md": FileEntry(content=content)},
    )
    return identifier


failures: list[tuple[str, str]] = []
for md_file in sorted(SKILLS_DIR.glob("*.md")):
    content = md_file.read_text(encoding="utf-8")
    for env in ("production", "staging"):
        hub_name = _hub_name(md_file.stem)
        identifier = f"{hub_name}:{env}"
        try:
            existing = client.pull_skill(identifier)
            existing_content = existing.files.get("SKILL.md")
            if existing_content and existing_content.content == content:
                print(f"—  {identifier} (already up to date, skipped)")
                continue
        except Exception:
            pass  # not found or unreadable → push
        try:
            push_skill(md_file.stem, content, env)
            print(f"✓  {identifier} (pushed)")
        except Exception as e:
            short = str(e).splitlines()[0][:160]
            print(f"✗  {identifier} — {short}")
            failures.append((identifier, short))

if failures:
    print(f"\n{len(failures)} échec(s) :")
    for ident, msg in failures:
        print(f"  - {ident}: {msg}")
