"""Model profiles from models.yaml: which provider and model an agent talks to, and what each request costs.

A profile names a provider (anthropic, or openai for any OpenAI-compatible endpoint), the model id, the environment
variable holding the key, an optional base URL, a price table with long-prompt tiers, and (Anthropic only) server-side
compaction and prompt caching. `chat_model()` builds the LangChain chat model; `usage_entries()` turns one response
into billable entries, including the compaction step Anthropic reports only in `usage.iterations`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MODELS_FILE = Path(os.environ.get("P2E_MODELS_FILE", Path(__file__).resolve().parent.parent / "models.yaml"))
DEFAULT_PROFILE = "haiku55"
COMPACT_BETA = "compact-2026-01-12"
MAX_OUTPUT_TOKENS = 16000


@dataclass(frozen=True)
class Tier:
    above: int  # prompt tokens (input incl. cached) above which the multipliers apply
    x_in: float
    x_out: float


@dataclass(frozen=True)
class Prices:
    """USD per million tokens."""
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    tiers: tuple[Tier, ...] = ()
    known: bool = True  # False when the profile gives no prices: tokens are counted, dollars are not

    def tier(self, prompt_tokens: int) -> Tier | None:
        hit = [t for t in self.tiers if prompt_tokens > t.above]
        return max(hit, key=lambda t: t.above) if hit else None

    def first_tier_tokens(self) -> int | None:
        return min((t.above for t in self.tiers), default=None)


@dataclass(frozen=True)
class Entry:
    """One billable model step: a normal response, or the compaction step inside one."""
    kind: str  # message | compaction
    prompt: int  # all input tokens of the step, cached ones included
    cached: int
    written: int
    output: int
    reasoning: int = 0


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider: str
    model: str
    api_key_env: str
    prices: Prices
    base_url: str | None = None
    compaction_trigger: int | None = None
    prompt_cache: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.provider}:{self.model})"

    def cost(self, e: Entry) -> float:
        p = self.prices
        t = p.tier(e.prompt)
        k_in, k_out = (t.x_in, t.x_out) if t else (1.0, 1.0)
        fresh = max(e.prompt - e.cached - e.written, 0)
        return (k_in * (fresh * p.input + e.cached * p.cache_read + e.written * p.cache_write)
                + k_out * e.output * p.output) / 1e6

    def chat_model(self, effort: str, max_tokens: int = MAX_OUTPUT_TOKENS):
        """The LangChain chat model for this profile; reads the key from `api_key_env`."""
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"model profile {self.name!r} needs {self.api_key_env} (put it in .env or export it)")
        if self.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            kw: dict = {}
            if self.compaction_trigger:
                kw["betas"] = [COMPACT_BETA]
                kw["context_management"] = {"edits": [{"type": "compact_20260112", "trigger": {
                    "type": "input_tokens", "value": self.compaction_trigger}}]}
            if self.prompt_cache:  # top-level automatic caching: the last cacheable block of each request
                kw["model_kwargs"] = {"cache_control": {"type": "ephemeral"}}
            # Haiku 5.5 / Opus 5.5 reject non-default sampling parameters, so none are set. Thinking text comes back
            # summarized for the trace; it is billed the same either way.
            return ChatAnthropic(model=self.model, api_key=key, base_url=self.base_url, max_tokens=max_tokens,
                                 effort=effort, thinking={"type": "adaptive", "display": "summarized"},
                                 max_retries=4, **kw)
        if self.provider == "openai":
            from langchain_openai import ChatOpenAI
            # Responses API: on GPT-6, Chat Completions allows function calling only with reasoning effort "none".
            return ChatOpenAI(model=self.model, api_key=key, base_url=self.base_url or "https://api.openai.com/v1",
                              use_responses_api=True, output_version="responses/v1",
                              reasoning={"effort": effort}, max_tokens=max_tokens, max_retries=4)
        raise ValueError(f"model profile {self.name!r}: unknown provider {self.provider!r}")

    def invoke_kwargs(self, agent_name: str) -> dict:
        """Per-request options: OpenAI routes requests with the same key to the same cache."""
        return {"prompt_cache_key": f"p2e-{agent_name}"} if self.provider == "openai" else {}


def _profile(name: str, d: dict) -> ModelProfile:
    p = d.get("prices")
    prices = Prices(known=False) if not p else Prices(
        input=float(p.get("in", 0)), output=float(p.get("out", 0)), cache_read=float(p.get("cache_read", 0)),
        cache_write=float(p.get("cache_write", 0)),
        tiers=tuple(Tier(int(t["above"]), float(t.get("x_in", 1)), float(t.get("x_out", 1))) for t in p.get("tiers", [])))
    trigger = (d.get("compaction") or {}).get("trigger")
    if trigger is not None and d["provider"] != "anthropic":
        raise ValueError(f"model profile {name!r}: server-side compaction is Anthropic only")
    if trigger is not None and int(trigger) < 50_000:
        raise ValueError(f"model profile {name!r}: compaction trigger must be at least 50000 tokens")
    known = {"provider", "model", "api_key_env", "base_url", "prices", "compaction", "prompt_cache"}
    return ModelProfile(name=name, provider=d["provider"], model=d["model"],
                        api_key_env=d.get("api_key_env") or ("ANTHROPIC_API_KEY" if d["provider"] == "anthropic"
                                                             else "OPENAI_API_KEY"),
                        prices=prices, base_url=d.get("base_url"),
                        compaction_trigger=int(trigger) if trigger is not None else None,
                        prompt_cache=bool(d.get("prompt_cache", False)),
                        extra={k: v for k, v in d.items() if k not in known})


def load_profiles(path: Path = MODELS_FILE) -> dict[str, ModelProfile]:
    data = yaml.safe_load(path.read_text()) or {}
    return {name: _profile(name, d) for name, d in data.items()}


def get_profile(name: str | None = None) -> ModelProfile:
    """A profile by name, or by bare model id (P2E_MODEL=gpt-6-luna from before profiles still works)."""
    name = name or os.environ.get("P2E_MODEL") or DEFAULT_PROFILE
    profiles = load_profiles()
    if name in profiles:
        return profiles[name]
    by_model = [p for p in profiles.values() if p.model == name]
    if by_model:
        return by_model[0]
    raise KeyError(f"no model profile {name!r} in {MODELS_FILE.name} (have: {', '.join(profiles)})")


def secret_env_names() -> set[str]:
    """Every key variable a profile names, so the sandbox can keep them away from agent commands."""
    try:
        return {p.api_key_env for p in load_profiles().values()}
    except (OSError, ValueError, KeyError, yaml.YAMLError):
        return set()


def usage_entries(message) -> list[Entry]:
    """Billable entries of one LangChain AIMessage.

    Anthropic: from the raw usage in response_metadata, one entry per `usage.iterations` element when present
    (langchain's usage_metadata leaves out the compaction step, often most of the request's cost). Other providers:
    from usage_metadata, whose input_tokens already include cached and cache-write tokens.
    """
    raw = (getattr(message, "response_metadata", None) or {}).get("usage")
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if isinstance(raw, dict) and ("cache_read_input_tokens" in raw or "iterations" in raw):
        steps = raw.get("iterations") or [raw]
        out = []
        for s in steps:
            cached = s.get("cache_read_input_tokens") or 0
            written = s.get("cache_creation_input_tokens") or 0
            reasoning = ((s.get("output_tokens_details") or raw.get("output_tokens_details") or {})
                         .get("thinking_tokens") or 0) if s.get("type", "message") == "message" else 0
            out.append(Entry(kind=s.get("type", "message"), prompt=(s.get("input_tokens") or 0) + cached + written,
                             cached=cached, written=written, output=s.get("output_tokens") or 0, reasoning=reasoning))
        return out
    um = getattr(message, "usage_metadata", None) or {}
    if not um:
        return []
    d_in, d_out = um.get("input_token_details") or {}, um.get("output_token_details") or {}
    return [Entry(kind="message", prompt=um.get("input_tokens", 0), cached=d_in.get("cache_read") or 0,
                  written=d_in.get("cache_creation") or 0, output=um.get("output_tokens", 0),
                  reasoning=d_out.get("reasoning") or 0)]
