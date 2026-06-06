# Test Results

- `python3 -m compileall evoagent` : passed
- `python3 -m pytest -q` : passed, 420 tests
- `python3 -m pip install -e '.[dev]'` : passed
- `evoagent --help` : passed
- `python -m evoagent --help` : passed
- Clean clone install, lint, and tests: passed in `/tmp/EvoAgent_clean_verify`

Notes:
- `python -m evoagent` support was added via `evoagent/__main__.py`.

Recent targeted runs:

- `python3 -m pytest -q tests/test_model_capabilities.py` — `3 passed` (validates `supports_streaming`, `supports_json`, `supports_vision` defaults and alias resolution)

Additional notes:
- Full CI-suite run reported earlier: `33 passed` for targeted CLI/session/provider tests during the audit iterations.
