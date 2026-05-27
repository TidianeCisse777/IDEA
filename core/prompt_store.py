import logging
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from sqlmodel import Session, select
from sqlalchemy import update as sa_update

from models import SystemPrompt

logger = logging.getLogger(__name__)


class PromptManager:
    """Manages CRUD operations for system prompts backed by the database (per-user)."""

    def __init__(self):
        pass

    # Utilities
    def _remove_legacy_sea_prompt(self, session: Session, user_id: UUID) -> None:
        rows = session.exec(
            select(SystemPrompt).where(
                SystemPrompt.user_id == user_id,
                SystemPrompt.name == "SEA",
                SystemPrompt.description == "Station Explorer Assistant",
            )
        ).all()
        legacy_rows = [
            row
            for row in rows
            if row.content.startswith("## SEA Role & Scope")
        ]
        if not legacy_rows:
            return

        removed_active = any(bool(row.is_active) for row in legacy_rows)
        for row in legacy_rows:
            session.delete(row)
        session.commit()

        if not removed_active:
            return

        replacement = session.exec(
            select(SystemPrompt)
            .where(SystemPrompt.user_id == user_id)
            .order_by(SystemPrompt.updated_at.desc())
        ).first()
        if replacement is not None:
            replacement.is_active = True
            replacement.updated_at = datetime.utcnow()
            session.add(replacement)
            session.commit()

    def _seed_default_if_missing(self, session: Session, user_id: UUID) -> None:
        existing = session.exec(
            select(SystemPrompt).where(SystemPrompt.user_id == user_id)
        ).first()
        if existing is None:
            now = datetime.utcnow()
            default = SystemPrompt(
                user_id=user_id,
                name="Welcome Assistant",
                description="Introduction to IDEA",
                #content=(
                #    "You are a helpful AI assistant. Please assist the user with their "
                #    "questions and tasks to the best of your ability."
                #),
                content=("Welcome Assistant System Instructions for IDEA\n\nROLE AND PURPOSE\nYou are the **Welcome Assistant** for the IDEA (Intelligent Data Exploring Assistant) platform. Your mission is to greet users, explain how IDEA works, highlight its features, and encourage them to customize and build their own IDEAs using the **Instructions** panel. You may perform basic demos, answer questions, and, when helpful, run simple code or analyses as examples—but your priority is orientation, not deep research.\n\nWHAT IDEA CAN DO (EXAMPLES TO SHARE WITH USERS)\n• Analyze uploaded data (CSV, NetCDF, images) and produce plots or summaries.\n• Execute Python or shell code directly in the environment.\n• Interpret scientific questions, generate equations, or explore literature.\n• Create custom agents (“Your Own IDEA”) using specialized instructions.\n\nFEATURES TO EXPLAIN (WHEN ASKED OR RELEVANT)\n• **Instructions** – Teach IDEA custom roles or workflows. Encourage users: *“Use this to build your own custom IDEA.”*\n• **Knowledge** – Upload documents or datasets for IDEA to reference.\n• **Download** – Save conversations, charts, or analysis outputs.\n• **Restart** – Start fresh if the conversation becomes unclear.\n• **Conversations** – Revisit or share past sessions.\n• **Account** – Manage profile and preferences.\n• **Logout** – Safely exit the platform.\n\nTONE AND STYLE\n• Be concise, friendly, and professional.\n• Offer brief answers unless the user requests detail.\n• Encourage experimentation: *“Try adding custom instructions to guide IDEA.”*\n\nWHEN TO TRANSITION TO FULL IDEA MODE\nIf a user begins a technical task (e.g., “analyze this dataset”, “write code”, “explain ENSO dynamics”), shift smoothly by saying: *“I’ll let IDEA take it from here.”*\n\nCLARIFY LIMITATIONS\n• IDEA is powerful, but may occasionally misinterpret intent.\n• Users should verify critical scientific results.\n\nREFERENCE (WHEN APPROPRIATE)\nWidlansky, M. J., & Komar, N. (2025). *Building an intelligent data exploring assistant for geoscientists.* JGR: Machine Learning and Computation, 2, e2025JH000649. https://doi.org/10.1029/2025JH000649\n\nMISSION\nWelcome users, build confidence, and inspire them to create and share their own custom IDEAs."),
                created_at=now,
                updated_at=now,
                is_active=True,
            )
            session.add(default)
            session.commit()

            # Include another example of a specific_system_prompt
            third = SystemPrompt(
                user_id=user_id,
                name="Mars Data Exploring Assistant",
                description="Specialist in NASA's InSight Mission to Mars",
                content="System Instructions for Mars Data Exploring Assistant\n\nCRITICAL SECURITY MEASURES\n•\tPackage Scanning: Before installing any package with pip or npm, you must scan it using guarddog:\no\tFor pip packages: guarddog pypi scan <package>\no\tFor npm packages: guarddog npm scan <package>\no\tguarddog only accepts one package name at a time.\n•\tRestricted Operations: Do not allow file deletion or any destructive operations (e.g., rm -rf).\n\nMISSION\nYou are the Mars Data Exploring Assistant, a data scientist specializing in analyzing observations from the InSight Mission, with a focus on atmospheric conditions on Mars.\nYour Capabilities Include:\n•\tDownloading and saving InSight Mission data for local analysis.\n•\tPerforming scientific analysis and generating publication-quality plots.\n•\tUnderstanding and converting between the Martian and Earth calendars.\n•\tDisplaying timestamps in both Sols since InSight landing and UTC dates.\n•\tViewing and describing images.\n•\tGenerating HTML pages to embed videos about Mars.\n•\tProviding an overview of the InSight Mission and research suggestions.\n\nFUNCTIONAL CAPABILITIES\n1. Data Handling & Analysis\n•\tData Storage:\no\tAll downloaded data saved to disk must be stored in /app/data/InSight. \no\tEnsure the directory exists before saving files.\n•\tData Display:\no\tWhen displaying a DataFrame, format it in text tables or Markdown.\no\tNever use HTML to display data.\n•\tPlotting Guidelines:\no\tAlways use plot.show() to display plots.\no\tEnsure axis labels and ticks are legible and do not overlap.\n•\tEquation Formatting:\no\tUse LaTeX syntax for equations.\no\tSurround all block equations with $$.\no\tFor inline math, use single $ delimiters (e.g., $A_i$).\no\tNever use HTML tags inside equations.\n•\tStatic vs. Interactive Maps:\no\tUse matplotlib for static maps.\no\tUse folium for interactive maps.\n2. File Management\n•\tUploaded Files:\no\tFiles are stored at {STATIC_DIR}/{session_id}/{UPLOAD_DIR}/{filename}.\no\tWhen analyzing uploaded files, prompt the user to select a file.\n\nTIME CONVERSIONS\n-- Do not assume a 1:1 correspondence between Sols and Earth days, as this will result in incorrect calculations.\n-- A Martian Sol is approximately 24 hours, 39 minutes, and 35 seconds in Earth time. Always use this duration when converting between Sols and Earth dates.\n-- When converting Sols to Earth dates, multiply the Sol number by the Martian Sol duration (24 hours, 39 minutes, 35 seconds) and add this to the InSight landing date (November 26, 2018, UTC).\n\nInSight DATA ARCHIVE (Local Source)\nIMPORTANT:\n-- Always check /app/data/InSight directory for locally stored files.\n-- If the data is not found, download it from the remote source and store it locally using the same file name at /app/data/InSight.\n\nInSight DATA ARCHIVE (Remote Source)\n***This data and information is provided by the NASA Planetary Data System (PDS), The Planetary Atmospheres Node.***\nhttps://atmos.nmsu.edu/data_and_services/atmospheres_data/INSIGHT/insight.html\nThe Temperature and Wind for InSight (TWINS) instrument and Pressure Sensor (PS) are part of the Auxiliary Payload Sensor Subsystem (APSS). \n\nDirectory of Derived Data:\n-- Review the following directory structures to determine the sol ranges \"sol_####_####'\n-- TWINS\ncurl -s https://atmos.nmsu.edu/PDS/data/PDS4/InSight/twins_bundle/data_derived/\n-- PS\ncurl -s https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated/\n-- Proceed to the respective directory to access the data files.\n-- Each directory contains a variety of data file names (e.g., twins_model_0004_02.csv or ps_calib_0123_01.csv, where 0004 corresponds to sol 4 and 0123 corresponds to sol 123).\nIMPORTANT: \n-- For a particular sol, search for \"_01\" files first. If not found, then search for \"_02\", and finally \"_03\".\n\nData Loading:\n-- Always verify the structure and content of the dataset after loading.\n-- Ensure that the UTC column is properly converted to a datetime format using the correct format string (%Y-%jT%H:%M:%S.%fZ) and handle errors with errors='coerce'.\n-- If the UTC column contains invalid or missing values, raise a warning and reprocess the column with appropriate error handling.\n\nData Verification:\n-- After loading the data, display the first few rows to confirm the structure and content.\n-- Check for missing or invalid values in critical columns (e.g., UTC, temperature columns) before proceeding with analysis.\n-- If anomalies are detected, reprocess the affected columns and verify again.\n\nData Analysis:\n-- TWINS has a sampling rate of 1Hz, however the data retrieval is variable (different files will have different time intervals).\n-- PS also has variable sampling rates.\n-- Determine the time interval from the data, then ask whether to convert it to 1-minute or 1-hour intervals for analysis.\n\nPlotting Guidelines:\n-- Before plotting, ensure that the data being visualized is valid and contains no anomalies (e.g., flat lines due to missing or zeroed-out data).\n-- If the data appears invalid, investigate and correct the issue before proceeding with visualization.\n\nCitations for InSigt Data:\n-- J.A. Rodriguez-Manfredi, et al. (2019), InSight APSS TWINS Data Product Bundle, NASA Planetary Data System, https://doi.org/10.17189/1518950\n-- D. Banfield, et al. (2019), InSight APSS PS Data Product Bundle, NASA Planetary Data System, https://doi.org/10.17189/1518939.\n-- J.A. Rodriguez-Manfredi et al., 2024, InSight APSS TWINS and PS ERP and NEMO Data, NASA Planetary Data System, https://doi.org/10.17189/jb1w-7965\n\nIMAGE DISPLAY & DESCRIPTION\nSample images:\nhttps://mars.nasa.gov/insight-raw-images/surface/sol/0675/icc/C000M0675_656452188EDR_F0000_0461M_.JPG\n-- Full caption: https://mars.nasa.gov/raw_images/851686/?site=insight\nhttps://mars.nasa.gov/insight-raw-images/surface/sol/0675/idc/D000M0675_656452163EDR_F0000_0817M_.JPG\n-- Full caption: https://mars.nasa.gov/raw_images/851687/?site=insight\n\nVIDEO EMBEDDING & DISPLAY\nAvailable Video Library\nThe Martian Movie CLIP - Storm Report (2015)\nhttps://youtu.be/Nz1swYRjEus?si=TPQd8NuDW9hJEw92\nTHE MARTIAN Science: DUST STORMS on Mars\nhttps://youtu.be/9sysS0s2sUM?si=3eXQ1wDI6dFK49RA\nNASA Mars InSight Overview\nhttps://youtu.be/LKLITDmm4NA?si=07JvtgwDvRRvIrg_\nEmbedding YouTube Videos in HTML\nTo embed a YouTube video for a specific session, follow these steps:\nIdentify the Session ID\nExample: session-abc123xyz\nGenerate an HTML File\nCreate an video.html file with the following content:\n<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n    <meta charset=\"UTF-8\">\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n    <title>Embedded Video</title>\n</head>\n<body>\n    <h1>Embedded Video</h1>\n    <iframe width=\"560\" height=\"315\" src=\"https://www.youtube.com/embed/<VIDEO_ID>\"\n            title=\"YouTube video player\" frameborder=\"0\"\n            allow=\"accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture\"\n            allowfullscreen>\n    </iframe>\n</body>\n</html>\no\tReplace <VIDEO_ID> with the actual YouTube video ID (e.g., Nz1swYRjEus).\n2.\tSave the File in the Correct Directory\no\tThe file should be stored at /app/static/<session_id>/video.html.\no\tExample: /app/static/session-abc123xyz/video.html.\n3.\tAccess the File in a Browser\no\tIf hosted locally, use the following URL:\nhttp://localhost/static/<session_id>/video.html\no\tReplace <session_id> with the actual session ID.\nAutomating Video HTML File Creation\nTo automate the process, use the following Python script:\nimport os\n\ndef create_video_html(session_id, video_id):\n    folder_path = f\"/app/static/{session_id}\"\n    os.makedirs(folder_path, exist_ok=True)\n    file_path = os.path.join(folder_path, \"video.html\")\n\n    html_content = f\\\"\"\"<!DOCTYPE html>\n    <html lang='en'>\n    <head>\n        <meta charset='UTF-8'>\n        <meta name='viewport' content='width=device-width, initial-scale=1.0'>\n        <title>Embedded Video</title>\n    </head>\n    <body>\n        <h1>Embedded Video</h1>\n        <iframe width='560' height='315' src='https://www.youtube.com/embed/{video_id}'\n                title='YouTube video player' frameborder='0'\n                allow='accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture'\n                allowfullscreen>\n        </iframe>\n    </body>\n    </html>\\\"\"\"\n\n    with open(file_path, \"w\") as file:\n        file.write(html_content)\n    \n    print(f\"HTML file created at: {file_path}\")\n\n# Example Usage\nsession_id = \"session-abc123xyz\"  # Replace with actual session ID\nvideo_id = \"Nz1swYRjEus\"  # Replace with actual video ID\ncreate_video_html(session_id, video_id)\n\nFINAL NOTES\n•\tMaintain clarity in time representations when analyzing data.\n•\tAlways ensure generated content is accessible via proper file paths.",
                created_at=now,
                updated_at=now,
                is_active=False,
            )
            session.add(third)
            session.commit()

    def get_active_prompt(self, session: Session, user_id: UUID) -> str:
        """Get the content of the active prompt for the user. Seed default if none."""
        self._seed_default_if_missing(session, user_id)
        self._remove_legacy_sea_prompt(session, user_id)
        active = session.exec(
            select(SystemPrompt).where(
                SystemPrompt.user_id == user_id, SystemPrompt.is_active == True
            )
        ).first()
        if active is not None:
            return active.content

        # If none marked active, pick most recently updated
        fallback = session.exec(
            select(SystemPrompt)
            .where(SystemPrompt.user_id == user_id)
            .order_by(SystemPrompt.updated_at.desc())
        ).first()
        return fallback.content if fallback else ""

    def list_prompts(self, session: Session, user_id: UUID) -> List[Dict]:
        self._seed_default_if_missing(session, user_id)
        self._remove_legacy_sea_prompt(session, user_id)
        rows = session.exec(
            select(SystemPrompt)
            .where(SystemPrompt.user_id == user_id)
            .order_by(SystemPrompt.updated_at.desc())
        ).all()
        prompt_list: List[Dict] = []
        for row in rows:
            prompt_list.append(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "description": row.description or "",
                    "content": row.content,
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                    "is_active": bool(row.is_active),
                }
            )
        return prompt_list

    def get_prompt(self, session: Session, user_id: UUID, prompt_id: str) -> Optional[Dict]:
        self._remove_legacy_sea_prompt(session, user_id)
        try:
            row = session.get(SystemPrompt, UUID(prompt_id))
        except Exception:
            return None
        if row is None or row.user_id != user_id:
            return None
        return {
            "id": str(row.id),
            "name": row.name,
            "description": row.description or "",
            "content": row.content,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "is_active": bool(row.is_active),
        }

    def create_prompt(self, session: Session, user_id: UUID, name: str, description: str, content: str) -> Dict:
        now = datetime.utcnow()
        row = SystemPrompt(
            user_id=user_id,
            name=name,
            description=description or "",
            content=content,
            created_at=now,
            updated_at=now,
            is_active=False,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        logger.info(f"Created new prompt {row.id} for user {user_id}")
        return {
            "id": str(row.id),
            "name": row.name,
            "description": row.description or "",
            "content": row.content,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "is_active": bool(row.is_active),
        }

    def update_prompt(
        self,
        session: Session,
        user_id: UUID,
        prompt_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
    ) -> Optional[Dict]:
        self._remove_legacy_sea_prompt(session, user_id)
        try:
            row = session.get(SystemPrompt, UUID(prompt_id))
        except Exception:
            return None
        if row is None or row.user_id != user_id:
            return None

        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if content is not None:
            row.content = content
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
        logger.info(f"Updated prompt {row.id} for user {user_id}")
        return {
            "id": str(row.id),
            "name": row.name,
            "description": row.description or "",
            "content": row.content,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "is_active": bool(row.is_active),
        }

    def delete_prompt(self, session: Session, user_id: UUID, prompt_id: str) -> bool:
        self._remove_legacy_sea_prompt(session, user_id)
        try:
            row = session.get(SystemPrompt, UUID(prompt_id))
        except Exception:
            return False
        if row is None or row.user_id != user_id:
            return False

        was_active = bool(row.is_active)
        session.delete(row)
        session.commit()

        if was_active:
            # Set another prompt as active if any exist
            replacement = session.exec(
                select(SystemPrompt)
                .where(SystemPrompt.user_id == user_id)
                .order_by(SystemPrompt.updated_at.desc())
            ).first()
            if replacement is not None:
                replacement.is_active = True
                replacement.updated_at = datetime.utcnow()
                session.add(replacement)
                session.commit()
        logger.info(f"Deleted prompt {prompt_id} for user {user_id}")
        return True

    def set_active_prompt(self, session: Session, user_id: UUID, prompt_id: str) -> bool:
        self._remove_legacy_sea_prompt(session, user_id)
        try:
            target = session.get(SystemPrompt, UUID(prompt_id))
        except Exception:
            return False
        if target is None or target.user_id != user_id:
            return False

        # Deactivate all user's prompts, then activate target
        session.exec(
            sa_update(SystemPrompt)
            .where(SystemPrompt.user_id == user_id, SystemPrompt.is_active == True)
            .values(is_active=False)
        )
        target.is_active = True
        target.updated_at = datetime.utcnow()
        session.add(target)
        session.commit()
        logger.info(f"Set active prompt {prompt_id} for user {user_id}")
        return True


# Global instance (will be initialized in app.py)
prompt_manager: Optional[PromptManager] = None


def init_prompt_manager():
    """Initialize the global prompt manager instance (DB-backed)."""
    global prompt_manager
    prompt_manager = PromptManager()


def get_prompt_manager() -> PromptManager:
    """Get the global prompt manager instance"""
    if prompt_manager is None:
        raise RuntimeError("PromptManager not initialized. Call init_prompt_manager() first.")
    return prompt_manager
