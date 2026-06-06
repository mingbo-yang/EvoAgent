# Security Results

- `.env` is ignored by `.gitignore`.
- `.env.example` contains placeholders only.
- No real API key values were found in repository source code or examples during audit.
- Provider registry supports the expected env vars: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `XAI_API_KEY`, and Ollama local mode without a key.
- CLI error sanitization includes api_key pattern detection in `evoagent/cli/ui/error_view.py`.

Remaining concerns:
- No full real API call test was performed in this audit due to lack of configured keys.
- The project still allows user model providers and requires explicit runtime review for production safety.

Recent automated checks:
- Added `tests/test_model_capabilities.py` to assert model capability flags (`supports_streaming`, `supports_json`, `supports_vision`) and alias resolution. These are unit-level checks and do not exercise live provider APIs.
