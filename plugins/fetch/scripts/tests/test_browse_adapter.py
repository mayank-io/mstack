"""Tests for the _browse.py expression builder.

These do NOT drive a real browser. They pin how a Playwright-shaped call is
translated into the single expression `$B js` accepts — which is where the
adapter can go silently wrong.

Regression origin: evaluate() accepted *args and discarded them. A caller
written in Playwright idiom, page.evaluate(fn, {focalId, handle}), saw both as
undefined. In x-post that meant the thread-root walk reported "not a thread"
for a real thread, with no error raised anywhere.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _browse  # noqa: E402


class Spy(_browse.BrowsePage):
    """Captures the expression instead of shelling out to $B."""

    def __init__(self, reply="null"):
        self.sent = None
        self.reply = reply

    def _run(self, *args, **kwargs):
        self.sent = args[1] if len(args) > 1 else None
        return self.reply

    def _parse(self, raw):
        return raw


def ev(expr, *args, reply="null"):
    page = Spy(reply)
    result = asyncio.run(page.evaluate(expr, *args))
    return page.sent, result


# ---------------------------------------------------------------- invocation

def test_function_literal_is_invoked():
    sent, _ = ev("() => 1 + 1")
    assert "(() => 1 + 1)()" in sent


def test_bare_expression_is_not_invoked():
    sent, _ = ev("document.title")
    assert "()" not in sent.replace("JSON.stringify((document.title))", "")


def test_result_is_stringified():
    """$B js prints its result, so an object would arrive as [object Object]."""
    sent, _ = ev("() => ({a: 1})")
    assert sent.startswith("JSON.stringify(")


def test_already_stringified_not_double_wrapped():
    sent, _ = ev("JSON.stringify({a: 1})")
    assert sent.count("JSON.stringify") == 1


# ---------------------------------------------------------------- arguments

def test_arguments_are_passed_not_dropped():
    """THE regression. Args must reach the function."""
    sent, _ = ev("({focalId, handle}) => focalId", {"focalId": "123", "handle": "abc"})
    assert "123" in sent and "abc" in sent
    assert "JSON.parse" in sent


def test_multiple_arguments_applied_in_order():
    sent, _ = ev("(a, b) => a + b", 1, 2)
    payload = json.loads(json.loads(sent[sent.index("JSON.parse(") + len("JSON.parse("):
                                        sent.rindex(")))")].strip().rstrip(")")))
    assert payload == [1, 2]


def test_arguments_are_json_escaped():
    """A quote or backslash in an argument must not break out of the expression."""
    sent, _ = ev("(s) => s", 'he said "hi" \\ bye')
    # The payload survives a full round trip rather than terminating the string.
    assert sent.count("JSON.parse") == 1


def test_arguments_on_non_function_is_an_error():
    """Silently ignoring them is what caused the original bug."""
    with pytest.raises(_browse.BrowseError, match="not a function"):
        ev("document.title", {"a": 1})


# ---------------------------------------------------------------- decoding

def test_json_string_reply_is_decoded():
    _, result = ev("() => ({a: 1})", reply='{"a": 1}')
    assert result == {"a": 1}


def test_non_json_reply_passes_through():
    _, result = ev("() => 'plain'", reply="not json at all")
    assert result == "not json at all"


# ---------------------------------------------------------------- idiom parity

def test_wait_for_timeout_exists():
    """Present so Playwright-idiom callers need no rewrite; absence of this
    method previously raised AttributeError mid-extraction."""
    page = Spy()
    asyncio.run(page.wait_for_timeout(1))


# ---------------------------------------------------------------- async

def test_async_function_is_refused_loudly():
    """`$B js` does not await promises — verified live against gstack: an async
    IIFE with a real 300ms await prints nothing, and JSON.stringify of the
    pending promise gives "{}". There is no expression-level fix, so the
    adapter must fail rather than hand back an empty result that reads as
    success. blog-post's async scroll returned "no images found" this way."""
    with pytest.raises(_browse.BrowseError, match="cannot run async"):
        ev("async () => ({ok: 42})")


def test_expression_containing_await_is_refused():
    with pytest.raises(_browse.BrowseError, match="cannot run async"):
        ev("() => { const x = await go(); return x; }")


def test_refusal_names_the_workaround():
    """An error that does not say what to do instead just moves the confusion."""
    with pytest.raises(_browse.BrowseError, match="wait_for_timeout"):
        ev("async () => 1")


def test_sync_function_still_works():
    sent, _ = ev("() => ({ok: 1})")
    assert sent.startswith("JSON.stringify((")
    assert "async" not in sent


# ---------------------------------------------------------------- lifecycle

class LifecycleSpy(_browse.BrowsePage):
    """Records browse subcommands; simulates an existing-daemon refusal."""

    def __init__(self, daemon_running=False):
        self.calls = []
        self.daemon_running = daemon_running

    def _run(self, *args, **kwargs):
        self.calls.append(args[0])
        if args[0] == "connect" and self.daemon_running:
            raise _browse.BrowseError(
                "`browse connect` failed: [browse] A healthy daemon is already "
                "running (PID 21831, launched mode)."
            )
        return ""


def test_connect_tolerates_an_existing_daemon():
    """The user's normal state is a headed daemon already holding their logins.
    Treating that refusal as fatal would fail every fetch skill at step one."""
    p = LifecycleSpy(daemon_running=True)
    p.connect()
    assert p._owns_daemon is False


def test_connect_starts_one_when_none_running():
    p = LifecycleSpy(daemon_running=False)
    p.connect()
    assert p._owns_daemon is True


def test_close_does_not_kill_a_daemon_it_did_not_start():
    """THE destructive one. Disconnecting a daemon we merely attached to closes
    the user's browser and drops their tabs, cookies and logins mid-session."""
    p = LifecycleSpy(daemon_running=True)
    p.connect()
    p.calls.clear()
    p.close()
    assert "disconnect" not in p.calls


def test_close_disconnects_a_daemon_it_started():
    p = LifecycleSpy(daemon_running=False)
    p.connect()
    p.calls.clear()
    p.close()
    assert "disconnect" in p.calls


def test_connect_reraises_unrelated_failures():
    class Boom(LifecycleSpy):
        def _run(self, *a, **k):
            raise _browse.BrowseError("browse binary not found")
    with pytest.raises(_browse.BrowseError, match="not found"):
        Boom().connect()


# ---------------------------------------------------------------- wait

class WaitSpy(_browse.BrowsePage):
    def __init__(self, err=None):
        self.err = err
        self.calls = []

    def _run(self, *args, **kwargs):
        self.calls.append(args)
        if self.err:
            raise _browse.BrowseError(self.err)
        return ""


def test_wait_accepts_multiple_matches():
    """`$B wait` refuses a non-unique selector; Playwright waits for the first
    match. wait_for_selector("article") is how every X capture starts, and an X
    status page always has several — so this rejected every real post."""
    p = WaitSpy("`browse wait` failed: Selector matched multiple elements. "
                "Be more specific or use @refs from 'snapshot'.")
    asyncio.run(p.wait_for_selector("article"))  # must not raise


def test_wait_still_raises_when_absent():
    p = WaitSpy("`browse wait` failed: Timeout 20000ms exceeded")
    with pytest.raises(_browse.BrowseError, match="never appeared"):
        asyncio.run(p.wait_for_selector("nope"))


def test_wait_passes_through_when_unique():
    p = WaitSpy()
    asyncio.run(p.wait_for_selector("article"))
    assert p.calls[0][0] == "wait"
