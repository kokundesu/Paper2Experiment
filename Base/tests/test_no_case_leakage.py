"""The system must not know the benchmark: no case id, repository, dataset setting or paper id in agent-facing code.

Success rates are measured on cases the system was not tuned on, so prompts and code may carry general reproduction
practice but nothing that names or hints at a specific case. The web UI (p2e/web) is analysis tooling the agents never
see and is not checked. Version folders (SingleAgent, Multiagent/*) hold prompts and are checked too.
"""
import re
from pathlib import Path

import yaml

from p2e.versions import version_dirs

ROOT = Path(__file__).resolve().parent.parent


def case_identifiers() -> set[str]:
    ids: set[str] = set()
    for f in sorted((ROOT / "benchmark").glob("*/task.yaml")):
        t = yaml.safe_load(f.read_text())
        ids.add(t["id"])
        owner, repo = t["repo_url"].rstrip("/").split("/")[-2:]
        ids.update({owner, repo})
        ids.update(re.findall(r"\d{4}\.\d{4,5}", t.get("paper_url", "") + t.get("paper_pdf", "")))
        for c in t.get("claims", []):
            ids.add(c["id"])
            setting = str(c.get("setting", ""))
            if re.fullmatch(r"[A-Za-z][\w-]{2,}", setting):  # single-word dataset settings (cora, etth1, ...)
                ids.add(setting)
    return {i for i in ids if len(i) >= 3}


def agent_facing_sources() -> list[Path]:
    """Base/p2e (minus the web UI and the test helpers) and every version folder's workflow code (minus its tests)."""
    base = [p for p in sorted((ROOT / "p2e").rglob("*.py"))
            if "web" not in p.relative_to(ROOT / "p2e").parts and p.name != "testing.py"]
    versions = [p for d in version_dirs() for p in sorted(d.rglob("*.py")) if "tests" not in p.relative_to(d).parts]
    return base + versions


def test_identifiers_are_collected():
    ids = {i.lower() for i in case_identifiers()}
    assert len(ids) > 10  # the check must actually have something to look for


def test_no_case_identifier_in_agent_facing_code():
    ids = case_identifiers()
    hits = []
    for path in agent_facing_sources():
        text = path.read_text()
        for ident in ids:
            for m in re.finditer(rf"(?<![\w/.-]){re.escape(ident)}(?![\w-])", text, flags=re.IGNORECASE):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(ROOT)}:{line}: {ident}")
    assert not hits, "case-specific identifiers in agent-facing code:\n" + "\n".join(sorted(hits))
