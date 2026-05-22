from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    CODEX_HOME = "/app/.codex"
    CODEX_SANDBOX = f"/app/static/{user_id}/{session_id}/Codex_Sandbox"
    return f"""            COMMAND LINE INTERFACE (CLI) TOOLS:
            You have access to many command line tools, including the following specific tool:

            1. A command line coding agent called Codex.
            Codex can explore, summarize, edit, and run code in the local workspace.
                - Make sure that `{CODEX_SANDBOX}` exists before running Codex.
                - cd to the Codex_Sandbox: cd {CODEX_SANDBOX}
                - Then call: codex exec --full-auto --skip-git-repo-check "<instruction>"
                - Login should happen automatically using an authentication file (usually no need to manually login).
                - If login fails, then you may authenticate it by logging in with the environment variable:
                    printenv OPENAI_API_KEY | codex login --with-api-key
                - IMPORTANT: Do not expose the OPENAI_API_KEY or any authentication tokens in your responses to the user.
            Use Codex when:
                - The user requests a code explanation, refactor, or improvement.
                - You need to summarize, analyze, or document a repository.
                - You want to generate or modify source code in an existing project.
                - You need to identify where specific functionality is implemented.
            Rules:
                - Always run Codex in exec mode (e.g., codex exec --full-auto --skip-git-repo-check "Summarize this repository").
                - Work only within {CODEX_SANDBOX}:
                    * Repositories: {CODEX_SANDBOX}/repos
                    * Temporary files: {CODEX_SANDBOX}/tmp
                - Invoke Codex directly from the shell using codex exec ... by default.
                - Do not wrap Codex in Python subprocess unless requested or if direct shell execution is unavailable.
                - For repository tasks, prefer: codex exec -C /path/to/repo --full-auto "<instruction>"
                - Configuration, Agent working agreements, Skills, and Authentication files are in {CODEX_HOME}.
                - Do not modify files outside these paths.
                - Keep commands clear and descriptive to guide Codex effectively.
                - Remind the user that Codex operations may take time.
                - IMPORTANT: Confirm that `{CODEX_SANDBOX}` exists prior to running Codex."""


renderer.register(InstructionBlock(
    name="cli_reference",
    tags=frozenset({"cli"}),
    render=_render,
))
