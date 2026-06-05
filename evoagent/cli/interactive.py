"""Interactive CLI — persistent multi-turn conversation mode."""

import os
from pathlib import Path

from evoagent.conversation.runtime import ConversationRuntime
from evoagent.conversation.schema import AgentMode
from evoagent.conversation.session import ConversationSession
from evoagent.conversation.store import SessionStore
from evoagent.models.deepseek import DeepSeekProvider
from evoagent.models.factory import MockLLMProvider
from evoagent.models.router import ModelRouter
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.tools.builtin import create_builtin_registry


async def run_interactive():
    workspace = Path.cwd()

    # Check for API key
    has_key = bool(os.getenv("DEEPSEEK_API_KEY"))
    if has_key:
        provider = DeepSeekProvider()
    else:
        print("No DEEPSEEK_API_KEY found. Using mock mode.")
        provider = MockLLMProvider(fixed_text='{"risk_level":"low","steps":[{"goal":"Execute","action_type":"finish"}]}')

    router = ModelRouter(providers={"planner": provider, "executor": provider, "critic": provider, "default": provider})
    tools = create_builtin_registry(workspace)
    policy = PermissionPolicy()
    store = SessionStore()

    # Create or resume session
    session = ConversationSession(workspace=str(workspace))
    runtime = ConversationRuntime(session, router, tools, policy)

    print("EvoAgent v0.4.0")
    print(f"Workspace: {workspace}")
    print(f"Model: {'deepseek' if has_key else 'mock'}")
    print(f"Mode: {session.mode.value}")
    print(f"Session: {session.session_id}")
    print()

    while True:
        try:
            user_input = input(f"EvoAgent[{session.mode.value}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            store.save(session)
            print("\nSession saved. Goodbye.")
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            handled = _handle_command(user_input, session, store)
            if handled == "exit":
                store.save(session)
                print("Goodbye.")
                break
            continue

        # Normal message
        response = await runtime.handle_user_message(user_input)
        print(f"\n{response}\n")
        store.save(session)


def _handle_command(cmd: str, session: ConversationSession, store: SessionStore) -> str:
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command == "/exit" or command == "/quit":
        return "exit"

    if command == "/mode":
        if len(parts) > 1:
            mode_str = parts[1].lower()
            if mode_str in ("default", "plan", "auto"):
                session.set_mode(AgentMode(mode_str))
                print(f"Mode: {session.mode.value}")
            else:
                print(f"Unknown mode: {mode_str}. Use default, plan, or auto.")
        else:
            print(f"Current mode: {session.mode.value}")
            print("Available: default, plan, auto")
        return "ok"

    if command == "/plan":
        if session.current_plan:
            steps = [f"{i+1}. {s.goal}" for i, s in enumerate(session.current_plan.steps)]
            print("Current Plan:\n" + "\n".join(steps))
        else:
            print("No active plan.")
        return "ok"

    if command == "/sessions":
        sessions = store.list_sessions()
        if sessions:
            print("Recent sessions:")
            for s in sessions[:10]:
                print(f"  {s}")
        else:
            print("No saved sessions.")
        return "ok"

    if command == "/resume":
        if len(parts) > 1 and parts[1] == "latest":
            loaded = store.latest()
        elif len(parts) > 1:
            loaded = store.load(parts[1])
        else:
            print("Usage: /resume <id> or /resume latest")
            return "ok"
        if loaded:
            session.session_id = loaded.session_id
            session.messages = loaded.messages
            session.mode = loaded.mode
            session.turns = loaded.turns
            print(f"Resumed session {loaded.session_id}")
        else:
            print("Session not found.")
        return "ok"

    if command == "/new":
        session.session_id = ""
        session.messages = []
        session.current_plan = None
        session.mode = AgentMode.DEFAULT
        print("New session created.")
        return "ok"

    if command == "/status":
        print(f"Session: {session.session_id}")
        print(f"Mode: {session.mode.value}")
        print(f"Messages: {len(session.messages)}")
        print(f"Turns: {len(session.turns)}")
        print(f"Plan: {'active' if session.current_plan else 'none'}")
        return "ok"

    if command == "/help":
        print("Commands: /mode /plan /sessions /resume /new /status /exit /help")
        return "ok"

    if command == "/clear":
        session.messages = []
        print("History cleared.")
        return "ok"

    print(f"Unknown command: {command}")
    return "ok"
