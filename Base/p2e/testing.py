"""Test helpers shared by Base/tests and the version folders' tests: a scripted fake chat model and a toy case.

Nothing here talks to a provider. The root conftest.py wraps make_toy_case as the `toy_case` fixture.
"""
import subprocess

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from p2e import runner
from p2e.models import ModelProfile


class FakeClient(BaseChatModel):
    """Replays scripted turns as a LangChain chat model. A turn is a list of (tool_name, input) calls; an input
    given as a string is sent as arguments that are not valid JSON."""

    scripts: dict
    tokens: tuple = (1000, 200, 0)  # input (cached included), output, cached input
    n: int = 0

    def __init__(self, scripts: dict[str, list[list[tuple[str, dict]]]], tokens=(1000, 200, 0)):
        super().__init__(scripts={k: list(v) for k, v in scripts.items()}, tokens=tokens)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kw):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        system = next(m.content for m in messages if isinstance(m, SystemMessage))
        key = next(k for k in self.scripts if system.startswith(k))
        turn = self.scripts[key].pop(0)
        self.n += 1
        calls = [{"name": name, "args": inp, "id": f"call_{self.n}_{i}"}
                 for i, (name, inp) in enumerate(turn) if not isinstance(inp, str)]
        invalid = [{"name": name, "args": inp, "id": f"call_{self.n}_{i}", "error": "bad json", "type": "invalid_tool_call"}
                   for i, (name, inp) in enumerate(turn) if isinstance(inp, str)]
        msg = AIMessage(content="", tool_calls=calls, invalid_tool_calls=invalid, usage_metadata={
            "input_tokens": self.tokens[0], "output_tokens": self.tokens[1],
            "total_tokens": self.tokens[0] + self.tokens[1],
            "input_token_details": {"cache_read": self.tokens[2]}})
        return ChatResult(generations=[ChatGeneration(message=msg)])



def use_fake(monkeypatch, fake):
    """Every model profile returns `fake` instead of a provider's chat model."""
    monkeypatch.setattr(ModelProfile, "chat_model", lambda self, effort, **kw: fake)


SPEC = {"summary": "s", "hyperparameters": [], "claims": [{"claim_id": "a", "protocol": "p"}]}


def make_toy_case(tmp_path, monkeypatch):
    """A local git repo whose script prints an accuracy, plus task/case files for it."""
    repo = tmp_path / "toyrepo"
    repo.mkdir()
    (repo / "train.py").write_text(
        "import sys\nseed = int(sys.argv[sys.argv.index('--seed') + 1])\n"
        "print(f'Test accuracy: {0.80 + 0.01 * seed:.4f}')\n")
    subprocess.run("git init -q && git add . && git -c user.email=t@t -c user.name=t commit -qm init",
                   shell=True, cwd=repo, check=True)

    bench = tmp_path / "benchmark"
    case = bench / "toy"
    (case / "paper").mkdir(parents=True)
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(100, 100); w.write(case / "paper" / "p.pdf")
    (case / "task.yaml").write_text(yaml.safe_dump({
        "id": "toy", "paper_pdf": "paper/p.pdf", "repo_url": str(repo), "objective": "toy", "seeds": 2,
        "claims": [{"id": "acc", "metric": "acc", "setting": "toy", "unit": "%", "description": "acc"}]}))
    (case / "case.yaml").write_text(yaml.safe_dump({
        "id": "toy", "rubric": {"min_seeds": 2},
        "claims": [{"id": "acc", "metric": "acc", "setting": "toy", "unit": "%", "value": 80.5,
                    "tolerance": {"abs": 1.0}}]}))
    monkeypatch.setattr(runner, "BENCHMARK", bench)
    monkeypatch.setattr(runner, "RUNS", tmp_path / "runs")
    return repo


ENV = {"repo_dir": "repo", "python": "python3", "entrypoint": "repo/train.py",
       "setup_log": ["git clone"], "smoke_test": "ran", "ok": True}


