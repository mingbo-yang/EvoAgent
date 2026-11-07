# Contributing to EvoAgent
Wenqiang Wang contributed the majority of the code for this project.
## Development Setup

```bash
git clone <repo-url>
cd agent
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest                  # All tests (mock-first, no API key needed)
pytest tests/test_tools.py  # Specific module
ruff check .            # Lint
python -m compileall evoagent  # Compile check
```

## Code Style

- Type annotations required for all public APIs
- Docstrings for all classes and public methods
- ruff configured in pyproject.toml

## Adding a New Tool

1. Create a Pydantic input schema
2. Extend `BaseTool` with `name`, `description`, `input_schema`, `risk_level`
3. Implement `async run() -> ToolResult`
4. Register in `create_builtin_registry()`
5. Add tests in `tests/test_tools.py`

## Adding a New Model Provider

1. Extend `BaseLLMProvider`
2. Implement `chat()`, `structured_chat()`, `stream_chat()`
3. Add to `ProviderFactory`
4. Add tests using `MockLLMProvider` pattern

## Commit Style

- Use present tense: "Add X" not "Added X"
- Reference issue numbers when applicable
- Keep commits focused — one logical change per commit
