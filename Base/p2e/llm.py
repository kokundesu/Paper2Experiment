"""A tool-using agent as a LangGraph subgraph, with tracing, a budget and per-provider billing.

Each agent gets a system prompt, a set of tools bound to the run's sandbox, and a pydantic model it must submit
through the `submit` tool. The loop is a small graph (model -> tools -> model ..., with a nudge when the model answers
without a tool call) over a LangChain chat model built from a profile in models.yaml, so the same agent runs on
Anthropic, OpenAI or any OpenAI-compatible endpoint. Every request, response and tool call is appended to the run's
trace.jsonl; a callback bills each response from the provider's raw usage (Anthropic's compaction step included).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ValidationError

from . import spend
from .models import DEFAULT_PROFILE, Entry, ModelProfile, get_profile, usage_entries
from .sandbox import Sandbox

# Profile name from models.yaml (a bare model id such as gpt-6-luna also works).
DEFAULT_MODEL = os.environ.get("P2E_MODEL", DEFAULT_PROFILE)
# none / low / medium / high / xhigh / max (passed to the provider as its reasoning effort).
DEFAULT_EFFORT = os.environ.get("P2E_EFFORT", "medium")
# Multi-agent roles that judge results against the paper (Result Reviewer, Discrepancy Analyst). At medium they
# tended to read the logs and submit without a diagnostic run; P2E_REVIEW_EFFORT=medium gives the ablation.
REVIEW_EFFORT = os.environ.get("P2E_REVIEW_EFFORT", "high")
# Hard cap on LLM spend for one run (all agents of a workflow together).
RUN_BUDGET_USD = float(os.environ.get("P2E_RUN_BUDGET_USD", "5.0"))
# Cap on what one tool call returns to the model, in tokens. A first Haiku 5.5 test measured number-heavy training
# logs at about 1.7 characters per token, so one uncapped log could push a request past a price tier on its own.
TOOL_OUTPUT_TOKENS = int(os.environ.get("P2E_TOOL_OUTPUT_TOKENS", "8000"))
CHARS_PER_TOKEN = 1.7  # conservative: the densest text measured so far


class BudgetExceeded(RuntimeError):
    pass


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def cap_tokens(text: str, max_tokens: int | None = None) -> str:
    """Keep a tool output under `max_tokens` (estimated, default TOOL_OUTPUT_TOKENS): its head and, for logs the more
    useful part, its tail."""
    limit = int((max_tokens or TOOL_OUTPUT_TOKENS) * CHARS_PER_TOKEN)
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.3), int(limit * 0.7)
    cut = len(text) - head - tail
    return (f"{text[:head]}\n[... {cut} characters (~{estimate_tokens(text[head:len(text) - tail])} tokens) cut to keep "
            f"the request small; read the full output from its log file or with read_file offset/limit ...]\n"
            f"{text[-tail:]}")


@dataclass
class Usage:
    input_tokens: int = 0  # all prompt tokens, cached ones included, summed over requests (compaction steps too)
    output_tokens: int = 0
    reasoning_tokens: int = 0  # part of output_tokens
    cache_read: int = 0
    cache_write: int = 0
    requests: int = 0
    tool_calls: int = 0
    compactions: int = 0  # Anthropic server-side compaction steps
    compaction_input_tokens: int = 0
    max_prompt_tokens: int = 0  # largest single step: shows how close the run came to a price tier
    tier_steps: int = 0  # steps billed above the profile's first price tier
    wall_s: float = 0.0
    usd: float = 0.0  # summed per step, since tiered pricing depends on each step's prompt length

    def add(self, entries: list[Entry], profile: ModelProfile) -> None:
        self.requests += 1
        first_tier = profile.prices.first_tier_tokens()
        for e in entries:
            self.input_tokens += e.prompt
            self.output_tokens += e.output
            self.reasoning_tokens += e.reasoning
            self.cache_read += e.cached
            self.cache_write += e.written
            self.max_prompt_tokens = max(self.max_prompt_tokens, e.prompt)
            self.tier_steps += first_tier is not None and e.prompt > first_tier
            if e.kind == "compaction":
                self.compactions += 1
                self.compaction_input_tokens += e.prompt
            self.usd += profile.cost(e)

    def cost(self, model: str | None = None) -> float:
        return self.usd

    def merge(self, other: "Usage") -> None:
        for k in self.__dataclass_fields__:
            if k == "max_prompt_tokens":
                self.max_prompt_tokens = max(self.max_prompt_tokens, other.max_prompt_tokens)
            else:
                setattr(self, k, getattr(self, k) + getattr(other, k))


@dataclass
class Budget:
    """Spend shared by every agent in one run; checked before each request."""
    profile: ModelProfile = field(default_factory=lambda: get_profile(DEFAULT_MODEL))
    limit_usd: float = RUN_BUDGET_USD
    usage: Usage = field(default_factory=Usage)

    @property
    def model(self) -> str:
        return self.profile.model

    @property
    def reserve_usd(self) -> float:
        """Stop this far below the limit: room for one more large request (a prompt at the compaction trigger, or
        150k without compaction, plus 16k output)."""
        prompt = (self.profile.compaction_trigger or 150_000) + TOOL_OUTPUT_TOKENS
        return self.profile.cost(Entry(kind="message", prompt=prompt, cached=0, written=0, output=16_000))

    @property
    def spent_usd(self) -> float:
        return self.usage.usd

    def check(self, who: str) -> None:
        if self.spent_usd >= self.limit_usd - self.reserve_usd:
            raise BudgetExceeded(f"{who}: run budget exhausted (${self.spent_usd:.2f} of ${self.limit_usd:.2f})")
        # the installation's monthly cap (P2E_MONTHLY_BUDGET_USD), shared by every run and process: the same reserve
        # keeps the request about to be sent from taking the month over the cap
        if (cap := spend.monthly_limit()) is not None and (used := spend.spent()) >= cap - self.reserve_usd:
            raise BudgetExceeded(f"{who}: monthly budget exhausted (${used:.2f} of ${cap:.2f} this month)")


class Trace:
    """Append-only JSONL event log for one run."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()  # workers may log from several threads

    def log(self, agent: str, event: str, **data) -> None:
        rec = {"t": round(time.time(), 3), "agent": agent, "event": event, **data}
        line = json.dumps(rec, default=str) + "\n"
        with self._lock, self.path.open("a") as f:
            f.write(line)


