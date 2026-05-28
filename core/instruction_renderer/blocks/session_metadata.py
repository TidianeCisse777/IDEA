from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    host = ctx["host"]
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    static_dir = ctx["static_dir"]
    upload_dir = ctx["upload_dir"]
    online_mode_enabled = bool(ctx.get("online_mode_enabled", False))
    online_mode_state = "ON" if online_mode_enabled else "OFF"
    return f"""            The host is {host}.
            The user_id is {user_id}.
            The session_id is {session_id}.
            Mode En Ligne: {online_mode_state}. Allowed online sources: OGSL, Bio-ORACLE.
            The uploaded files are available in {static_dir}/{user_id}/{session_id}/{upload_dir} folder. Use the file path to access the files when asked to analyze uploaded files"""


renderer.register(InstructionBlock(
    name="session_metadata",
    tags=frozenset({"session"}),
    render=_render,
))
