"""Test that all EvoAgent modules can be imported."""


def test_evoagent_import():
    """evoagent top-level package should import."""
    import evoagent

    assert evoagent.__version__ == "1.0.0"


def test_core_import():
    """evoagent.core should import."""
    from evoagent import core

    assert core is not None


def test_models_import():
    """evoagent.models should import."""
    from evoagent import models

    assert models is not None


def test_tools_import():
    """evoagent.tools should import."""
    from evoagent import tools

    assert tools is not None


def test_sandbox_import():
    """evoagent.sandbox should import."""
    from evoagent import sandbox

    assert sandbox is not None


def test_memory_import():
    """evoagent.memory should import."""
    from evoagent import memory

    assert memory is not None


def test_planning_import():
    """evoagent.planning should import."""
    from evoagent import planning

    assert planning is not None


def test_workflow_import():
    """evoagent.workflow should import."""
    from evoagent import workflow

    assert workflow is not None


def test_multi_agent_import():
    """evoagent.multi_agent should import."""
    from evoagent import multi_agent

    assert multi_agent is not None


def test_rag_import():
    """evoagent.rag should import."""
    from evoagent import rag

    assert rag is not None


def test_skills_import():
    """evoagent.skills should import."""
    from evoagent import skills

    assert skills is not None


def test_logging_import():
    """evoagent.logging should import."""
    from evoagent import logging

    assert logging is not None


def test_eval_import():
    """evoagent.eval should import."""
    from evoagent import eval

    assert eval is not None


def test_config_import():
    """evoagent.config should import."""
    from evoagent import config

    assert config is not None


def test_cli_import():
    """evoagent.cli should import."""
    from evoagent import cli

    assert cli is not None


def test_config_schema_import():
    """Config schema classes should be importable."""
    from evoagent.config.schema import EvoAgentConfig, ModelsConfig

    assert EvoAgentConfig is not None
    assert ModelsConfig is not None


def test_config_loader_import():
    """Config loader should be importable."""
    from evoagent.config.loader import load_config

    assert callable(load_config)
