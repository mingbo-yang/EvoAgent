"""Tests for double-Esc exit logic."""

import time

from evoagent.cli.ui.escape import EscapeAction, EscapeActionResolver


def test_single_escape_arms():
    r = EscapeActionResolver(timeout_ms=800)
    action = r.resolve(is_executing=False, buffer_empty=True)
    assert action == EscapeAction.ARM_EXIT
    assert r.state.armed is True


def test_double_escape_exits():
    r = EscapeActionResolver(timeout_ms=800)
    r.resolve(is_executing=False, buffer_empty=True)  # first
    action = r.resolve(is_executing=False, buffer_empty=True)  # second
    assert action == EscapeAction.EXIT


def test_double_escape_timeout_resets():
    r = EscapeActionResolver(timeout_ms=1)  # 1ms timeout
    r.resolve(is_executing=False, buffer_empty=True)
    time.sleep(0.01)  # wait beyond timeout
    action = r.resolve(is_executing=False, buffer_empty=True)
    assert action == EscapeAction.ARM_EXIT  # timed out, re-arms


def test_buffer_not_empty_ignores():
    r = EscapeActionResolver()
    action = r.resolve(is_executing=False, buffer_empty=False)
    assert action == EscapeAction.IGNORE


def test_executing_interrupts():
    r = EscapeActionResolver()
    action = r.resolve(is_executing=True, buffer_empty=True)
    assert action == EscapeAction.INTERRUPT


def test_double_escape_after_interrupt():
    """After interrupt, double-Esc should still work."""
    r = EscapeActionResolver()
    r.resolve(is_executing=True, buffer_empty=True)  # interrupt
    r.resolve(is_executing=False, buffer_empty=True)  # arm
    action = r.resolve(is_executing=False, buffer_empty=True)  # exit
    assert action == EscapeAction.EXIT


def test_is_armed_true():
    r = EscapeActionResolver(timeout_ms=5000)
    r.resolve(is_executing=False, buffer_empty=True)
    assert r.is_armed() is True


def test_is_armed_timeout():
    r = EscapeActionResolver(timeout_ms=1)
    r.resolve(is_executing=False, buffer_empty=True)
    time.sleep(0.01)
    assert r.is_armed() is False


def test_reset_clears_state():
    r = EscapeActionResolver()
    r.resolve(is_executing=False, buffer_empty=True)
    r.reset()
    assert r.state.armed is False
    assert r.state.last_escape_at is None