class BillingCallback(BaseCallbackHandler):
    """Bills every chat model response to the agent and to the run budget.

    LangChain's usage_metadata leaves out Anthropic's compaction step, which `usage.iterations` reports and which is
    often most of that request's cost, so the bill comes from the raw usage (models.usage_entries).
    """

    def __init__(self, agent: str, profile: ModelProfile, usage: Usage, budget: Budget, trace: Trace):
        self.agent, self.profile, self.usage, self.budget, self.trace = agent, profile, usage, budget, trace
        self.last: list[Entry] = []

    _lock = threading.Lock()  # shared by every callback: parallel workers bill the same run budget

    def on_llm_end(self, response, **kwargs: Any) -> None:
        with self._lock:
            self._bill(response)

    def _bill(self, response) -> None:
        for gens in response.generations:
            for g in gens:
                msg = getattr(g, "message", None)
                entries = usage_entries(msg) if msg is not None else []
                raw = (response.llm_output or {}).get("usage")
                if hasattr(raw, "model_dump"):
                    raw = raw.model_dump()
                if isinstance(raw, dict) and raw.get("iterations") and len(entries) <= 1:
                    entries = usage_entries(AIMessage(content="", response_metadata={"usage": raw}))
                self.last = entries
                self.usage.add(entries, self.profile)
                self.budget.usage.add(entries, self.profile)
                spend.record(sum(self.profile.cost(e) for e in entries))
                first_tier = self.profile.prices.first_tier_tokens()
                for e in entries:
                    if first_tier is not None and e.prompt > first_tier:
                        self.trace.log(self.agent, "price_tier", step=e.kind, prompt_tokens=e.prompt,
                                       above=first_tier, cost_usd=round(self.profile.cost(e), 5))
                    if e.kind == "compaction":
                        self.trace.log(self.agent, "compaction", prompt_tokens=e.prompt, output_tokens=e.output)


# ---------------------------------------------------------------- tools


@dataclass
class ImageOutput:
    """A tool result that carries an image (view_image): `text` goes to the model with the image itself."""
    text: str
    data: str  # base64
    media_type: str = "image/png"


MAX_IMAGE_SIDE = 1568  # longest side sent to the model (larger images are scaled down)


