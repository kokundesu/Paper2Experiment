"""Discovery of the workflow versions that live next to Base/.

Each version is a folder with a `workflow.py` that defines `NAME` (the name `p2e run --workflow` takes),
`DESCRIPTION` (one line) and `run(ctx, **kw) -> EvalResult`; a version that supports `p2e resume` also sets
`RESUMABLE = True` and accepts `resume=True`. Folders searched, relative to the repository root (the parent of Base/):

    SingleAgent/                 one version
    Multiagent/<Version>/        one version per subfolder

Versions import the shared code from `p2e` (Base/p2e) and may import a sibling version with `load(<folder>)`.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .sandbox import PROJECT_ROOT

REPO_ROOT = Path(os.environ.get("P2E_VERSIONS_ROOT", PROJECT_ROOT.parent)).resolve()


def version_dirs() -> list[Path]:
    dirs = [REPO_ROOT / "SingleAgent"]
    multi = REPO_ROOT / "Multiagent"
    if multi.is_dir():
        dirs += sorted(p for p in multi.iterdir() if p.is_dir())
    return [d for d in dirs if (d / "workflow.py").is_file()]


def _import(folder: Path) -> ModuleType:
    name = f"p2e_versions.{folder.parent.name}.{folder.name}" if folder.parent != REPO_ROOT else f"p2e_versions.{folder.name}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, folder / "workflow.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # before exec, so the module can be found while it imports siblings
    spec.loader.exec_module(module)
    for attr in ("NAME", "DESCRIPTION", "run"):
        if not hasattr(module, attr):
            raise ImportError(f"{folder / 'workflow.py'} does not define {attr}")
    return module


@lru_cache(maxsize=1)
def discover() -> dict[str, ModuleType]:
    """Workflow name -> its module, for every version folder."""
    found: dict[str, ModuleType] = {}
    for folder in version_dirs():
        module = _import(folder)
        if module.NAME in found:
            raise ImportError(f"two versions use the workflow name {module.NAME!r}")
        found[module.NAME] = module
    return found


def load(folder: str) -> ModuleType:
    """A version module by folder name (e.g. "PlannerRuntime") or workflow name (e.g. "planner")."""
    for path in version_dirs():
        if path.name == folder:
            return _import(path)
    workflows = discover()
    if folder in workflows:
        return workflows[folder]
    raise KeyError(f"no version folder or workflow named {folder!r} under {REPO_ROOT}")
