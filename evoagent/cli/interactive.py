"""Interactive CLI — Rich-powered terminal interface with banner, streaming, tool view."""

import copy
import sys
from pathlib import Path

from evoagent.config.loader import load_config
from evoagent.config.schema import EvoAgentConfig
from evoagent.conversation.runtime import ConversationRuntime
from evoagent.conversation.schema import AgentMode
from evoagent.conversation.session import ConversationSession
from evoagent.conversation.store import SessionStore
from evoagent.models.factory import MockLLMProvider, ProviderFactory
from evoagent.models.provider_registry import ProviderRegistry
from evoagent.models.registry import ModelRegistry
from evoagent.models.router import ModelRouter
from evoagent.models.schema import ModelConfig
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.tools.builtin import create_builtin_registry

try:
    from rich.console import Console
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

_current_model_selection: str = "default"
_debug_mode: bool = False
_verbose_level: str = "compact"


def _model_display(selection: str, config) -> str:
    """Resolve a model selection to a friendly display name.

    'default'/'mock' resolve to the configured default model's name (so the
    prompt shows e.g. 'deepseek-chat' instead of the literal 'default'); a
    'provider/model' selection shows the model part.
    """
    if selection in ("default", "mock"):
        try:
            return config.models.default.model
        except Exception:
            return selection
    return selection.split("/")[-1] if "/" in selection else selection


def _make_model_config(
    selection: str,
    providers: ProviderRegistry,
    models: ModelRegistry,
    config: EvoAgentConfig,
) -> ModelConfig | None:
    if selection == "default":
        return ModelConfig.model_validate(config.models.default.model_dump())

    resolved = models.resolve(selection) if models else selection
    if not resolved or "/" not in resolved:
        return None

    provider_id, model_id = resolved.split("/", 1)
    provider_def = providers.get(provider_id) if providers else None
    if provider_def is None:
        return None

    return ModelConfig(
        provider=provider_id,
        adapter_type=provider_def.adapter_type,
        model=model_id,
        base_url=provider_def.base_url or "",
        api_key_env=provider_def.api_key_env or "",
        temperature=config.models.default.temperature,
        max_tokens=config.models.default.max_tokens,
        timeout=config.models.default.timeout,
        max_retries=config.models.default.max_retries,
    )


def _build_provider(
    selection: str,
    providers: ProviderRegistry,
    models: ModelRegistry,
    config: EvoAgentConfig,
):
    model_config = _make_model_config(selection, providers, models, config)
    if not model_config:
        return None
    try:
        return ProviderFactory.create(model_config)
    except Exception:
        return None


def _bind_provider_to_router(router: ModelRouter, provider) -> None:
    for role in ("planner", "executor", "critic", "default"):
        router.register(role, provider)