def load_image(path: Path) -> ImageOutput | str:
    """An image file as PNG (scaled down if large), via macOS `sips`, which also opens PDF, TIFF, BMP, GIF, JPEG."""
    import base64
    import subprocess
    import tempfile

    if not path.is_file():
        return f"no such file: {path.name}"
    info = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], capture_output=True, text=True)
    dims = [int(x) for x in re.findall(r"pixel(?:Width|Height): (\d+)", info.stdout)]
    if info.returncode or len(dims) != 2:
        return (f"cannot open {path.name} as an image (sips: {(info.stderr or info.stdout).strip()[:200]}); "
                f"convert it to PNG first (e.g. re-save the figure as PNG)")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "view.png"
        cmd = ["sips", "-s", "format", "png", str(path), "--out", str(out)]
        if max(dims) > MAX_IMAGE_SIDE:
            cmd[1:1] = ["-Z", str(MAX_IMAGE_SIDE)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode or not out.is_file():
            return f"cannot convert {path.name} to PNG ({r.stderr.strip()[:200]})"
        data = out.read_bytes()
    if len(data) > 4_500_000:
        return f"{path.name} is too large to view even scaled down"
    scale = min(1.0, MAX_IMAGE_SIDE / max(dims))
    return ImageOutput(f"image {path.name} ({dims[0]}x{dims[1]} px{', scaled down' if scale < 1 else ''})",
                       base64.b64encode(data).decode())


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[[dict], str]

    def spec(self) -> dict:
        return _fn_spec(self.name, self.description, self.schema)


def sandbox_tools(sb: Sandbox, *, shell: bool = True, write: bool = True, max_timeout_s: int = 1800) -> list[Tool]:
    def run_shell(a: dict) -> str:
        timeout = min(int(a.get("timeout_s", 600)), max_timeout_s)
        return sb.run(a["command"], a.get("workdir", "."), timeout, tag="shell").summary()

    def read_file(a: dict) -> str:
        path = sb.resolve(a["path"])
        lines = path.read_text(errors="replace").splitlines()
        start = max(int(a.get("offset", 1)), 1)
        limit = int(a.get("limit", 400))
        chunk = lines[start - 1:start - 1 + limit]
        body = "\n".join(f"{i:5d}\t{line}" for i, line in enumerate(chunk, start))
        more = f"\n[{len(lines)} lines total; continue with offset={start + limit}]" if start - 1 + limit < len(lines) else ""
        return body + more

    def write_file(a: dict) -> str:
        path = sb.resolve(a["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(a["content"])
        if path.is_relative_to(sb.workspace.resolve()):
            sb.authored.add(path.relative_to(sb.workspace.resolve()).as_posix())
        return f"wrote {len(a['content'])} chars to {a['path']}"

    def list_dir(a: dict) -> str:
        root = sb.resolve(a.get("path", "."))
        depth = int(a.get("depth", 2))
        out = []
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if len(rel.parts) > depth or any(part.startswith(".") or part in ("__pycache__", ".venv", "site-packages") for part in rel.parts):
                continue
            out.append(f"{rel}{'/' if p.is_dir() else ''}")
        return "\n".join(out[:500]) or "(empty)"

    tools = [
        Tool("read_file", "Read a text file in the workspace with line numbers.",
             {"type": "object", "properties": {
                 "path": {"type": "string", "description": "Path relative to the workspace"},
                 "offset": {"type": "integer", "description": "1-based first line (default 1)"},
                 "limit": {"type": "integer", "description": "Max lines (default 400)"}},
              "required": ["path"]}, read_file),
        Tool("list_dir", "List files under a workspace directory (hidden dirs and venvs skipped).",
             {"type": "object", "properties": {
                 "path": {"type": "string"}, "depth": {"type": "integer"}}}, list_dir),
    ]
    if write:
        tools.append(Tool("write_file", "Create or overwrite a text file in the workspace.",
                          {"type": "object", "properties": {
                              "path": {"type": "string"}, "content": {"type": "string"}},
                           "required": ["path", "content"]}, write_file))
    if shell:
        tools.append(Tool(
            "run_shell",
            "Run a bash command inside the workspace sandbox. Returns exit code and the head/tail of combined "
            "stdout+stderr; the full output is saved to the command's log file, which is the only evidence the "
            "evaluator accepts for a result, so print experiment output instead of redirecting it to files. "
            "No sudo. Use `uv venv` / `uv pip install` for Python environments; for R, create an environment in "
            "the workspace with `micromamba create -y -p ./.renv -c conda-forge r-base=<version> r-<package> ...` "
            "and run `./.renv/bin/Rscript`.",
            {"type": "object", "properties": {
                "command": {"type": "string"},
                "workdir": {"type": "string", "description": "Directory relative to the workspace (default '.')"},
                "timeout_s": {"type": "integer", "description": f"Wall-clock limit, max {max_timeout_s}"}},
             "required": ["command"]}, run_shell))
    tools.append(Tool("view_image", "Look at an image file in the workspace (a figure a run wrote: PNG, JPEG, PDF, "
                                    "TIFF...). Use it for questions about a figure; prefer printed numbers when they "
                                    "exist.",
                      {"type": "object", "properties": {"path": {"type": "string",
                                                                 "description": "Path relative to the workspace"}},
                       "required": ["path"]}, lambda a: load_image(sb.resolve(a["path"]))))
    from .skills import read_tool  # every agent of every version gets the same skill library (p2e.skills)
    if (skill := read_tool()) is not None:
        tools.append(skill)
    return tools




# ---------------------------------------------------------------- agent

NUDGE = "Continue the task with your tools, and finish by calling `submit`."


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    turn: int
    submitted: dict | None  # the validated submission, as plain data (checkpointable)


def _fn_spec(name: str, description: str, parameters: dict) -> dict:
    """OpenAI function format, which LangChain converts for every provider."""
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _text(msg: AIMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content
    return "\n".join(b.get("text", "") for b in msg.content
                     if isinstance(b, dict) and b.get("type") in ("text", "output_text") and b.get("text"))


def _without_image_data(content):
    """Message content for the trace: images become a placeholder (their bytes would swamp the trace)."""
    if not isinstance(content, list):
        return content
    out = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "image":
            out.append({"type": "image", "omitted_bytes": len(b.get("source", {}).get("data", "")) * 3 // 4})
        elif isinstance(b, dict) and b.get("type") == "image_url":
            out.append({"type": "image_url", "omitted_bytes": len(b.get("image_url", {}).get("url", "")) * 3 // 4})
        else:
            out.append(b)
    return out


def _message_record(m) -> dict:
    """A message exactly as the model receives it, as plain data for the trace."""
    rec = {"role": m.type, "content": _without_image_data(m.content), "id": m.id}
    if getattr(m, "tool_calls", None):
        rec["tool_calls"] = [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in m.tool_calls]
    if getattr(m, "invalid_tool_calls", None):
        rec["invalid_tool_calls"] = [{"id": c.get("id"), "name": c.get("name"), "args": c.get("args")}
                                     for c in m.invalid_tool_calls]
    if getattr(m, "tool_call_id", None):
        rec["tool_call_id"] = m.tool_call_id
    return rec


def replay_messages(events: list[dict], agent: str) -> list[dict]:
    """`agent`'s current conversation rebuilt from the trace alone: its system prompt plus every message, ending with
    the model's reply to the latest request (drop that reply to get exactly what the latest request sent). A `start` with history_len == 0 opens a new conversation; otherwise the conversation
    continues (Agent.converse enforces that it is the previous one)."""
    system, messages = None, []
    for e in events:
        if e.get("agent") != agent:
            continue
        if e.get("event") == "start":
            system = e.get("system")
            if not e.get("history_len"):
                messages = []
        elif e.get("event") == "message":
            messages.append(e["message"])
    return [{"role": "system", "content": system}, *messages] if system is not None else messages


ToolGuard = Callable[[str, dict], "str | None"]  # (tool name, args) -> reason to deny, or None to allow
ToolPost = Callable[[str, dict, str, bool], "tuple[str, bool]"]  # (name, args, output, is_error) -> (output, is_error)


def _refusal(msg: AIMessage) -> str | None:
    """Anthropic: stop_reason "refusal" (with stop_details); OpenAI Responses: a refusal content part."""
    meta = msg.response_metadata or {}
    if meta.get("stop_reason") == "refusal":
        details = meta.get("stop_details") or {}
        return f"stop_reason=refusal {details}"
    if isinstance(msg.content, list):
        parts = [b.get("refusal", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "refusal"]
        if parts:
            return "\n".join(parts)
    return None


@dataclass
class Agent:
    name: str
    system: str
    tools: list[Tool]
    output: type[BaseModel]
    trace: Trace
    budget: Budget
    effort: str = DEFAULT_EFFORT
    max_turns: int = 40
    max_cost_usd: float = 5.0  # this agent's own cap, on top of the shared run budget
    usage: Usage = field(default_factory=Usage)
    chat: Any = None  # a LangChain chat model; built from the run's profile when not given (tests pass a fake)
    # Tool pipeline hooks, in order: a pre guard may deny a call (its reason goes back to the model); a post hook may
    # rewrite the output. Both run for every call except `submit`, which is validated against `output`.
    pre_tool: list[ToolGuard] = field(default_factory=list)
    post_tool: list[ToolPost] = field(default_factory=list)
    _recorded: set = field(default_factory=set, init=False, repr=False)  # message ids already written to the trace
    _last_messages: list | None = field(default=None, init=False, repr=False)

    @property
    def model(self) -> str:
        return self.budget.model

    @property
    def profile(self) -> ModelProfile:
        return self.budget.profile

    def _submit_spec(self) -> dict:
        return _fn_spec("submit", f"Submit your final {self.output.__name__}. Call this exactly once, when done. "
                                  "The input is validated; on error you get the message back and can retry.",
                        self.output.model_json_schema())

    # ---- graph nodes

    def _model_node(self, state: AgentState) -> dict:
        turn = state["turn"] + 1
        if turn > self.max_turns:
            raise BudgetExceeded(f"{self.name}: no submission after {self.max_turns} turns")
        self.budget.check(self.name)
        if self.usage.usd >= self.max_cost_usd:
            raise BudgetExceeded(f"{self.name}: agent cap reached (${self.usage.usd:.2f} of ${self.max_cost_usd:.2f})")
        self._record(state["messages"])  # model-visible is recorded: everything sent below is in the trace first
        resp: AIMessage = self._runnable.invoke([SystemMessage(self.system), *state["messages"]],
                                                config={"callbacks": [self._billing]})
        self._record([resp])
        meta = resp.response_metadata or {}
        self.trace.log(self.name, "response", turn=turn, text=_text(resp),
                       status=meta.get("stop_reason") or meta.get("status"),
                       incomplete=(meta.get("incomplete_details") or {}).get("reason")
                       if isinstance(meta.get("incomplete_details"), dict) else None,
                       tool_calls=[{"name": c["name"], "input": json.dumps(c["args"])} for c in resp.tool_calls]
                       + [{"name": c.get("name"), "input": c.get("args"), "invalid": True}
                          for c in resp.invalid_tool_calls],
                       usage=[e.__dict__ for e in self._billing.last])
        if refusal := _refusal(resp):
            raise RuntimeError(f"{self.name}: model refused ({refusal[:300]})")
        return {"messages": [resp], "turn": turn}

    def _after_model(self, state: AgentState) -> str:
        last: AIMessage = state["messages"][-1]
        return "tools" if (last.tool_calls or last.invalid_tool_calls) else "nudge"

    def _nudge_node(self, state: AgentState) -> dict:
        return {"messages": [HumanMessage(NUDGE)]}

    def _tools_node(self, state: AgentState) -> dict:
        last: AIMessage = state["messages"][-1]
        out_msgs, submitted, images = [], None, []
        for bad in last.invalid_tool_calls:
            self.usage.tool_calls += 1
            self.budget.usage.tool_calls += 1
            out = f"Arguments are not valid JSON ({bad.get('error') or 'parse error'}); call the tool again."
            self.trace.log(self.name, "tool_result", tool=bad.get("name"), is_error=True, output=out)
            out_msgs.append(ToolMessage(f"ERROR: {out}", tool_call_id=bad["id"], status="error"))
        for call in last.tool_calls:
            self.usage.tool_calls += 1
            self.budget.usage.tool_calls += 1
            name, args = call["name"], call["args"]
            denied = None if name == "submit" else next((r for g in self.pre_tool if (r := g(name, args))), None)
            if denied:
                out, err = f"Not allowed: {denied}", True
                self.trace.log(self.name, "tool_denied", tool=name, reason=denied)
            elif name == "submit":
                try:
                    submitted = self.output.model_validate(args).model_dump(mode="json")
                    out, err = "accepted", False
                except ValidationError as e:
                    out, err = f"Validation failed, fix and resubmit:\n{e}", True
            elif name in self._tools:
                try:
                    out, err = self._tools[name].fn(args), False
                except Exception as e:  # tool errors go back to the model
                    out, err = f"{type(e).__name__}: {e}", True
            else:
                out, err = f"unknown tool {name}", True
            image = None
            if isinstance(out, ImageOutput):
                image, out = out, out.text
            if name != "submit" and not denied:
                for hook in self.post_tool:
                    out, err = hook(name, args, out, err)
            out = cap_tokens(out)
            self.trace.log(self.name, "tool_result", tool=name, is_error=err, output=out[:4000],
                           **({"image_bytes": len(image.data) * 3 // 4} if image else {}))
            if image is not None and not err and self.profile.provider == "anthropic":
                out_msgs.append(ToolMessage([{"type": "text", "text": out},
                                             {"type": "image", "source": {"type": "base64",
                                                                          "media_type": image.media_type,
                                                                          "data": image.data}}],
                                            tool_call_id=call["id"], status="success"))
                continue
            if image is not None and not err:  # tool messages are text-only here: the image follows as a user turn
                images.append(HumanMessage([{"type": "text", "text": f"view_image result: {out}"},
                                            {"type": "image_url",
                                             "image_url": {"url": f"data:{image.media_type};base64,{image.data}"}}]))
                out += " (the image follows in the next message)"
            out_msgs.append(ToolMessage(f"ERROR: {out}" if err else out, tool_call_id=call["id"],
                                        status="error" if err else "success"))
        out_msgs += images
        return {"messages": out_msgs, **({"submitted": submitted} if submitted is not None else {})}

    def _after_tools(self, state: AgentState) -> str:
        return END if state.get("submitted") is not None else "model"

    def graph(self):
        """The agent's loop as a LangGraph graph: model -> tools -> model ..., nudge when no tool is called."""
        g = StateGraph(AgentState)
        g.add_node("model", self._model_node)
        g.add_node("tools", self._tools_node)
        g.add_node("nudge", self._nudge_node)
        g.add_edge(START, "model")
        g.add_conditional_edges("model", self._after_model, ["tools", "nudge"])
        g.add_edge("nudge", "model")
        g.add_conditional_edges("tools", self._after_tools, ["model", END])
        return g.compile()

    def _record(self, messages: list) -> None:
        for m in messages:
            if m.id not in self._recorded:
                self._recorded.add(m.id)
                self.trace.log(self.name, "message", message=_message_record(m))

    def run(self, task: str) -> BaseModel:
        return self.converse([], task)[0]

    def adopt(self, history: list) -> None:
        """Take over a conversation another Agent object recorded (e.g. after a resume): its messages are already in
        the trace, and `converse(history, ...)` may continue it."""
        self._recorded.update(m.id for m in history)
        self._last_messages = history

    def converse(self, history: list, task: str, *, output: type[BaseModel] | None = None,
                 tools: list[Tool] | None = None, max_turns: int | None = None) -> tuple[BaseModel, list]:
        """Continue a conversation: `history` is [] (a new one) or exactly the messages the previous call returned.
        `output` and `tools` override the agent's for this call (e.g. a planner that also executes a task in its own
        context). Returns the submission and the conversation so far, ending with the accepted `submit` call."""
        if history and history is not self._last_messages:
            raise ValueError(f"{self.name}: history must be [] or the messages the previous converse() returned")
        saved = self.output, self.tools, self.max_turns
        self.output, self.tools = output or self.output, tools if tools is not None else self.tools
        self.max_turns = max_turns or self.max_turns
        self._tools = {t.name: t for t in self.tools}
        chat = self.chat if self.chat is not None else self.profile.chat_model(self.effort)
        specs = [t.spec() for t in self.tools] + [self._submit_spec()]
        self._runnable = chat.bind_tools(specs).bind(**self.profile.invoke_kwargs(self.name))
        self._billing = BillingCallback(self.name, self.profile, self.usage, self.budget, self.trace)
        self.trace.log(self.name, "start", model=self.model, profile=self.profile.name, effort=self.effort, task=task,
                       system=self.system, history_len=len(history), output_schema=self.output.__name__,
                       tools=[t.name for t in self.tools])
        t0 = time.monotonic()
        try:
            # Each turn passes model, then tools or nudge: allow the turn limit (checked in the model node) to bind.
            final = self.graph().invoke({"messages": [*history, HumanMessage(task)], "turn": 0, "submitted": None},
                                        config={"recursion_limit": 2 * self.max_turns + 5})
            submitted = self.output.model_validate(final["submitted"])
            self.trace.log(self.name, "submit", output=submitted.model_dump())
            self._last_messages = final["messages"]
            return submitted, final["messages"]
        finally:
            self.output, self.tools, self.max_turns = saved
            elapsed = time.monotonic() - t0
            self.usage.wall_s += elapsed
            self.budget.usage.wall_s += elapsed
            self.trace.log(self.name, "end", usage=self.usage.__dict__, cost_usd=round(self.usage.usd, 4),
                           run_spent_usd=round(self.budget.spent_usd, 4))
