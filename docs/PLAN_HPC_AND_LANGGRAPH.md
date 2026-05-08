# Integration Plans: HPC Execution & LangGraph

---

## Part 1 — HPC Cluster as a Tool

### Overview

Add HPC job submission as a **set of pre-loaded Python functions** injected into every interpreter session alongside existing tools like `web_search` and `get_climate_index`. The LLM decides when to use them. No core routing or interpreter architecture changes are required.

The HPC connection uses **SSH (via paramiko)** to the cluster head node. Jobs are submitted through the **SLURM** workload manager, which is standard on academic HPC systems (UH Mana, NCAR, NERSC, Jetstream2, etc.).

---

### Connection Flow

```
LLM generates code
  → calls submit_hpc_job(script, partition, nodes, ...)
    → paramiko SSHClient connects to HPC_HOST
    → writes .slurm batch script to HPC_SCRATCH_DIR/{job_uuid}/
    → runs `sbatch job.slurm` on head node
    → captures and returns SLURM job_id
  → LLM polls poll_hpc_job(job_id)
    → SSH: runs `squeue -j {job_id}` → returns status
    → when COMPLETED: copies result files back to /app/static/{user_id}/{session_id}/
  → LLM reads output, continues analysis
```

---

### New Environment Variables (add to `.env` / `.env.example`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `HPC_HOST` | ✅ | — | Hostname or IP of the HPC login/head node (e.g., `mana.its.hawaii.edu`) |
| `HPC_USER` | ✅ | — | SSH username on the cluster |
| `HPC_SSH_KEY_PATH` | ✅ | — | Absolute path to the SSH private key file inside the container (e.g., `/app/.ssh/id_rsa`) |
| `HPC_SSH_PORT` | ❌ | `22` | SSH port |
| `HPC_SCRATCH_DIR` | ✅ | — | Path on HPC where job scripts and outputs are written (e.g., `/scratch/uhslc/idea_jobs`) |
| `HPC_RESULTS_MOUNT` | ❌ | — | Optional: shared filesystem path if HPC scratch is mounted on the IDEA host |
| `HPC_DEFAULT_PARTITION` | ❌ | `shared` | Default SLURM partition/queue |
| `HPC_DEFAULT_ACCOUNT` | ❌ | — | SLURM billing account / allocation name |
| `HPC_DEFAULT_WALLTIME` | ❌ | `01:00:00` | Default max walltime for jobs |
| `HPC_DEFAULT_MEMORY` | ❌ | `8G` | Default memory per node |
| `HPC_CONDA_ENV` | ❌ | — | Conda environment to activate before running user code (e.g., `idea-env`) |
| `HPC_MODULES` | ❌ | — | Space-separated modules to load (e.g., `python/3.11 netcdf4/4.9`) |
| `HPC_MAX_JOBS_PER_USER` | ❌ | `5` | Max concurrent jobs a single user can submit |

**SSH key setup:** The private key needs to be mounted into the container. In `docker-compose.yml`, add a volume like `./.ssh/idea_hpc_key:/app/.ssh/id_rsa:ro`. The corresponding public key must be in `~/.ssh/authorized_keys` on the HPC cluster for `HPC_USER`.

---

### Files to Create / Modify

#### New: `utils/tools/hpc_functions.py`
Contains the full HPC tool implementation as a Python string (same pattern as `custom_functions.py`). Defines:

| Function | Signature | Description |
|---|---|---|
| `submit_hpc_job` | `(script, partition=None, nodes=1, tasks=1, memory=None, time=None, gpus=0, job_name="idea_job")` | Writes and submits a SLURM batch job. Returns `{"job_id": str, "submit_dir": str}` |
| `poll_hpc_job` | `(job_id)` | Returns `{"status": "PENDING\|RUNNING\|COMPLETED\|FAILED", "elapsed": str}` |
| `get_hpc_job_output` | `(job_id, submit_dir)` | Reads stdout/stderr files from HPC scratch, copies any output files back to static dir, returns `{"stdout": str, "stderr": str, "output_files": list}` |
| `cancel_hpc_job` | `(job_id)` | Runs `scancel {job_id}` via SSH |
| `list_hpc_jobs` | `()` | Returns current user's active jobs via `squeue` |
| `check_hpc_connection` | `()` | Quick SSH connectivity test, returns cluster info |