async def run_interactive():
    global _current_model_selection
    workspace = Path.cwd()
    config = load_config()
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()

    provider = _build_provider("default", provider_registry, model_registry, config)
    if provider is None:
        print("\n  ⚠ No configured model provider found. EvoAgent needs a model to function.")
        print("    Set an API key or configure a provider in evoagent.yaml.\n")
        provider = MockLLMProvider(
            fixed_text=
            "No model configured.\n\n"
            "EvoAgent requires a model provider to function.\n\n"
            "To get started:\n"
            "  1. Set DEEPSEEK_API_KEY, OPENAI_API_KEY, or "
            "equivalent environment variable\n"
            "  2. Or configure another provider in evoagent.yaml\n"
            "  3. Restart EvoAgent\n\n"
            "Supported: DeepSeek, OpenAI, Anthropic, Gemini, Mistral, xAI, Ollama\n\n"
            "Type /model to see available providers."
        )
        _current_model_selection = "mock"

    router = ModelRouter(
        providers={
            "planner": provider,
            "executor": provider,
            "critic": provider,
            "default": provider,
        }
    )
    # The interactive runtime gates tool approval via the event bus, so the
    # bash tool may execute ASK commands once the user has approved them.
    tools = create_builtin_registry(workspace, auto_approve=True)
    policy = PermissionPolicy()
    store = SessionStore()

    session = ConversationSession(workspace=str(workspace))

    version = "v1.0.0"

    # Banner
    if HAS_RICH and sys.stdout.isatty():
        console = Console(
            theme=__import__("evoagent.cli.ui.theme", fromlist=["EVO_THEME"]).EVO_THEME
        )
        from evoagent.cli.ui.banner import render_banner
        console.print(
            render_banner(
                version,
                _model_display(_current_model_selection, config),
                session.mode.value,
                str(workspace),
                context_pct=8,
                billing="API" if _current_model_selection != "mock" else "Free",
                width=console.width,
            )
        )
    elif sys.stdout.isatty():
        from evoagent.cli.ui.banner import render_simple_startup
        render_simple_startup(version, _current_model_selection, session.mode.value)
    else:
        console = None
        print(f"EvoAgent {version} | {_current_model_selection} | {session.mode.value}")

    # EventBus for tool activity rendering
    from evoagent.cli.ui import render as _render
    from evoagent.cli.ui.event_bus import EventBus
    from evoagent.cli.ui.events import UIEventType
    event_bus = EventBus()
    _tool_reporter = (
        _render.LiveToolReporter(console) if (HAS_RICH and console) else None
    )
    _thinking = {"status": None}

    def _start_thinking() -> None:
        if not (HAS_RICH and console) or _thinking["status"] is not None:
            return
        try:
            _thinking["status"] = console.status(
                "thinking", spinner="dots", spinner_style="evo.spinner"
            )
            _thinking["status"].start()
        except Exception:
            _thinking["status"] = None

    def _stop_thinking() -> None:
        status = _thinking.get("status")
        if status is None:
            return
        try:
            status.stop()
        except Exception:
            pass
        _thinking["status"] = None

    async def _on_tool(evt):
        name = evt.payload.get("tool_name", "?")
        _stop_thinking()
        if evt.type == UIEventType.TOOL_CALL_STARTED:
            if _tool_reporter is not None:
                _tool_reporter.start(name, evt.payload.get("arguments"))
            else:
                print(f"  * {name}")
        else:
            out_full = evt.payload.get("output", "")
            ok = evt.type != UIEventType.TOOL_CALL_FAILED
            if _tool_reporter is not None:
                _tool_reporter.finish(name, out_full, success=ok)
            else:
                glyph = "+" if ok else "x"
                print(f"  {glyph} {name}")
    async def _on_approval(evt):
        tool = evt.payload.get("tool_name", "?")
        cmd = str(evt.payload.get("arguments", {}))
        if HAS_RICH and console:
            from evoagent.cli.ui.approval_view import prompt_approval
            choice = await prompt_approval(
                f"Approve tool: {tool}",
                cmd[:100],
                description=f"Run '{tool}' in workspace?",
                risk=evt.payload.get("risk", "medium"),
            )
            if choice in ("yes", "remember"):
                session.metadata[f"approved_{evt.payload.get('tool_call_id','')}"] = True
                _render.success(console, "Approved")
            else:
                _render.error(console, "Denied")
            return choice
        else:
            print(f"\nApprove: {tool}? (y/n): ", end="")
            c = sys.stdin.readline().strip().lower()
            if c == "y":
                session.metadata[f"approved_{evt.payload.get('tool_call_id','')}"] = True
                return "yes"
            return "no"
    event_bus.subscribe("approval_requested", _on_approval)
    event_bus.subscribe(UIEventType.TOOL_CALL_STARTED.value, _on_tool)
    event_bus.subscribe(UIEventType.TOOL_CALL_FINISHED.value, _on_tool)
    event_bus.subscribe(UIEventType.TOOL_CALL_FAILED.value, _on_tool)
    runtime = ConversationRuntime(session, router, tools, policy, event_bus=event_bus)

    # Escape resolver for double-Esc exit
    from evoagent.cli.ui.escape import EscapeActionResolver
    escape_resolver = EscapeActionResolver(timeout_ms=800)

    # Try prompt_toolkit, fall back to sys.stdin
    pt_session = None
    HAS_PT = False
    try:
        from evoagent.cli.ui.prompt import create_prompt_session
        pt_session = create_prompt_session(
            get_mode=lambda: session.mode.value,
            get_model=lambda: _model_display(_current_model_selection, config),
            get_status=lambda: (
                f"{len(session.messages)} msgs · {len(session.turns)} turns"
            ),
        )
        HAS_PT = True
    except ImportError:
        pass

    while True:
        try:
            if HAS_PT and pt_session and sys.stdout.isatty():
                user_input = await pt_session.prompt_async()
            elif HAS_RICH and console:
                prompt = Text()
                prompt.append("❯ ", style=f"evo.{session.mode.value}")
                console.print(prompt, end="")
                sys.stdout.flush()
                line = sys.stdin.readline()
                if not line:  # EOF (Ctrl-D)
                    store.save(session)
                    print("\nGoodbye.")
                    break
                user_input = line.strip()
            else:
                print(f"EvoAgent[{session.mode.value}]> ", end="")
                sys.stdout.flush()
                line = sys.stdin.readline()
                if not line:  # EOF
                    store.save(session)
                    print("\nGoodbye.")
                    break
                user_input = line.strip()

        except (EOFError, KeyboardInterrupt):
            store.save(session)
            print("\nSession saved. Goodbye.")
            break

        if not user_input:
            continue

        # Collapse large pastes
        if user_input.count("\n") > 20 or len(user_input) > 4096:
            lines = user_input.count("\n") + 1
            kb = len(user_input) / 1024
            print(f"  Pasted {lines} lines · {kb:.1f} KB (use Ctrl+O to expand)")
            # Model still receives full content via runtime

        if user_input == "/escape":
            action = escape_resolver.resolve(is_executing=False, buffer_empty=True)
            if action.value == "arm_exit":
                if escape_resolver.is_armed():
                    print("\n  Press Esc again to exit")
            elif action.value == "exit":
                store.save(session)
                print(f"\n  Session saved: {session.session_id}\n  Goodbye!")
                break
            elif action.value == "interrupt":
                print("\n  Interrupted.")
            continue

        if user_input == "/exit":
            store.save(session)
            print("Goodbye.")
            break

        if user_input == "/interrupt":
            print("\nInterrupted. Session preserved.")
            continue

        if user_input == "/escape":
            action = escape_resolver.resolve(
                is_executing=False,
                buffer_empty=True,
            )
            if action.value == "arm_exit":
                if escape_resolver.is_armed():
                    print("\n  Press Esc again to exit.")
            elif action.value == "exit":
                store.save(session)
                print(f"\n  Session saved: {session.session_id}")
                print("  Goodbye!")
                break
            elif action.value == "interrupt":
                print("\n  Interrupted. Session preserved.")
            continue

        if user_input == "/toggle_verbose":
            global _verbose_level
            _verbose_level = "full" if _verbose_level == "compact" else "compact"
            print(f"Verbose: {_verbose_level}")
            continue

        # Slash commands
        if user_input.startswith("/"):
            handled = _handle_command(
                user_input,
                session,
                store,
                provider_registry,
                model_registry,
                tools,
                router,
                config,
                console=console if (HAS_RICH and console) else None,
            )
            if handled == "exit":
                store.save(session)
                print("Goodbye.")
                break
            continue

        # Normal message with error recovery
        try:
            t0 = __import__('time').monotonic()
            if HAS_RICH and console:
                # Show a lightweight thinking indicator until the first tool
                # event or visible model output arrives.
                response_parts = []
                _start_thinking()
                try:
                    async for chunk in runtime.handle_user_message_stream(user_input):
                        _stop_thinking()
                        if chunk.startswith("·"):
                            if chunk.strip():
                                _render.reasoning(console, chunk)
                        else:
                            response_parts.append(chunk)
                finally:
                    _stop_thinking()
                response = "".join(response_parts)
                elapsed = __import__('time').monotonic() - t0
                tc = sum(1 for m in session.messages if m.role.value == "tool")
                # Show activity group summary
                tool_names = getattr(runtime, '_tool_names_this_turn', [])
                if len(tool_names) >= 3:
                    uniq = list(dict.fromkeys(tool_names))
                    label = (
                        "Explored"
                        if "list_directory" in uniq or "grep" in uniq
                        else "Executed"
                    )
                    _render.activity_summary(console, label, tool_names)
                from rich.markdown import Markdown
                console.print()
                console.print(Markdown(response, code_theme="monokai"))
                _render.response_footer(console, elapsed, tc)
            else:
                response = await runtime.handle_user_message(user_input)
                elapsed = __import__('time').monotonic() - t0
                tc = sum(1 for m in session.messages if m.role.value == "tool")
                parts = [f"{elapsed:.1f}s"]
                if tc:
                    parts.append(f"{tc} tool calls")
                print(f"\n{response}\n  ({', '.join(parts)})\n")
        except Exception as exc:
            store.save(session)
            from evoagent.cli.ui.error_view import render_error
            err_text = render_error(exc, debug=_debug_mode)
            if HAS_RICH and console:
                console.print(err_text, style="evo.error")
            else:
                print(err_text)
            print()
        store.save(session)


