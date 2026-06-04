# EvoAgent

A research-friendly, modular agent framework with self-evolving memory.

## Quick Start

```bash
pip install -e ".[dev]"
export DEEPSEEK_API_KEY="sk-your-key"
evoagent init
evoagent run "Hello world"
```

No API key? Use mock mode:
```bash
evoagent run "Hello" --mock
```

## Key Features

- Model-agnostic (DeepSeek / OpenAI-compatible / Mock)
- 9 built-in tools with Pydantic validation
- 5-layer self-evolving memory
- Hybrid retrieval (keyword + vector)
- Docker sandbox support
- Multi-agent collaboration
- Workflow graph engine
- Code agent with LLM patch generation
- 347 tests, mock-first (zero API calls in tests)

## Documentation

- [Quick Start](quickstart.md)
- [Architecture](architecture.md)
- [Configuration](configuration.md)
- [Tools](tools.md)
- [Sandbox](sandbox.md)
- [Memory](memory_system.md)
- [RAG](rag.md)
- [Code Agent](code_agent.md)
- [Evaluation](evaluation.md)
- [Skills](skills.md)

## Links

- [GitHub](https://github.com/mingbo-yang/EvoAgent)
- [Changelog](../CHANGELOG.md)
- [Contributing](../CONTRIBUTING.md)
