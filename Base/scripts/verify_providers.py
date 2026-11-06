"""Check that LangChain's model integrations keep what the agents depend on, before P2E is rebuilt on LangGraph.

For each provider a short tool loop runs through the LangChain chat model while the provider SDK's `create` is
recorded, so every request LangChain sent and every raw response can be compared:

  anthropic (claude-haiku-5-5, langchain-anthropic)
    thinking   every earlier assistant turn is sent back block for block as the API returned it (preserved
               thinking: an edited turn invalidates its thinking blocks, and on newer accounts returns a 400)
    compaction a threshold compaction (beta compact-2026-01-12) returns a `compaction` block, LangChain sends
               it back unchanged, and the next request starts from it
    usage      what LangChain's usage_metadata reports vs the raw usage, including `usage.iterations`
               (the compaction step is billed there and missing from the top-level counts)
  openai (gpt-6-luna, langchain-openai, Responses API)
    reasoning  reasoning and function_call items are sent back as returned
    usage      cached / cache-write / reasoning tokens in usage_metadata vs the raw usage

    .venv/bin/python scripts/verify_providers.py                 # both providers
    .venv/bin/python scripts/verify_providers.py --only openai   # one provider

Keys come from the environment or the project's .env (ANTHROPIC_API_KEY, OPENAI_API_KEY); a provider without a key
is skipped. Costs about $0.02 in total. The report is printed and saved under runs/provider_checks/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from p2e.cli import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import anthropic.resources.beta.messages.messages as a_beta  # noqa: E402
import anthropic.resources.messages.messages as a_msgs  # noqa: E402
import openai.resources.responses.responses as o_resp  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

HAIKU = os.environ.get("P2E_CHECK_ANTHROPIC_MODEL", "claude-haiku-5-5")
LUNA = os.environ.get("P2E_CHECK_OPENAI_MODEL", "gpt-6-luna")
COMPACT_BETA = "compact-2026-01-12"
COMPACT_TRIGGER = 50_000  # the API's minimum; the default (150k) is above Haiku 5.5's 100k price tier
HAIKU_TIER_TOKENS = 100_000

# ------------------------------------------------------------------ recording the SDK traffic

CALLS: list[dict] = []


def _record(cls, provider: str) -> None:
    original = cls.create

    def create(self, *args, **kwargs):
        t0 = time.monotonic()
        result = original(self, *args, **kwargs)
        # LangChain calls `.with_raw_response.create`, which returns a wrapper; parse() is cached, so LangChain's own
        # parse later returns the same object.
        parsed = result.parse() if hasattr(result, "parse") else result
        CALLS.append({"provider": provider, "request": kwargs, "response": parsed,
                      "wall_s": round(time.monotonic() - t0, 2)})
        return result

    cls.create = create


_record(a_msgs.Messages, "anthropic")
_record(a_beta.Messages, "anthropic")
_record(o_resp.Responses, "openai")


def dump(x):
    """Plain JSON-able form of an SDK object, request param or LangChain block, without None fields."""
    if hasattr(x, "model_dump"):
        x = x.model_dump(mode="json", exclude_none=True)
    if isinstance(x, dict):
        return {k: dump(v) for k, v in x.items() if v is not None}
    if isinstance(x, (list, tuple)):
        return [dump(v) for v in x]
    return x


def block_diff(returned: list[dict], sent: list[dict]) -> list[str]:
    """Differences between the blocks the API returned and the blocks sent back for the same turn."""
    out = []
    if len(returned) != len(sent):
        out.append(f"block count {len(returned)} returned vs {len(sent)} sent: "
                   f"{[b.get('type') for b in returned]} vs {[b.get('type') for b in sent]}")
    for i, (r, s) in enumerate(zip(returned, sent)):
        if r == s:
            continue
        kind = r.get("type")
        missing = sorted(set(r) - set(s))
        extra = sorted(set(s) - set(r))
        changed = sorted(k for k in set(r) & set(s) if r[k] != s[k])
        out.append(f"block {i} ({kind}): missing {missing}, added {extra}, changed {changed}")
    return out


# ------------------------------------------------------------------ shared tool loop

VALUES = {"alpha": 17, "beta": 25, "gamma": 41}


@tool
def lookup(key: str) -> str:
    """Return the stored integer for `key` (one of alpha, beta, gamma)."""
    return str(VALUES.get(key, "unknown key"))


TASK = ("Call `lookup` for alpha, then for beta, then for gamma: one call per turn, never two at once, and think "
        "about which key comes next before each call. Then reply with the sum of the three values.")


def tool_loop(llm, max_turns: int = 6) -> list:
    bound = llm.bind_tools([lookup])
    msgs: list = [HumanMessage(TASK)]
    for _ in range(max_turns):
        ai: AIMessage = bound.invoke(msgs)
        msgs.append(ai)
        if not ai.tool_calls:
            break
        for tc in ai.tool_calls:
            msgs.append(ToolMessage(lookup.invoke(tc["args"]), tool_call_id=tc["id"]))
    return msgs


def final_text(ai: AIMessage) -> str:
    if isinstance(ai.content, str):
        return ai.content
    return " ".join(b.get("text", "") for b in ai.content if isinstance(b, dict) and b.get("type") in ("text", "output_text"))


# ------------------------------------------------------------------ anthropic

def haiku_price(usage: dict) -> float:
    """USD for one Messages response on Haiku 5.5: $0.10/$0.50 per MTok up to a 100k-token prompt, 5x above;
    cache reads 0.1x and 5-minute cache writes 1.25x the input rate. Each `usage.iterations` entry is priced on its
    own prompt length (待核实: whether the compaction step is tiered on its own input)."""
    entries = usage.get("iterations") or [usage]
    usd = 0.0
    for u in entries:
        cached, written = u.get("cache_read_input_tokens", 0) or 0, u.get("cache_creation_input_tokens", 0) or 0
        prompt = (u.get("input_tokens", 0) or 0) + cached + written
        k = 5.0 if prompt > HAIKU_TIER_TOKENS else 1.0
        usd += k * ((u.get("input_tokens", 0) or 0) * 0.10 + cached * 0.01 + written * 0.125
                    + (u.get("output_tokens", 0) or 0) * 0.50) / 1e6
    return usd


def check_anthropic_thinking() -> dict:
    from langchain_anthropic import ChatAnthropic
    start = len(CALLS)
    llm = ChatAnthropic(model=HAIKU, max_tokens=8000, effort="medium",
                        thinking={"type": "adaptive", "display": "summarized"})
    msgs = tool_loop(llm)
    calls = CALLS[start:]
    issues, turns = [], []
    for i, call in enumerate(calls):
        returned = dump(call["response"].content)
        thinking = [b for b in returned if b.get("type") == "thinking"]
        turns.append({"turn": i + 1, "blocks": [b.get("type") for b in returned],
                      "thinking_blocks": len(thinking),
                      "thinking_with_signature": sum(1 for b in thinking if b.get("signature")),
                      "thinking_text_chars": sum(len(b.get("thinking", "")) for b in thinking)})
        # The same assistant turn as LangChain sent it in every later request.
        for later in calls[i + 1:]:
            sent_turns = [m for m in later["request"]["messages"] if m["role"] == "assistant"]
            if len(sent_turns) <= i:
                continue
            sent = dump(sent_turns[i]["content"])
            sent = sent if isinstance(sent, list) else [{"type": "text", "text": sent}]
            for d in block_diff(returned, sent):
                issues.append(f"turn {i + 1} as resent in request {calls.index(later) + 1}: {d}")
    usage = [dump(c["response"].usage) for c in calls]
    lc_usage = [m.usage_metadata for m in msgs if isinstance(m, AIMessage)]
    return {
        "model": HAIKU,
        "requests": len(calls),
        "answer": final_text(msgs[-1]),
        "answer_correct": str(sum(VALUES.values())) in final_text(msgs[-1]),
        "turns": turns,
        "thinking_returned": any(t["thinking_blocks"] for t in turns),
        "history_resent_unchanged": not issues,
        "history_issues": sorted(set(issues)),
        "usage_raw": usage,
        "usage_langchain": lc_usage,
        "usd": round(sum(haiku_price(u) for u in usage), 5),
    }


def _filler(part: int, tokens: int) -> str:
    """Synthetic training log of roughly `tokens` Haiku 5.5 tokens. Number-heavy log lines are dense: a first run
    measured about 1.7 characters per token, not the usual 4."""
    lines, n = [], 0
    while n < tokens * 1.7:
        k = len(lines)
        line = (f"[part {part}] epoch {k // 50:03d} step {k:05d} loss {1.0 / (1 + k * 0.01):.6f} "
                f"lr {0.001 * 0.999 ** k:.8f} grad_norm {0.5 + (k * 37 % 100) / 200:.4f} val_acc {0.6 + (k % 97) / 400:.4f}")
        lines.append(line)
        n += len(line) + 1
    return "\n".join(lines)


def check_anthropic_compaction() -> dict:
    from langchain_anthropic import ChatAnthropic
    start = len(CALLS)
    edit = {"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": COMPACT_TRIGGER}}
    llm = ChatAnthropic(model=HAIKU, max_tokens=8000, effort="low", betas=[COMPACT_BETA],
                        context_management={"edits": [edit]})
    msgs: list = [HumanMessage(f"Here is the first half of a training log. Reply only with OK.\n\n{_filler(1, 30_000)}")]
    msgs.append(llm.invoke(msgs))
    msgs.append(HumanMessage(f"Second half of the same log:\n\n{_filler(2, 30_000)}\n\n"
                             "What was the val_acc on the last line of part 2? Answer in one line."))
    compacted: AIMessage = llm.invoke(msgs)
    msgs.append(compacted)
    msgs.append(HumanMessage("Which two parts did the log have? One line."))
    follow = llm.invoke(msgs)
    calls = CALLS[start:]

    raw = [dump(c["response"]) for c in calls]
    blocks = [[b.get("type") for b in r.get("content", [])] for r in raw]
    returned = next((b for r in raw for b in r.get("content", []) if b.get("type") == "compaction"), None)
    # Each compaction block as returned vs as LangChain sent the same assistant turn back in the last request.
    pairs = []
    if len(calls) == 3:
        sent_turns = [m for m in calls[2]["request"]["messages"] if m["role"] == "assistant"]
        for i, r in enumerate(raw[:2]):
            got = next((b for b in r.get("content", []) if b.get("type") == "compaction"), None)
            back = None
            if got is not None and i < len(sent_turns) and isinstance(sent_turns[i]["content"], list):
                back = next((dump(b) for b in sent_turns[i]["content"]
                             if isinstance(b, dict) and b.get("type") == "compaction"), None)
            if got is not None:
                pairs.append((i + 1, got, back))
    usage = [dump(c["response"].usage) for c in calls]
    return {
        "model": HAIKU,
        "trigger": COMPACT_TRIGGER,
        "requests": len(calls),
        "blocks_per_response": blocks,
        "compaction_block_returned": returned is not None,
        "compaction_block_in_langchain_message": any(isinstance(b, dict) and b.get("type") == "compaction"
                                                     for b in (compacted.content if isinstance(compacted.content, list) else [])),
        "compactions_per_request": [sum(1 for i in (u.get("iterations") or []) if i.get("type") == "compaction")
                                    for u in usage],
        "compaction_blocks_resent_unchanged": bool(pairs) and all(g == b for _, g, b in pairs),
        "compaction_block_resent_diff": [f"response {n}: {d}" for n, g, b in pairs if g != b
                                         for d in (block_diff([g], [b]) if b else ["not sent back"])],
        "iterations_in_raw_usage": [u.get("iterations") for u in usage],
        "iterations_in_usage_metadata": ["iterations" in json.dumps(m.usage_metadata or {}, default=str)
                                         for m in (msgs[1], compacted, follow)],
        "iterations_in_response_metadata_keys": [[k for k, v in (m.response_metadata or {}).items()
                                                  if "iterations" in json.dumps(v, default=str)]
                                                 for m in (msgs[1], compacted, follow)],
        "usage_raw": usage,
        "usage_langchain": [m.usage_metadata for m in (msgs[1], compacted, follow)],
        "follow_up_input_tokens": usage[-1].get("input_tokens") if usage else None,
        "largest_prompt_tokens": max((i.get("input_tokens", 0) or 0) + (i.get("cache_read_input_tokens", 0) or 0)
                                     for u in usage for i in (u.get("iterations") or [u])) if usage else None,
        "answers": [final_text(compacted), final_text(follow)],
        "usd": round(sum(haiku_price(u) for u in usage), 5),
    }


# ------------------------------------------------------------------ openai

def luna_price(usage: dict) -> float:
    from p2e.models import Entry, get_profile
    d = usage.get("input_tokens_details", {})
    e = Entry(kind="message", prompt=usage.get("input_tokens", 0), cached=d.get("cached_tokens", 0) or 0,
              written=d.get("cache_write_tokens", 0) or 0, output=usage.get("output_tokens", 0))
    return get_profile(LUNA).cost(e)


def check_openai() -> dict:
    from langchain_openai import ChatOpenAI
    start = len(CALLS)
    llm = ChatOpenAI(model=LUNA, use_responses_api=True, output_version="responses/v1",
                     reasoning={"effort": "medium"}, max_tokens=8000,
                     base_url=os.environ.get("P2E_BASE_URL", "https://api.openai.com/v1"))
    msgs = tool_loop(llm)
    calls = CALLS[start:]
    issues, turns = [], []
    for i, call in enumerate(calls):
        returned = dump(call["response"].output)
        turns.append({"turn": i + 1, "items": [o.get("type") for o in returned]})
        for later in calls[i + 1:]:
            sent_items = dump(later["request"].get("input", []))
            for o in returned:
                if o.get("type") not in ("reasoning", "function_call"):
                    continue
                match = next((s for s in sent_items if isinstance(s, dict) and s.get("id") == o.get("id")), None)
                if match is None:
                    issues.append(f"{o['type']} item {o.get('id')} of response {i + 1} missing from request "
                                  f"{calls.index(later) + 1}")
                elif match != o:
                    issues += [f"{o['type']} item of response {i + 1} in request {calls.index(later) + 1}: {d}"
                               for d in block_diff([o], [match])]
    usage = [dump(c["response"].usage) for c in calls]
    first_req = calls[0]["request"] if calls else {}
    return {
        "model": LUNA,
        "requests": len(calls),
        "answer": final_text(msgs[-1]),
        "answer_correct": str(sum(VALUES.values())) in final_text(msgs[-1]),
        "turns": turns,
        "request_options": {k: first_req.get(k) for k in ("store", "include", "reasoning", "previous_response_id")},
        "reasoning_items_returned": any("reasoning" in t["items"] for t in turns),
        "items_resent_unchanged": not issues,
        "item_issues": sorted(set(issues)),
        "usage_raw": usage,
        "usage_langchain": [m.usage_metadata for m in msgs if isinstance(m, AIMessage)],
        "usd": round(sum(luna_price(u) for u in usage), 5),
    }


# ------------------------------------------------------------------ main

def run(name: str, fn) -> dict:
    try:
        return {"ok": True, **fn()}
    except Exception as e:  # report and go on with the next check
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:2000]}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=["anthropic", "openai"])
    args = ap.parse_args()
    report: dict = {"date": time.strftime("%Y-%m-%d %H:%M:%S")}
    if args.only in (None, "anthropic"):
        if os.environ.get("ANTHROPIC_API_KEY"):
            report["anthropic_thinking"] = run("anthropic_thinking", check_anthropic_thinking)
            report["anthropic_compaction"] = run("anthropic_compaction", check_anthropic_compaction)
        else:
            report["anthropic"] = {"skipped": "ANTHROPIC_API_KEY is not set (add it to .env)"}
    if args.only in (None, "openai"):
        if os.environ.get("OPENAI_API_KEY"):
            report["openai"] = run("openai", check_openai)
        else:
            report["openai"] = {"skipped": "OPENAI_API_KEY is not set (add it to .env)"}
    out = ROOT / "runs" / "provider_checks" / f"{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))
    print(f"\nsaved {out.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