def _handle_command(cmd: str, session: ConversationSession, store: SessionStore,
                    providers=None, models=None, tools=None, router=None,
                    config: EvoAgentConfig | None = None, console=None) -> str:
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command in ("/exit", "/quit"):
        return "exit"

    if command == "/debug":
        global _debug_mode
        if len(parts) > 1:
            _debug_mode = parts[1].lower() == "on"
        else:
            _debug_mode = not _debug_mode
        print(f"Debug: {'ON' if _debug_mode else 'OFF'}")
        return "ok"

    if command == "/model":
        return _handle_model(parts, providers, models, router, config, session,
                             console=console)

    if command == "/mode":
        if len(parts) > 1:
            mode_str = parts[1].lower()
            if mode_str in ("default", "plan", "auto"):
                session.set_mode(AgentMode(mode_str))
                if console:
                    from evoagent.cli.ui import render as R
                    R.mode_card(console, session.mode.value)
                else:
                    print(f"Mode: {session.mode.value}")
            else:
                if console:
                    from evoagent.cli.ui import render as R
                    R.warn(console, f"Unknown mode '{mode_str}' — use default, plan, or auto.")
                else:
                    print(f"Unknown mode: {mode_str}. Use default, plan, or auto.")
        else:
            if console:
                from evoagent.cli.ui import render as R
                R.kv(console, [("current", session.mode.value),
                               ("available", "default · plan · auto")])
            else:
                print(f"Current mode: {session.mode.value}")
                print("Available: default, plan, auto")
        return "ok"

    if command == "/plan":
        sub = parts[1] if len(parts) > 1 else "show"
        if sub == "create":
            desc = " ".join(parts[2:]) if len(parts) > 2 else "Untitled plan"
            from evoagent.planning.schema import ActionType, Plan, PlanStep
            session.current_plan = Plan(
                task=desc,
                steps=[PlanStep(goal=desc, action_type=ActionType.FINISH)],
            )
            print(f"Plan created: {desc}")
        elif sub == "edit":
            instruction = " ".join(parts[2:]) if len(parts) > 2 else ""
            if session.current_plan and instruction:
                from evoagent.planning.schema import ActionType, PlanStep
                session.current_plan.steps.append(
                    PlanStep(goal=instruction, action_type=ActionType.FINISH))
                print("Plan updated.")
            else:
                print("No active plan or no instruction.")
        elif sub == "execute":
            session.metadata["plan_approved"] = True
            print("Plan approved. Executing...")
        elif sub == "cancel":
            session.current_plan = None
            print("Plan cancelled.")
        elif sub == "clear":
            session.current_plan = None
            print("Plan cleared.")
        else:
            if session.current_plan:
                steps = [f"{i+1}. {s.goal}" for i, s in enumerate(session.current_plan.steps)]
                print("Plan:\n" + "\n".join(steps))
            else:
                print("No active plan.")
        return "ok"

    if command == "/sessions":
        sessions = store.list_sessions()
        print("Recent sessions:" if sessions else "No saved sessions.")
        for s in sessions[:10]:
            print(f"  {s}")
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
            session.workspace = loaded.workspace
            session.mode = loaded.mode
            session.messages = loaded.messages
            session.current_plan = loaded.current_plan
            session.turns = loaded.turns
            session.metadata = loaded.metadata
            session.created_at = loaded.created_at
            session.updated_at = loaded.updated_at
            print(f"Resumed session {loaded.session_id}")
        else:
            print("Session not found.")
        return "ok"

    if command == "/new":
        session.__init__(workspace=str(session.workspace))
        print("New session created.")
        return "ok"

    if command == "/fork":
        new_session = ConversationSession(workspace=str(session.workspace))
        new_session.messages = copy.deepcopy(session.messages)
        new_session.mode = session.mode
        new_session.current_plan = copy.deepcopy(session.current_plan)
        new_session.turns = copy.deepcopy(session.turns)
        store.save(new_session)
        session.session_id = new_session.session_id
        print(f"Forked session: {new_session.session_id} (history preserved)")
        return "ok"

    if command == "/reset":
        session.__init__(workspace=str(session.workspace))
        print("Session reset. All state cleared.")
        return "ok"

    if command == "/status":
        if console:
            from evoagent.cli.ui import render as R
            R.section(console, "Session")
            R.kv(console, [
                ("id", session.session_id),
                ("mode", session.mode.value),
                ("messages", str(len(session.messages))),
                ("turns", str(len(session.turns))),
                ("plan", "active" if session.current_plan else "none"),
            ])
            if providers:
                rows = list(providers.status_summary().items())
                if rows:
                    console.print()
                    R.section(console, "Providers")
                    R.kv(console, [(p, s) for p, s in rows])
        else:
            print(f"Session: {session.session_id}")
            print(f"Mode: {session.mode.value}")
            print(f"Messages: {len(session.messages)}")
            print(f"Turns: {len(session.turns)}")
            print(f"Plan: {'active' if session.current_plan else 'none'}")
            if providers:
                for pid, status in providers.status_summary().items():
                    print(f"  {pid}: {status}")
        return "ok"

    if command == "/help":
        groups = [
            ("Session", "/new  /resume  /fork  /history  /clear  /reset  /exit"),
            ("Runtime", "/mode  /model  /plan  /status  /compact"),
            ("Display", "/verbose  /debug  /diff  /cost  /tokens"),
            ("Model", "/model list  ·  /model <provider>/<id>  ·  /model status"),
            ("Tools", "/tools list  ·  /tool show <id>  ·  /permissions"),
            ("Exit", "/exit   Ctrl+D   Esc Esc (idle)"),
        ]
        if console:
            from rich.table import Table
            grid = Table.grid(padding=(0, 3))
            grid.add_column(style="evo.heading", justify="left", min_width=9)
            grid.add_column(style="evo.muted")
            for name, cmds in groups:
                grid.add_row(name, cmds)
            console.print()
            console.print(grid)
            console.print()
        else:
            for name, cmds in groups:
                print(f"{name:9s} {cmds}")
        return "ok"

    if command == "/tools":
        if len(parts) > 1 and parts[1] == "show" and len(parts) > 2:
            name = parts[2]
            try:
                tool = tools.get(name)
                print(f"Name: {tool.name}")
                print(f"Description: {tool.description}")
                print(f"Risk: {tool.risk_level.value}")
                schema = tool.input_schema.model_json_schema()
                props = schema.get("properties", {})
                print("Parameters:")
                for pname, pinfo in props.items():
                    req = pname in schema.get("required", [])
                    print(f"  {pname}: {pinfo.get('type','?')}{' (required)' if req else ''}")
                    if 'description' in pinfo:
                        print(f"    {pinfo['description'][:100]}")
            except Exception:
                print(f"Tool '{name}' not found.")
            return "ok"
        if len(parts) > 1 and parts[1] == "list":
            names = sorted(tools.list_tools()) if hasattr(tools, 'list_tools') else []
            if console:
                from rich.table import Table
                from rich.text import Text as _T
                _risk_style = {"low": "evo.success", "medium": "evo.warning",
                               "high": "evo.error"}
                grid = Table.grid(padding=(0, 3))
                grid.add_column(style="evo.tool.name", justify="left", min_width=16)
                grid.add_column(justify="left")
                for t in names:
                    tool = tools.get(t)
                    risk = tool.risk_level.value if hasattr(tool, 'risk_level') else '?'
                    grid.add_row(t, _T(risk, style=_risk_style.get(risk, "evo.muted")))
                console.print()
                console.print(grid)
                console.print(_T(f"\n  {len(names)} tools registered",
                                 style="evo.faint"))
            else:
                for t in names:
                    tool = tools.get(t)
                    risk = tool.risk_level.value if hasattr(tool, 'risk_level') else '?'
                    print(f"  {t:20s}  risk:{risk}")
            return "ok"
        print("Usage: /tools list | /tools show <name>")
        return "ok"

    if command == "/history":
        try:
            limit = int(parts[1]) if len(parts) > 1 else 10
        except ValueError:
            limit = 10
        limit = max(1, min(limit, 50))
        if console:
            from evoagent.cli.ui import render as R
            R.history_timeline(console, session.turns, limit=limit)
        else:
            if not session.turns:
                print("No conversation history yet.")
            for i, turn in enumerate(session.turns[-limit:], 1):
                print(f"{i}. Q: {turn.user_message}")
                print(f"   A: {turn.assistant_response}")
        return "ok"

    if command == "/permissions":
        print("Permission mode: auto")
        print("Deny: rm -rf, sudo, shutdown, mkfs, curl|bash")
        print("Ask: install, commit")
        return "ok"

    if command == "/tool":
        if len(parts) < 2:
            print("Usage: /tool show <id> | /tool list | /tool last")
            return "ok"
        sub = parts[1]
        if sub == "list":
            tool_msgs = [m for m in session.messages if m.role.value == "tool"]
            for m in tool_msgs[-10:]:
                print(f"  {m.tool_call_id}  [{m.name}]  {m.content[:80]}")
            return "ok"
        if sub == "last":
            tool_msgs = [m for m in session.messages if m.role.value == "tool"]
            if tool_msgs:
                m = tool_msgs[-1]
                print(f"ID: {m.tool_call_id}")
                print(f"Tool: {m.name}")
                print(f"Output: {m.content[:2000]}")
            else:
                print("No tool calls yet.")
            return "ok"
        if sub == "show" and len(parts) > 2:
            tid = parts[2]
            for m in session.messages:
                if m.role.value == "tool" and m.tool_call_id == tid:
                    print(f"ID: {m.tool_call_id}")
                    print(f"Tool: {m.name}")
                    print(f"Output:\n{m.content[:3000]}")
                    return "ok"
            print(f"Tool call '{tid}' not found.")
            return "ok"
        print("Usage: /tool show <id> | /tool list | /tool last")
        return "ok"

    if command == "/diff":
        if session.metadata.get("last_diff"):
            print(session.metadata["last_diff"][:2000])
        else:
            print("No diff available. Make edits first.")
        return "ok"

    if command == "/verbose":
        global _verbose_level
        levels = ["off", "compact", "full"]
        if len(parts) > 1 and parts[1] in levels:
            _verbose_level = parts[1]
        else:
            idx = levels.index(_verbose_level) if _verbose_level in levels else 1
            _verbose_level = levels[(idx + 1) % 3]
        print(f"Verbose: {_verbose_level}")
        return "ok"

    if command == "/cost":
        print("Cost tracking: session-level cost not yet accumulated.")
        print("Run with real provider to see per-call costs via /tokens.")
        return "ok"

    if command == "/tokens":
        total = sum(len(m.content) for m in session.messages)
        print(f"Estimated context: {total:,} chars · {total//4:,} tokens")
        print(f"Messages: {len(session.messages)} · Turns: {len(session.turns)}")
        return "ok"

    if command == "/compact":
        total_chars = sum(len(m.content) for m in session.messages)
        if total_chars > 500000:
            # Keep system + last 20 messages
            kept = session.messages[-20:]
            old_count = len(session.messages)
            session.messages = kept
            print(f"Compacted: {old_count} → {len(kept)} messages ({total_chars:,} chars)")
        else:
            print(
                f"Context: {total_chars:,} chars · {len(session.messages)} "
                "msgs (no compaction needed)"
            )
        return "ok"

    if command == "/undo":
        changed = session.metadata.get("modified_files", [])
        if changed:
            print("Changed files this session:")
            for f in changed:
                print(f"  {f}")
            print("Use 'git checkout' to revert specific files.")
        else:
            print("No file changes to undo.")
        return "ok"

    if command == "/clear":
        session.messages = []
        print("History cleared.")
        return "ok"

    print(f"Unknown: {command}")
    return "ok"


