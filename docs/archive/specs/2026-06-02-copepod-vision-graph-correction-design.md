# Copepod Vision Graph Correction Design

Date: 2026-06-02
Status: Draft

## Goal

Allow the Copepod agent to understand an explicit visual request, inspect a graph image or a user-supplied image, identify a visible problem, and produce a corrected graph or a corrected artifact without replacing the original source artifact.

The feature must stay inside the existing planner/executor flow. It is not a separate image mode.

## Problem Statement

The current Copepod flow already preserves artifacts, hydrates image attachments, and supports planner/executor behavior. It still needs a clearer contract for explicit visual requests:

- when the user sends a graph image or an image of a graph;
- when the user asks to correct, improve, zoom, or reconstruct a graph from an image;
- when the user wants the agent to inspect the image, spot the issue, and produce a corrected artifact.

The desired behavior is semantic, not keyword-based. The assistant must understand the meaning of the request, not match specific words like "zoom" or "corrige".

## User-Facing Contract

When the user makes an explicit visual request, the assistant should:

- stay in the planner/executor pipeline;
- interpret the intention from the full message and available artifacts;
- inspect the image or existing graph artifact as a real input;
- identify what is wrong or missing;
- produce a corrected graph or corrected artifact as a new output;
- keep the source artifact intact for traceability.

The assistant should not:

- replace the source graph in place for now;
- ask repeated clarification questions when the intent is already clear;
- treat the image as decorative context only;
- rely on brittle keyword triggers to decide whether a request is visual;
- hide the correction inside vague prose instead of producing a usable artifact.

## Design Principles

### 1. Semantic intent, not keyword matching

The routing decision must be based on the meaning of the user request plus the current session context. The system should classify the request into a small number of visual intents, such as inspection, zoom, correction, or reconstruction, without hardcoding word lists as the primary signal.

### 2. Planner first, executor second

The planner remains responsible for deciding what should happen. The executor remains responsible for reading the image or artifact and doing the actual correction work. The visual capability is an extension of the current flow, not a bypass.

### 3. Preserve the source artifact

For now, the original image or graph artifact must remain available after correction. The corrected version is emitted as a new artifact or deliverable, not as a destructive replacement.

### 4. Make image inputs actionable

An uploaded image, pasted image, or existing graph image already present in the session should become a first-class working input. The model should be able to inspect it, reason about visible issues, and produce a revised result.

### 5. Ask only when the missing information changes the output

If the user intent is clear enough to execute, the assistant should not stall. If a truly missing detail would change the correction, it may ask one targeted question.

## Proposed Flow

1. The user sends a message that explicitly asks for image-based inspection, correction, zoom, or reconstruction.
2. `routers/chat_routes.py` builds the usual Copepod session context and includes the relevant image or artifact context.
3. The planner reads the message meaning and the session resources, then decides whether the task is inspection, zoom, correction, or reconstruction.
4. The executor opens the image or artifact, diagnoses the visible issue, and generates the corrected graph or artifact.
5. The original artifact remains untouched.
6. The new artifact is returned through the existing deliverable pipeline.

## Intended Behavior for Common Cases

### Uploaded image of a graph

If the user uploads a graph image and asks to "fix it", "improve it", "make it clearer", or an equivalent explicit correction request, the assistant should inspect the image, identify the visible issue, and produce a corrected version.

### Existing graph artifact in the conversation

If the user refers to a graph already generated in the session, the assistant should use the session artifact context to retrieve the prior graph and continue from there instead of asking for the file again.

### Zoom or crop requests

If the user asks for a zoom or crop as part of a correction workflow, the assistant should treat that as a visual editing request inside the same planner/executor flow. The output should be a new artifact that reflects the requested crop or refinement while preserving the original source.

### Ambiguous visual requests

If the request is not clear enough to choose a safe correction target, the assistant may ask one short question. It should not loop through several clarifications.

## Component Boundaries

### `agents/copepod_prompt.py`

Owns the language contract for the Copepod profile:

- visual requests are executed, not deferred indefinitely;
- explicit image-based requests should be treated as actionable tasks;
- the assistant should preserve the source artifact and create a corrected artifact instead of replacing it;
- the assistant should avoid repeated clarification loops when the request is already clear.

### `routers/chat_routes.py`

Owns the runtime routing and context assembly:

- it must surface session artifact context for prior graphs and uploaded images;
- it must keep the planner/executor pipeline intact;
- it must make visual context available in the prompt in a compact, deterministic form;
- it must not require a separate image subsystem just to support this feature.

### `frontend/file-upload.js`

Owns the upload side of the user experience:

- image uploads remain available as normal session inputs;
- pasted images continue to be converted into usable attachments;
- the image metadata carried into the message should be sufficient for the backend to hydrate the image into the model context.

### `tests/test_chat_routes.py`

Owns backend regression coverage for image hydration, session context, and planner/executor routing.

### `tests/test_copepod_prompt_contract.py`

Owns prompt contract coverage for explicit visual execution, source preservation, and non-replacement behavior.

## Non-Goals

This design does not:

- create a separate vision-only mode;
- replace the source graph in place;
- add keyword-only routing as the main mechanism;
- introduce a generic image-editing editor in the frontend;
- change the existing join safety or deliverable protocol work;
- require the user to re-upload artifacts already present in session history.

## Testing Strategy

The feature should be verified in three layers:

1. Prompt contract tests
   - the prompt must say that explicit visual requests are executed within the planner/executor flow;
   - the prompt must preserve the original artifact and produce a new corrected artifact;
   - the prompt must not require keyword-only recognition.

2. Routing tests
   - image attachments are hydrated into the interpreter context;
   - session artifact context exposes the previous graph or image artifact;
   - explicit visual requests produce the expected planner note or execution path.

3. End-to-end regression tests
   - a user-supplied graph image can be inspected and corrected;
   - a graph already produced in the session can be used as the basis for correction;
   - the original artifact remains present after the corrected artifact is emitted.

## Success Criteria

The design is successful when:

- explicit visual requests are interpreted by meaning rather than word matching;
- image inputs become actionable session artifacts;
- the assistant can inspect a graph image, identify a visible issue, and emit a corrected artifact;
- the source artifact remains intact;
- the behavior continues to run through the existing planner/executor pipeline.

