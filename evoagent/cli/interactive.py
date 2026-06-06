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
                _current_model_selection,
                session.mode.value,
                str(workspace),
                context_pct=8,
                billing="API Billing" if _current_model_selection != "mock" else "Free",
            )
        )
    elif sys.stdout.isatty():
        from evoagent.cli.ui.banner import render_simple_startup
        render_simple_startup(version, _current_model_selection, session.mode.value)
    else:
        console = None
        print(f"EvoAgent {version} | {_current_model_selection} | {session.mode.value}")

    # EventBus for tool activity rendering
    from evoagent.cli.ui.event_bus import EventBus
    from evoagent.cli.ui.events import UIEventType
    event_bus = EventBus()
    async def _on_tool(evt):
        name = evt.payload.get("tool_name", "?")
        if evt.type == UIEventType.TOOL_CALL_STARTED:
            if HAS_RICH and console:
                console.print(f"◐ {name}", style="evo.tool")
            else:
                print(f"  ◐ {name}")
        else:
            out_full = evt.payload.get("output", "")
            out_lines = out_full.split("\n")
            if len(out_lines) > 3:
                out = (
                    "\n  ".join(out_lines[:3])
                    + f"\n  … ({len(out_lines)} lines total, /tool show for full output)"
                )
            else:
                out = "\n  ".join(out_lines)
            if HAS_RICH and console:
                console.print(f"● {name}\n  {out}", style="evo.tool")
            else:
                print(f"  ● {name}")
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
                console.print("Approved.", style="evo.success")
            else:
                console.print("Denied.", style="evo.error")
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
        bottom = (
            f"{session.mode.value} · {_current_model_selection} · "
            f"msgs:{len(session.messages)} · turns:{len(session.turns)}"
        )
        pt_session = create_prompt_session(
            mode=session.mode.value,
            model_label=_current_model_selection,
            bottom_text=bottom,
        )
        HAS_PT = True
    except ImportError:
        pass

    while True:
        try:
            label = _current_model_selection
            if HAS_PT and pt_session and sys.stdout.isatty():
                user_input = await pt_session.prompt_async()
            elif HAS_RICH and console:
                prompt = Text()
                prompt.append("EvoAgent", style="evo.prompt")
                prompt.append(f"[{session.mode.value}]", style=f"evo.{session.mode.value}")
                prompt.append(f"[{label}]", style="evo.muted")
                prompt.append(" ❯ ", style="evo.prompt")
                console.print(prompt, end="")
                sys.stdout.flush()
                line = sys.stdin.readline()
                if not line:  # EOF (Ctrl-D)
                    store.save(session)
                    print("\nGoodbye.")
                    break
                user_input = line.strip()
            else:
                print(f"EvoAgent[{session.mode.value}][{label}]> ", end="")
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
                # Use streaming path — no status() to keep toolbar visible
                response_parts = []
                async for chunk in runtime.handle_user_message_stream(user_input):
                    if chunk.startswith("·"):
                        if chunk.strip():
                            console.print(chunk, style="evo.reasoning")
                    else:
                        response_parts.append(chunk)
                response = "".join(response_parts)
                elapsed = __import__('time').monotonic() - t0
                tc = sum(1 for m in session.messages if m.role.value == "tool")
                # Show activity group summary
                tool_names = getattr(runtime, '_tool_names_this_turn', [])
                if len(tool_names) >= 3:
                    uniq = list(dict.fromkeys(tool_names))
                    label = (
                        "Explore"
                        if "list_directory" in uniq or "grep" in uniq
                        else "Execute"
                    )
                    console.print(
                        f"● {label}({', '.join(uniq[:3])}… +{len(tool_names)} tools)",
                        style="evo.tool",
                    )
                parts = [f"{elapsed:.1f}s"]
                if tc:
                    parts.append(f"{tc} tool calls")
                from rich.markdown import Markdown
                md = Markdown(response, code_theme="monokai")
                console.print(md)
                console.print(f"({', '.join(parts)})", style="evo.muted")
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
                    config: EvoAgentConfig | None = None) -> str:
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
        return _handle_model(parts, providers, models, router, config, session)

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
        print("Session:  /new /resume /fork /clear /reset /exit")
        print("Runtime:  /mode /model /plan /status /compact")
        print("Display:  /verbose /debug /diff /cost /tokens")
        print("Model:    /model list /model status /model <provider>/<id>")
        print("Tools:    /tools /permissions /tool show <id>")
        print("Exit:     /exit  Ctrl+D  Esc Esc (idle prompt)")
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
            for t in sorted(tools.list_tools()) if hasattr(tools, 'list_tools') else []:
                tool = tools.get(t)
                risk = tool.risk_level.value if hasattr(tool, 'risk_level') else '?'
                print(f"  {t:20s}  risk:{risk}")
            return "ok"
        print("Usage: /tools list | /tools show <name>")
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
) -> str:
    global _current_model_selection
    if len(parts) == 1:
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
                print("Model: default")
                return "ok"
            print("Failed to create default provider. Check API key or provider configuration.")
            return "ok"
        _current_model_selection = "default"
        print("Model: default")
        return "ok"

    target = parts[1]
    if "/" not in target and models:
        resolved = models.resolve(target)
        if resolved:
            target = resolved
            print(f"Model: {target} (alias: {parts[1]})")
        else:
            print(f"Unknown: {parts[1]}")
            return "ok"
    else:
        print(f"Model: {target}")

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
                print(
                    "Cannot switch: target model does not support tools while current plan requires tools."
                )
                return "ok"

        provider = _build_provider(target, providers, models, config)
        if provider is None:
            print("Failed to create provider. Check API key, base_url, or provider configuration.")
            return "ok"
        _bind_provider_to_router(router, provider)
    _current_model_selection = target
    return "ok"
