# EvoAgent Release Readiness Update — v0.3.0

## Current Version
v0.3.0 (pyproject.toml, README, CHANGELOG consistent)

## Test Results (actual, verified)
```
376 passed in ~20s
compileall: ✅
ruff check: ✅ All checks passed
pip install -e ".[dev]": ✅
```

## Fixed Issues (v0.3.0 release readiness pass)

| # | Issue | Resolution |
|---|-------|-----------|
| P1 | Sanity check | All files valid Python/Toml/Markdown — no one-liner compression |
| P2 | Version consistency | pyproject.toml 0.1.0→0.3.0; all placeholder URLs → mingbo-yang/EvoAgent; benchmarks marked illustrative |
| P3 | DockerSandbox image duplicated | Fixed: image in cmd once, options before image; added tests |
| P4 | Memory not injected | Agent.run()→_memory_context→AgentLoop(context=)→Planner.plan(context=); added test |
| P5 | CodeAgent LLM patch | PatchPlan/FileEdit schemas; tests for old_text missing, path outside workspace, max_iterations, rule-based fallback |
| P6 | Planner fallback unsafe | Replaced bash echo with list_directory + ask_user safe steps; added 5 tests |
| P7 | Benchmark claims | All numbers marked "illustrative", not measured results |

## Files Modified
- pyproject.toml (version 0.1.0→0.3.0)
- README.md / README_zh.md (URLs, benchmark wording)
- docs/release_readiness_v0.3.0.md (illustrative labels)
- docs/index.md (URL)
- evoagent/sandbox/docker.py (image once, correct order)
- evoagent/core/agent.py (memory injection)
- evoagent/planning/loop.py (context passthrough)
- evoagent/planning/planner.py (safe fallback, no bash)

## Files Added
- tests/test_code_agent_llm_patch.py (5 tests)
- tests/test_planner_fallback.py (5 tests)
- docs/release_readiness_update.md (this file)

## Remaining Known Limitations

### Not Yet Implemented
- Real embedding backends (OpenAI embeddings, sentence-transformers, bge) — currently mock hash-based only
- FAISS / Qdrant vector store integration — currently SimpleVectorIndex only
- SWE-bench integration — no benchmark scores available
- Streaming LLM response in agent loop
- LiteLLM provider

### Partially Implemented
- DockerSandbox works but requires Docker installed; CI skips docker tests
- CodeAgent LLM patch uses MockLLM in tests; real LLM behavior not benchmarked
- Hybrid retrieval pipeline exists but embedding model is mock

### Not Production Ready
- No security audit
- No load testing
- No multi-user isolation
- Error handling quality varies across modules
- Documentation auto-generation (Sphinx/MkDocs API docs) not done

## Safety Status
- PermissionPolicy with deny>ask>allow enforced everywhere
- Test command checker requires sandbox (no direct subprocess)
- Workspace boundary enforced via path resolution
- API keys from environment only (no keys in repo)
- DockerSandbox supports SELinux with :Z mount flag

## Classification

✅ **Research MVP**: Yes. Framework is structurally complete, all 376 tests pass, all major modules implemented, mock-first testing, safe defaults.

❌ **Production-ready**: No. Missing real embedding backends, no SWE-bench results, not hardened for multi-tenant or adversarial use.

✅ **L4 Research Framework**: Yes. Modular design, trace-driven execution, 5-layer memory, hybrid retrieval, multi-agent protocols, workflow graph — suitable for agent research and prototyping.
