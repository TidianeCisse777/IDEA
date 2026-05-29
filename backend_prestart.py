import logging
import re

from sqlalchemy import Engine
from sqlmodel import Session, select
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from core.db import engine


def _patch_oi_extract_payload():
    """Patch OI's _extract_payload to detect markdown blocks and to=execute format."""
    path = "/opt/venv/lib/python3.11/site-packages/interpreter/core/llm/run_tool_calling_llm.py"
    try:
        with open(path) as f:
            content = f.read()
        if "to_exec_nl" in content:
            return  # latest patch already applied
        old = (
            'def _extract_payload(txt: str):\n'
            '        stripped = (txt or "").strip()\n'
            '\n'
            '        # Prefer a fenced JSON block if present\n'
        )
        new = (
            'def _extract_payload(txt: str):\n'
            '        stripped = (txt or "").strip()\n'
            '\n'
            '        # Detect standard markdown python code blocks\n'
            '        md_fence = re.search(r"```(?:python|py)\\s*([\\s\\S]*?)```", stripped)\n'
            '        if md_fence:\n'
            '            code = md_fence.group(1).strip()\n'
            '            if code:\n'
            '                return ("python", code)\n'
            '\n'
            '        # Detect to=execute code="..." pattern (double-quoted, may contain single quotes)\n'
            '        to_exec = re.search(r\'to=execute\\s+code="(.*?)(?:"\\s*$|"\\s*\\))\', stripped, re.DOTALL)\n'
            '        if not to_exec:\n'
            '            # Last-resort: find code=" and take everything up to the last "\n'
            '            m = re.search(r\'code="(.*)"\\s*$\', stripped, re.DOTALL)\n'
            '            if m:\n'
            '                to_exec = m\n'
            '        if to_exec:\n'
            '            code = to_exec.group(1).replace("\\\\n", "\\n").strip()\n'
            '            if code:\n'
            '                return ("python", code)\n'
            '\n'
            '        # Detect to=execute code=python\\n<code> (no quotes, newline-separated)\n'
            '        to_exec_nl = re.search(r\'(?:to=execute|to execute)\\s+code=\\w*\\s*\\n([\\s\\S]+)\', stripped, re.IGNORECASE)\n'
            '        if to_exec_nl:\n'
            '            code = to_exec_nl.group(1).strip()\n'
            '            if code:\n'
            '                return ("python", code)\n'
            '\n'
            '        # Prefer a fenced JSON block if present\n'
        )
        if old in content:
            with open(path, "w") as f:
                f.write(content.replace(old, new, 1))
            logging.getLogger(__name__).info("Patched OI _extract_payload for markdown + to=execute formats")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not patch OI: {e}")


_patch_oi_extract_payload()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init(db_engine: Engine) -> None:
    try:
        with Session(db_engine) as session:
            # Try to create session to check if DB is awake
            session.exec(select(1))
    except Exception as e:
        logger.error(e)
        raise e


def main() -> None:
    logger.info("Initializing service")
    init(engine)
    logger.info("Service finished initializing")


if __name__ == "__main__":
    main()