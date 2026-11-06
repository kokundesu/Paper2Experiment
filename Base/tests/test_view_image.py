"""view_image: every agent can look at a figure; Anthropic gets the image in the tool result, other providers in a
user turn; the trace keeps a placeholder instead of the bytes."""
import json
import struct
import zlib

import pytest

from p2e.llm import Agent, Budget, ImageOutput, Trace, load_image, sandbox_tools
from p2e.sandbox import Sandbox
from p2e.spec import Answers
from p2e.testing import FakeClient


def _png(path, w=40, h=20):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_load_image_and_errors(tmp_path):
    _png(tmp_path / "fig.png")
    img = load_image(tmp_path / "fig.png")
    assert isinstance(img, ImageOutput) and "40x20" in img.text and img.data
    (tmp_path / "notes.txt").write_text("not an image")
    assert "cannot open" in load_image(tmp_path / "notes.txt")
    assert "no such file" in load_image(tmp_path / "nope.png")


@pytest.mark.parametrize("profile, in_tool_result", [("haiku55", True), ("luna", False)])
def test_image_reaches_the_model_and_not_the_trace(tmp_path, monkeypatch, profile, in_tool_result):
    from p2e.models import get_profile
    sb = Sandbox(tmp_path / "run")
    _png(sb.workspace / "fig.png")
    assert "view_image" in {t.name for t in sandbox_tools(sb, shell=False, write=False)}
    sent = []
    orig = FakeClient._generate

    def spy(self, messages, *a, **kw):
        sent.append(messages)
        return orig(self, messages, *a, **kw)

    monkeypatch.setattr(FakeClient, "_generate", spy)
    fake = FakeClient({"Look": [[("view_image", {"path": "fig.png"})], [("submit", {"answers": []})]]})
    trace = Trace(tmp_path / "trace.jsonl")
    agent = Agent("a", "Look at the figure.", sandbox_tools(sb), Answers, trace, Budget(profile=get_profile(profile)),
                  chat=fake)
    agent.run("go")
    second = sent[1]
    tool_msg = next(m for m in second if m.type == "tool")
    has_image = lambda c: isinstance(c, list) and any(b.get("type") in ("image", "image_url") for b in c)
    assert has_image(tool_msg.content) == in_tool_result
    assert in_tool_result or has_image(second[-1].content)
    text = (tmp_path / "trace.jsonl").read_text()
    assert "omitted_bytes" in text and len(text) < 20000
    assert all(len(json.dumps(json.loads(l))) < 8000 for l in text.splitlines())