#### Modified: `utils/tools/custom_functions.py`
Append `hpc_tool_string` import at the top of the `custom_tool` string:
```python
# At the end of custom_tool string, add:
custom_tool = custom_tool + hpc_functions.hpc_tool_string
```

#### Modified: `utils/prompts/system_prompt.py`
Add HPC functions to the "Function Usage" section:
```
- `submit_hpc_job(script, ...)`, `poll_hpc_job(job_id)`, `get_hpc_job_output(job_id, dir)` —
  Submit Python/shell scripts to the HPC cluster for compute-intensive tasks.
  Use for: large dataset processing, model training, long-running simulations.
  Do NOT use for: quick analysis, plotting, small data tasks (run those locally).
```

#### Modified: `backend/state.py`
Add HPC constants:
```python
HPC_HOST = os.getenv("HPC_HOST")
HPC_USER = os.getenv("HPC_USER")
HPC_SSH_KEY_PATH = os.getenv("HPC_SSH_KEY_PATH")
HPC_SSH_PORT = int(os.getenv("HPC_SSH_PORT", "22"))
HPC_SCRATCH_DIR = os.getenv("HPC_SCRATCH_DIR", "/scratch/idea_jobs")
HPC_DEFAULT_PARTITION = os.getenv("HPC_DEFAULT_PARTITION", "shared")
HPC_DEFAULT_ACCOUNT = os.getenv("HPC_DEFAULT_ACCOUNT")
HPC_DEFAULT_WALLTIME = os.getenv("HPC_DEFAULT_WALLTIME", "01:00:00")
HPC_DEFAULT_MEMORY = os.getenv("HPC_DEFAULT_MEMORY", "8G")
HPC_CONDA_ENV = os.getenv("HPC_CONDA_ENV")
HPC_MODULES = os.getenv("HPC_MODULES", "")
HPC_ENABLED = all([HPC_HOST, HPC_USER, HPC_SSH_KEY_PATH])
```

#### Modified: `requirements.txt`
Add: `paramiko>=3.4.0`

#### Modified: `docker-compose.yml` and `docker-compose.override.yml`
Add SSH key volume mount to the `web` service:
```yaml
volumes:
  - ./.ssh/idea_hpc_key:/app/.ssh/id_rsa:ro
```

#### New: `routes/hpc.py` (optional — admin/status endpoints)
- `GET /hpc/status` — test SSH connection, return cluster info
- `GET /hpc/jobs` — list active IDEA jobs on the cluster
- `DELETE /hpc/jobs/{job_id}` — cancel a job (superuser only)

---

### SLURM Script Template (generated by `submit_hpc_job`)

```bash
#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --partition={partition}
#SBATCH --account={account}
#SBATCH --nodes={nodes}
#SBATCH --ntasks-per-node={tasks}
#SBATCH --mem={memory}
#SBATCH --time={walltime}
#SBATCH --output={scratch_dir}/job_{job_id}/stdout.txt
#SBATCH --error={scratch_dir}/job_{job_id}/stderr.txt

# Load modules
module load {modules}

# Activate conda
conda activate {conda_env}

# Run user script
python {scratch_dir}/job_{job_id}/user_script.py
```

---

### Security Considerations

- SSH key must be **read-only** inside the container (`:ro` mount)
- `HPC_USER` should be a **service account** with limited cluster permissions, not a personal account
- Job scripts are written to a per-job UUID directory — no path traversal possible
- The system prompt already prohibits `rm -rf` and file deletion; this carries over to HPC scripts
- Rate-limit HPC submissions per user (use `HPC_MAX_JOBS_PER_USER`)
- Never pass environment variables or API keys into the SLURM script

---

### Implementation Order

1. Add env vars to `.env.example`
2. Add HPC constants to `backend/state.py`
3. Add `paramiko` to `requirements.txt`
4. Create `utils/tools/hpc_functions.py`
5. Append to `utils/tools/custom_functions.py`
6. Update `utils/prompts/system_prompt.py`
7. Add SSH key volume to Docker compose files
8. (Optional) Create `routes/hpc.py` status endpoints
9. Test: submit a simple `hostname` job, verify output retrieval

---
---

