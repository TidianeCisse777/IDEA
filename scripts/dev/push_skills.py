"""Pousse tous les skills locaux vers LangSmith Context Hub (production + staging)."""
from pathlib import Path
import sys

from dotenv import load_dotenv
from langsmith import Client

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "agents" / "skills"
sys.path.insert(0, str(REPO_ROOT))

from tools.skill_manifest import load_skill_document  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
client = Client()

try:
    from langsmith.schemas import FileEntry
except ImportError:
    FileEntry = None


def _hub_name(stem: str) -> str:
    return f"copepod-{stem.replace('_', '-')}"


def push_skill(stem: str, content: str, env: str) -> str:
    if not hasattr(client, "push_skill") or FileEntry is None:
        raise RuntimeError("Installed LangSmith SDK does not expose skill push APIs")
    hub_name = _hub_name(stem)
    identifier = f"{hub_name}:{env}"
    client.push_skill(
        identifier,
        files={"SKILL.md": FileEntry(content=content)},
    )
    return identifier


failures: list[tuple[str, str]] = []
for md_file in sorted(SKILLS_DIR.glob("*.md")):
    load_skill_document(md_file)
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
    raise SystemExit(1)