def _run_spec(seed, regex=r"Test accuracy: ([0-9.]+)"):
    return {"run_id": f"acc_s{seed}", "claim_id": "acc", "seed": seed, "command": f"python3 train.py --seed {seed}",
            "workdir": "repo", "metric_regex": regex, "scale": 100}


def _set_target(value, discrepancies=()):
    """Move the toy case's hidden target (so the claim fails) and add ground-truth discrepancies."""
    path = runner.BENCHMARK / "toy" / "case.yaml"
    case = yaml.safe_load(path.read_text())
    case["claims"][0]["value"] = value
    case["discrepancies"] = list(discrepancies)
    path.write_text(yaml.safe_dump(case))


GT_SEED = {"claim_id": "acc", "category": "randomness", "also_acceptable": ["environment"],
           "summary": "seed variance", "key_evidence": ["seed-to-seed spread of 1 point"], "confidence": "confirmed"}


def _diag(status, category=None, conclusion="", log=None):
    return {"claim_id": "acc", "paper_value": 80.5, "measured": 80.5, "status": status, "category": category,
            "hypotheses": [{"hypothesis": "seed variance", "evidence_for": "seed-to-seed spread of 1 point",
                            "diagnostic_log": log}] if category else [],
            "conclusion": conclusion, "confidence": "medium"}


# ---------------------------------------------------------------- spec runs (CORE-Bench-shaped capsule)

SPEC_ENTRY = {"capsule_id": "capsule-0000001", "capsule_title": "Toy capsule", "field": "Computer Science",
              "language": "Python", "task_prompt": "Run 'main.py'.",
              "results": [{"Which model is best?": "CatBoost", "What is the AUC?": 0.957,
                           "Old accuracy?": 0.9506}] * 3}


def make_spec_case(tmp_path, monkeypatch, files: dict[str, str] | None = None, split: str = "test") -> str:
    """A capsule whose main.py prints two of the three answers; the third sits in a shipped file (a shortcut).
    Points p2e.corebench at it; returns the capsule id."""
    import io
    import json
    import tarfile

    from p2e import corebench
    files = files or {"code/README.md": "Run main.py with python3.", "code/main.py":
                      "print('best model: CatBoost')\nprint('AUC 0.957')\n", "data/old_results.txt": "accuracy 0.9506\n",
                      "results/output": "AUC 0.957 accuracy 0.9506", "REPRODUCING.md": "python main.py"}
    caps, tasks = tmp_path / "capsules", tmp_path / "tasks"
    caps.mkdir()
    with tarfile.open(caps / "capsule-0000001.tar.gz", "w:gz") as tar:
        for rel, text in files.items():
            info = tarfile.TarInfo(f"capsule-0000001/{rel}")
            info.size = len(text.encode())
            tar.addfile(info, io.BytesIO(text.encode()))
    data = tmp_path / "core_test.json"
    data.write_text(json.dumps([SPEC_ENTRY]))
    corebench.export([SPEC_ENTRY], out=tasks, data=data, split=split)
    prefix = "DEV_" if split == "dev" else ""
    empty = tmp_path / "other_split"
    for name, value in (("DATA", data), ("TASKS", tasks), ("CAPSULES", caps)):
        monkeypatch.setattr(corebench, prefix + name, value)
        if split == "dev":
            monkeypatch.setattr(corebench, name, empty / name.lower())
    monkeypatch.setattr(corebench, "RUNS", tmp_path / "runs")
    if split == "test":
        monkeypatch.setattr(corebench.new_run, "__defaults__", ("", None, tasks, caps))
        monkeypatch.setattr(corebench.finish, "__defaults__", (None, None, data, None))
    else:
        monkeypatch.setattr(corebench.new_run, "__defaults__", ("", None, empty / "tasks", empty / "capsules"))
    return "capsule-0000001"