## Part 2 — LangGraph Integration

### Overview

Replace OpenInterpreter's **internal LLM loop and state management** with a LangGraph graph. OpenInterpreter's **code execution sandbox** (`interpreter.computer`) is retained as the execution environment. LangGraph takes ownership of:
- All LLM calls and tool routing
- Conversation state and memory (via `PostgresSaver` checkpointer)
- Agentic loop logic (plan → execute → reflect → respond)
- MCP tool invocation (as a `ToolNode`)

This is a **significant refactor** touching `routes/chat.py`, `backend/interpreter_manager.py`, and adding several new backend files.

---

### Graph Design

```
User Message
     │
     ▼
┌─────────────┐
│  plan_node  │  LLM reads full state + system prompt, decides next action
└──────┬──────┘
       │  tool_call? ──────────────────────────────────────────┐
       │  execute_code?  ──────────────────────────┐           │
       │  respond?  ──────────────┐                │           │
       ▼                          │                │           │
┌──────────────┐                  │   ┌────────────────────┐  │
│ execute_node │                  │   │  hpc_execute_node  │  │
│ (OI sandbox) │                  │   │  (optional branch) │  │
└──────┬───────┘                  │   └─────────┬──────────┘  │
       │                          │             │              │
       ▼                          │             ▼              ▼
┌──────────────┐                  │   ┌──────────────────────────┐
│ reflect_node │                  │   │      tool_node           │
│ (check output│                  │   │  (MCP, web_search, etc.) │
│  loop/done?) │                  │   └──────────────┬───────────┘
└──────┬───────┘                  │                  │
       │ done? ────────────────── │──────────────────┘
       │ loop?  → back to plan    │
       ▼                          ▼
┌──────────────────────────────────┐
│           respond_node           │
│  (format + stream final answer)  │
└──────────────────────────────────┘
```

---

### New State Definition (`backend/langgraph_state.py`)

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # full conversation history
    session_key: str                           # user_id:session_id
    user_id: str
    session_id: str
    iteration_count: int                       # loop guard
    last_code: str | None                      # last executed code block
    last_output: str | None                    # last execution output
    static_dir: str                            # output file path
    upload_dir: str                            # user uploads path
    mcp_tool_results: list                     # pre-gathered MCP results
```

---

### Node Descriptions (`backend/langgraph_nodes.py`)

| Node | What it does | LLM call? |
|---|---|---|
| `plan_node` | Calls LLM with full state + system prompt. Returns either: a tool call, a code block to execute, or a final response. | ✅ |
| `execute_node` | Receives code from plan_node, runs `interpreter.computer.run("python", code)`, captures stdout/images/errors, updates state. | ❌ |
| `reflect_node` | Examines execution output. If error or unexpected result → loop back to plan. If success → move to respond. Max iterations guard. | ✅ (small LLM call) or rule-based |
| `tool_node` | Standard LangGraph `ToolNode`. Handles MCP tools, web_search, get_station_info, etc. as LangChain tools. | ❌ |
| `hpc_execute_node` | Optional. Routes code to HPC cluster via submit_hpc_job, polls until complete, returns output. | ❌ |
| `respond_node` | Streams final formatted response back to the SSE generator in `routes/chat.py`. | ❌ |

---

### Files to Create / Modify

#### New: `backend/langgraph_state.py`
`AgentState` TypedDict as shown above.

#### New: `backend/langgraph_nodes.py`
All node function implementations. Imports `interpreter.computer` from `backend/interpreter_manager.py`.

#### New: `backend/langgraph_agent.py`
Builds and compiles the `StateGraph`. Wires nodes and edges. Attaches `PostgresSaver` checkpointer using the existing Postgres connection.

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

def build_agent(checkpointer: PostgresSaver) -> CompiledGraph:
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("tools", tool_node)
    graph.add_node("respond", respond_node)
    graph.set_entry_point("plan")
    # conditional edges based on plan_node output
    ...
    return graph.compile(checkpointer=checkpointer)
```

#### Modified: `backend/interpreter_manager.py`
- Keep `get_or_create_interpreter()` but strip out all LLM/chat config
- Expose `get_computer(session_key)` — returns only `interpreter.computer` (the execution sandbox)
- Remove `interpreter.chat()` usage entirely
- Keep `clear_session()`, `cleanup_idle_sessions()` — these still manage sandbox lifecycle

