"""EvoAgent CLI — entry point."""

import typer

app = typer.Typer(
    name="evoagent",
    help="EvoAgent — an open-source, research-friendly agent framework.",
)

# Make 'evoagent' without args start interactive mode
app_default = typer.Typer()
app_default.command(name="__default__", hidden=True)(lambda: None)  # placeholder

@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        import asyncio

        from evoagent.cli.interactive import run_interactive
        asyncio.run(run_interactive())

# Sub-command groups
init_app = typer.Typer(help="Initialize EvoAgent in the current directory.")
config_app = typer.Typer(help="Manage EvoAgent configuration.")
memory_app = typer.Typer(help="Manage agent memories.")
trace_app = typer.Typer(help="View execution traces.")

app.add_typer(init_app, name="init")
app.add_typer(config_app, name="config")
app.add_typer(memory_app, name="memory")
app.add_typer(trace_app, name="trace")

# Import sub-commands to register them
from evoagent.cli import chat as _chat  # noqa: E402, F401
from evoagent.cli import code as _code  # noqa: E402, F401
from evoagent.cli import config as _config  # noqa: E402, F401
from evoagent.cli import eval as _eval  # noqa: E402, F401
from evoagent.cli import init as _init  # noqa: E402, F401
from evoagent.cli import memory as _memory  # noqa: E402, F401
from evoagent.cli import run as _run  # noqa: E402, F401
from evoagent.cli import trace as _trace  # noqa: E402, F401