def _handle_model(
    parts: list[str],
    providers,
    models,
    router: ModelRouter | None = None,
    config: EvoAgentConfig | None = None,
    session: ConversationSession | None = None,
    console=None,
) -> str:
    global _current_model_selection
    if len(parts) == 1:
        if console:
            from evoagent.cli.ui import render as R
            R.kv(console, [("current", _current_model_selection)])
            if providers:
                rows = list(providers.status_summary().items())
                if rows:
                    console.print()
                    R.section(console, "Providers")
                    R.kv(console, rows)
            console.print(
                __import__("rich.text", fromlist=["Text"]).Text(
                    "\n  /model list  ·  /model <provider>/<id>  ·  "
                    "/model status  ·  /model default",
                    style="evo.faint",
                )
            )
        else:
            print(f"Current: {_current_model_selection}")
            if providers:
                for pid, status in providers.status_summary().items():
                    print(f"  {pid:20s} {status}")
            print(
                "Usage: /model list | /model <provider>/<id> | /model <alias> | "
                "/model status | /model refresh | /model default"
            )
        return "ok"

    sub = parts[1].lower()
    if sub == "list":
        if models:
            provider_filter = parts[2] if len(parts) > 2 else None
            for m in models.list_all():
                if provider_filter is None or m.provider == provider_filter:
                    print(f"  {m.canonical_id}")
        return "ok"

    if sub == "status":
        print(f"Current: {_current_model_selection}")
        return "ok"

    if sub == "refresh":
        if models and hasattr(models, "refresh"):
            models.refresh()
            print("Model registry refreshed.")
        else:
            print("Model refresh not available in this version.")
        return "ok"

    if sub == "default":
        if router and config:
            provider = _build_provider("default", providers, models, config)
            if provider:
                _bind_provider_to_router(router, provider)
                _current_model_selection = "default"
                _model_ok(console, "default")
                return "ok"
            _model_fail(console, "Failed to create default provider. "
                        "Check API key or provider configuration.")
            return "ok"
        _current_model_selection = "default"
        _model_ok(console, "default")
        return "ok"

    target = parts[1]
    alias = None
    if "/" not in target and models:
        resolved = models.resolve(target)
        if resolved:
            alias = parts[1]
            target = resolved
        else:
            _model_fail(console, f"Unknown model '{parts[1]}'.")
            return "ok"

    if router and config:
        # Validate model capabilities before switching
        # Resolve target to canonical id before lookup (handles aliases and
        # previously unseen canonical IDs added lazily by ModelRegistry.resolve).
        try:
            resolved_id = models.resolve(target) if models else target
        except Exception:
            resolved_id = target
        try:
            model_def = models.get(resolved_id) if (models and resolved_id) else None
        except Exception:
            model_def = None
        if model_def and session and session.current_plan:
            try:
                from evoagent.planning.schema import ActionType
                needs_tool = any(s.action_type == ActionType.TOOL for s in session.current_plan.steps)
            except Exception:
                needs_tool = False
            if needs_tool and not model_def.supports_tools:
                _model_fail(console, "Cannot switch: target model does not support "
                            "tools while the current plan requires them.")
                return "ok"

        provider = _build_provider(target, providers, models, config)
        if provider is None:
            _model_fail(console, "Failed to create provider. "
                        "Check API key, base_url, or provider configuration.")
            return "ok"
        _bind_provider_to_router(router, provider)
    _current_model_selection = target
    _model_ok(console, target, alias=alias)
    return "ok"


def _model_ok(console, label: str, alias: str | None = None) -> None:
    detail = f"alias: {alias}" if alias else ""
    if console:
        from evoagent.cli.ui import render as R
        R.model_card(console, label, detail)
    else:
        print(f"Model: {label}" + (f" (alias: {alias})" if alias else ""))


def _model_fail(console, msg: str) -> None:
    if console:
        from evoagent.cli.ui import render as R
        R.error(console, msg)
    else:
        print(msg)