#### Modified: `routes/chat.py`
Replace the `interpreter.chat(stream=True)` call and surrounding logic with:
```python
agent = get_agent()  # compiled LangGraph graph singleton
config = {"configurable": {"thread_id": session_key}}

async def event_stream():
    async for chunk in agent.astream(
        {"messages": messages, "session_key": session_key, ...},
        config=config,
        stream_mode="messages",
    ):
        yield f"data: {json.dumps(chunk)}\n\n"
```

#### Modified: `app.py`
Initialize `PostgresSaver` on startup and pass to `build_agent()`.

#### Modified: `requirements.txt`
Add:
```
langgraph>=0.2.0
langgraph-checkpoint-postgres>=1.0.0
langchain-openai>=0.1.0   # or keep litellm as LLM backend
```

---

### Memory & State: Redis vs. PostgresSaver

| Concern | Current (Redis) | With LangGraph |
|---|---|---|
| Message history | `messages:{session_key}` Redis key | `PostgresSaver` checkpointer, thread = `session_key` |
| Last active time | `last_active:{session_key}` Redis key | Keep in Redis (LangGraph doesn't manage this) |
| Guest expiry tracking | Redis ZSET | Keep in Redis |
| Session cleanup (idle) | `cleanup_idle_sessions()` | Keep — still clears OI sandbox + static files |
| Conversation save/load | Postgres `conversation` table | Unchanged — still uses `routes/conversations.py` |

Redis is **not fully replaced** — it still handles session activity tracking and guest expiry. LangGraph's `PostgresSaver` replaces only the message history store.

---

### New Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LANGGRAPH_MAX_ITERATIONS` | ❌ | `10` | Max plan→execute→reflect loops per request |
| `LANGGRAPH_PLANNER_MODEL` | ❌ | inherits `interpreter.llm.model` | LLM used in `plan_node` and `reflect_node` |
| `LANGGRAPH_REFLECT_MODEL` | ❌ | `gpt-4o-mini` | Smaller/cheaper model for reflect_node (optional cost optimization) |

No new database connection needed — `PostgresSaver` reuses the existing `POSTGRES_*` env vars and the same Postgres container.

---

### What Changes for Users

- **No visible difference** — the chat UI and SSE stream format stay identical
- **Better memory** — LangGraph checkpointer gives more reliable long-context conversations than Redis serialization
- **Better agentic behavior** — explicit plan→reflect→loop cycle replaces OI's opaque internal loop
- **Inspectable state** — every step of the graph is queryable from the `PostgresSaver` checkpoint store (useful for debugging and conversation replay)

---

### Implementation Order

1. Add `langgraph`, `langgraph-checkpoint-postgres` to `requirements.txt`
2. Create `backend/langgraph_state.py`
3. Create `backend/langgraph_nodes.py` — start with `plan_node` + `execute_node` only (simplest graph)
4. Create `backend/langgraph_agent.py` — wire minimal 3-node graph (plan → execute → respond)
5. Modify `backend/interpreter_manager.py` — expose `get_computer()`, keep sandbox lifecycle
6. Modify `routes/chat.py` — swap `interpreter.chat()` for `agent.astream()`
7. Modify `app.py` — initialize `PostgresSaver` on startup
8. Test: verify SSE streaming still works end-to-end
9. Add `reflect_node` and loop logic
10. Add `tool_node` for MCP tools (replaces `mcp_helpers.plan_and_run_mcp_tools`)
11. (Optional) Add `hpc_execute_node` if HPC plan is also implemented

---

### Dependency Between Both Plans

If implementing **both**, do HPC first:
- HPC as a tool has zero risk — it's purely additive
- Once LangGraph is in place, `submit_hpc_job` becomes a proper `ToolNode` in the graph rather than a pre-loaded Python function, which is a cleaner integration
- The `hpc_execute_node` branch in the LangGraph graph is the final target architecture

```
HPC Phase 1:  submit_hpc_job injected as pre-loaded function (works with current OI loop)
LangGraph:    refactor agentic loop
HPC Phase 2:  promote submit_hpc_job to a proper LangGraph ToolNode / hpc_execute_node
```
