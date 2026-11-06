"""Model profiles, per-provider billing, the tool-output cap and the LangGraph agent loop's edges, without any API."""
import json

import pytest
from langchain_core.messages import AIMessage

from p2e import models
from p2e.llm import Agent, Budget, BudgetExceeded, Trace, Usage, cap_tokens, estimate_tokens, sandbox_tools
from p2e.models import Entry, get_profile, usage_entries
from p2e.sandbox import Sandbox
from p2e.schemas import PaperSpec
from p2e.testing import SPEC, FakeClient


def _anthropic_usage(**kw) -> dict:
    """Raw Anthropic usage as langchain-anthropic leaves it in response_metadata["usage"]."""
    base = {"input_tokens": 300, "output_tokens": 400, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            "output_tokens_details": {"thinking_tokens": 350}}
    return {**base, **kw}


def test_profiles_load_and_resolve_by_name_or_model_id():
    assert get_profile("haiku55").model == "claude-haiku-5-5"
    assert get_profile("gpt-6-luna").name == "luna"  # P2E_MODEL=gpt-6-luna from before profiles
    with pytest.raises(KeyError, match="no model profile"):
        get_profile("nope")


def test_profile_rejects_bad_compaction(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("x: {provider: openai, model: m, compaction: {trigger: 60000}}\n")
    with pytest.raises(ValueError, match="Anthropic only"):
        models.load_profiles(f)
    f.write_text("x: {provider: anthropic, model: m, compaction: {trigger: 20000}}\n")
    with pytest.raises(ValueError, match="at least 50000"):
        models.load_profiles(f)


def test_profile_without_prices_counts_tokens_not_dollars(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("mine: {provider: openai, model: m, base_url: 'http://localhost:8000/v1', api_key_env: MINE_KEY}\n")
    p = models.load_profiles(f)["mine"]
    assert not p.prices.known and p.api_key_env == "MINE_KEY"
    assert p.cost(Entry("message", 50_000, 0, 0, 1000)) == 0


def test_anthropic_iterations_bill_the_compaction_step():
    # The measured shape: usage_metadata reports only the message step (286 in), the compaction step (61387 in)
    # is in usage.iterations.
    raw = _anthropic_usage(input_tokens=286, output_tokens=431, iterations=[
        {"type": "compaction", "input_tokens": 61387, "output_tokens": 219,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        {"type": "message", "input_tokens": 286, "output_tokens": 431,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}])
    msg = AIMessage(content="", response_metadata={"usage": raw},
                    usage_metadata={"input_tokens": 286, "output_tokens": 431, "total_tokens": 717})
    entries = usage_entries(msg)
    assert [e.kind for e in entries] == ["compaction", "message"]
    haiku = get_profile("haiku55")
    u = Usage()
    u.add(entries, haiku)
    assert u.compactions == 1 and u.compaction_input_tokens == 61387 and u.requests == 1
    assert u.usd == pytest.approx(((61387 + 286) * 0.10 + (219 + 431) * 0.50) / 1e6)
    assert u.max_prompt_tokens == 61387 and u.tier_steps == 0


def test_anthropic_cache_and_price_tier():
    raw = _anthropic_usage(input_tokens=20_000, cache_read_input_tokens=90_000, cache_creation_input_tokens=1000)
    (e,) = usage_entries(AIMessage(content="", response_metadata={"usage": raw}))
    assert (e.prompt, e.cached, e.written, e.reasoning) == (111_000, 90_000, 1000, 350)
    u = Usage()
    u.add([e], get_profile("haiku55"))
    assert u.tier_steps == 1  # 111k > 100k: billed at 5x
    assert u.usd == pytest.approx(5 * (20_000 * 0.10 + 90_000 * 0.01 + 1000 * 0.125 + 400 * 0.50) / 1e6)


def test_openai_usage_from_usage_metadata():
    msg = AIMessage(content="", usage_metadata={
        "input_tokens": 5000, "output_tokens": 300, "total_tokens": 5300,
        "input_token_details": {"cache_read": 4000, "cache_creation": 500}, "output_token_details": {"reasoning": 200}})
    (e,) = usage_entries(msg)
    assert (e.prompt, e.cached, e.written, e.output, e.reasoning) == (5000, 4000, 500, 300, 200)
    assert get_profile("luna").cost(e) == pytest.approx((500 * 0.10 + 4000 * 0.01 + 500 * 0.125 + 300 * 0.50) / 1e6)


def test_cap_tokens_keeps_head_and_tail():
    text = "\n".join(f"step {i:05d} loss {1 / (i + 1):.6f}" for i in range(5000))
    capped = cap_tokens(text, max_tokens=1000)
    assert estimate_tokens(capped) < 1100
    assert capped.startswith("step 00000") and capped.endswith("step 04999 loss 0.000200")
    assert "cut to keep the request small" in capped
    assert cap_tokens("short", 1000) == "short"


def test_sandbox_hides_every_profile_key(tmp_path, monkeypatch):
    monkeypatch.setattr("p2e.sandbox.secret_env_names", lambda: {"MY_ENDPOINT_TOKEN"})
    monkeypatch.setenv("MY_ENDPOINT_TOKEN", "secret-1")
    monkeypatch.setenv("SOMEVENDOR_API_KEY", "secret-2")
    monkeypatch.setenv("P2E_HARMLESS", "visible")
    sb = Sandbox(tmp_path / "run")
    out = sb.run("env", ".", 30, tag="t").tail(100_000)
    assert "secret-1" not in out and "secret-2" not in out and "P2E_HARMLESS=visible" in out


class AnthropicFake(FakeClient):
    """Fake whose responses carry Anthropic's raw usage, with a compaction step on the second request."""

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        res = super()._generate(messages, stop, run_manager, **kw)
        msg = res.generations[0].message
        steps = [{"type": "message", "input_tokens": 1000, "output_tokens": 200,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}]
        if self.n == 2:
            steps.insert(0, {"type": "compaction", "input_tokens": 70_000, "output_tokens": 500,
                             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})
        msg.response_metadata = {"usage": _anthropic_usage(input_tokens=1000, output_tokens=200, iterations=steps)}
        return res


def _agent(tmp_path, chat, profile="luna", **kw):
    return Agent("t", "TEST", sandbox_tools(Sandbox(tmp_path / "run")), PaperSpec, Trace(tmp_path / "trace.jsonl"),
                 Budget(profile=get_profile(profile)), chat=chat, **kw)


def _events(tmp_path) -> list[dict]:
    return [json.loads(l) for l in (tmp_path / "trace.jsonl").read_text().splitlines()]


def test_agent_bills_compaction_through_the_callback(tmp_path):
    fake = AnthropicFake({"TEST": [[("list_dir", {})], [("list_dir", {})], [("submit", SPEC)]]})
    agent = _agent(tmp_path, fake, profile="haiku55")
    agent.run("go")
    assert agent.usage.requests == 3 and agent.usage.compactions == 1
    expected = (3 * 1000 * 0.10 + 3 * 200 * 0.50 + 70_000 * 0.10 + 500 * 0.50) / 1e6
    assert agent.usage.usd == pytest.approx(expected) and agent.budget.spent_usd == pytest.approx(expected)
    ev = _events(tmp_path)
    assert [e["prompt_tokens"] for e in ev if e["event"] == "compaction"] == [70_000]
    resp = [e for e in ev if e["event"] == "response"]
    assert [len(e["usage"]) for e in resp] == [1, 2, 1]


def test_agent_nudges_when_no_tool_is_called(tmp_path):
    fake = FakeClient({"TEST": [[], [("submit", SPEC)]]})
    out = _agent(tmp_path, fake).run("go")
    assert out.summary == "s" and fake.n == 2


def test_agent_stops_at_max_turns(tmp_path):
    fake = FakeClient({"TEST": [[("list_dir", {})]] * 10})
    with pytest.raises(BudgetExceeded, match="no submission after 3 turns"):
        _agent(tmp_path, fake, max_turns=3).run("go")
    assert fake.n == 3


def test_agent_caps_tool_output(tmp_path, monkeypatch):
    monkeypatch.setattr("p2e.llm.TOOL_OUTPUT_TOKENS", 200)
    fake = FakeClient({"TEST": [[("run_shell", {"command": "seq 1 20000"})], [("submit", SPEC)]]})
    sent = []
    orig = FakeClient._generate

    def spy(self, messages, *a, **kw):
        sent.append(messages)
        return orig(self, messages, *a, **kw)
    monkeypatch.setattr(FakeClient, "_generate", spy)
    _agent(tmp_path, fake).run("go")
    tool_msg = sent[1][-1]
    assert "cut to keep the request small" in tool_msg.content and estimate_tokens(tool_msg.content) < 300
