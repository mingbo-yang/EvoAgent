from evoagent.models.registry import ModelDefinition, ModelRegistry


def test_register_and_retrieve_capabilities():
    reg = ModelRegistry()
    md = ModelDefinition(provider="deepseek", model_id="deepseek-chat")
    md.supports_streaming = True
    md.supports_json = True
    md.supports_vision = False
    reg.register(md)

    got = reg.get(md.canonical_id)
    assert got is not None
    assert got.supports_streaming is True
    assert got.supports_json is True
    assert got.supports_vision is False


def test_resolve_creates_default_model_with_capabilities():
    reg = ModelRegistry()
    name = "acme/unknown-model"
    resolved = reg.resolve(name)
    assert resolved == name
    md = reg.get(name)
    assert md is not None
    # defaults from ModelDefinition
    assert md.supports_streaming is True
    assert md.supports_json is True
    assert md.supports_vision is False


def test_alias_resolution_for_pro():
    reg = ModelRegistry()
    # by default 'pro' alias exists in constructor
    resolved = reg.resolve("pro")
    assert resolved == "deepseek/deepseek-chat"
