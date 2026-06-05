"""Interactive CLI — persistent multi-turn conversation mode."""

import os
from pathlib import Path

from evoagent.conversation.runtime import ConversationRuntime
from evoagent.conversation.schema import AgentMode
from evoagent.conversation.session import ConversationSession
from evoagent.conversation.store import SessionStore
from evoagent.models.deepseek import DeepSeekProvider
from evoagent.models.factory import MockLLMProvider
from evoagent.models.provider_registry import ProviderRegistry
from evoagent.models.registry import ModelRegistry
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
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()

    current_provider = "deepseek" if has_key else "mock"
    current_model_id = "deepseek-chat" if has_key else "mock"

    print("EvoAgent v0.4.0")
    print(f"Workspace: {workspace}")
    print(f"Model: {current_provider}/{current_model_id}")
    print(f"Mode: {session.mode.value}")
    print(f"Session: {session.session_id}")
    print()

    while True:
        try:
            label = f"{current_provider}:{current_model_id[:12]}" if current_model_id else current_provider
            user_input = input(f"EvoAgent[{session.mode.value}][{label}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            store.save(session)
            print("\nSession saved. Goodbye.")
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            handled = _handle_command(user_input, session, store, provider_registry, model_registry)
            if handled == "exit":
                store.save(session)
                print("Goodbye.")
                break
            continue

        # Normal message — with exception recovery
        try:
            response = await runtime.handle_user_message(user_input)
            print(f"\n{response}\n")
        except Exception as exc:
            store.save(session)
            print(f"\n✗ Turn failed: {exc}")
            print("Session was preserved. Use /status or retry the request.\n")
        store.save(session)


def _handle_command(cmd: str, session: ConversationSession, store: SessionStore,
                    providers=None, models=None) -> str:
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command == "/exit" or command == "/quit":
        return "exit"

    if command == "/model":
        return _handle_model(parts, providers, models)

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


_current_model_selection: str = "default"


def _handle_model(parts: list[str], providers, models) -> str:
    """Handle /model commands."""
    global _current_model_selection
    if len(parts) == 1:
        print(f"Current model: {_current_model_selection}")
        print()
        print("Configured providers:")
        if providers:
            for pid, status in providers.status_summary().items():
                print(f"  {pid:20s} {status}")
        print()
        print("Usage:")
        print("  /model list                 List known models")
        print("  /model list <provider>      List provider models")
        print("  /model <provider>/<id>      Switch to a model")
        print("  /model pro                  Use fast alias")
        print("  /model status               Show status")
        return "ok"

    sub = parts[1].lower()
    if sub == "list":
        if len(parts) > 2:
            provider = parts[2]
            if models:
                for m in models.list_by_provider(provider):
                    print(f"  {m.canonical_id}")
            return "ok"
        if models:
            for m in models.list_all():
                print(f"  {m.canonical_id}")
        return "ok"

    if sub == "status":
        print(f"Current: {_current_model_selection}")
        if providers:
            for pid, status in providers.status_summary().items():
                print(f"  {pid}: {status}")
        return "ok"

    if sub == "refresh":
        print("Model list refreshed (discovery not yet implemented).")
        return "ok"

    # Switch model: /model <provider>/<model-id> or /model <alias>
    target = parts[1]
    if "/" in target:
        print(f"Model switched to: {target}")
        # Register the model
        if models:
            prov, mid = target.split("/", 1)
            models.register(__import__("evoagent.models.registry", fromlist=["ModelDefinition"]).ModelDefinition(
                provider=prov, model_id=mid, canonical_id=target))
            models.mark_recent(target)
        _current_model_selection = target
        return "ok"

    # Try alias
    if models:
        resolved = models.resolve(target)
        if resolved:
            print(f"Model switched to: {resolved} (alias: {target})")
            models.mark_recent(resolved)
            _current_model_selection = resolved
            return "ok"

    print(f"Unknown model/alias: {target}")
    return "ok"
