# Conversation Runtime

## Overview

EvoAgent's conversation runtime provides persistent multi-turn interactive agent sessions with mode-aware execution, tool calling, and EventBus-based UI decoupling.

## Session Lifecycle

```
evoagent                    → new session or resume
User input                  → turn starts
  model → tool → model ...  → multi-tool loop within turn
Assistant final response    → turn ends
/exit                       → session saved, process exits
```

## Model/Tool Loop

Each user turn executes a model→tool→model loop:

1. Build messages: system prompt + recent history (no orphaned tool messages)
2. Call model via ModelRouter (executor role)
3. If model returns tool_calls: check permission, execute tool, append result
4. Loop back to step 2
5. If model returns text: final response, turn complete

## Message Ordering

Internal messages use `Message` objects with `ToolCall` schema. Provider wire format (`{function: {name, arguments}}`) is handled only in provider adapters.

Turn order: `user → assistant(tool_call) → tool(result) → assistant(tool_call) → tool(result) → assistant(final)`

## Modes

| Mode | Planning | Approval | Mutation |
|------|----------|----------|----------|
| default | adaptive | high-risk only | yes |
| plan | mandatory | mutations require plan approval | only after approval |
| auto | adaptive | none (hard deny retained) | yes |

## DeepSeek Reasoning Content

`reasoning_content` from DeepSeek is stored internally in `Message.reasoning_content` but never displayed in CLI output.

## Session Persistence

Sessions saved to `.evoagent/sessions/<id>/session.json`. Commands:
- `/sessions` — list saved sessions
- `/resume <id>` — restore session
- `/new` — fresh session

## CLI Commands

See `docs/cli.md` for the full command reference.
