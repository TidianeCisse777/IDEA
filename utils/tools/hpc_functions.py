hpc_tool_string = """
# HPC Cluster Tools
# These functions are injected into the interpreter sandbox.
# They delegate to backend.hpc_manager which handles the actual SSH/SLURM logic.
from backend.hpc_manager import (
    check_hpc_connection,
    submit_hpc_job,
    poll_hpc_job,
    get_hpc_job_output,
    cancel_hpc_job,
    list_hpc_jobs,
)
"""
