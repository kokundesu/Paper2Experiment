"""Fixtures for every test under Paper2Exp (Base/tests and each version folder's tests)."""
import pytest

from p2e.testing import make_toy_case


@pytest.fixture(autouse=True)
def _isolated_workspaces(tmp_path, monkeypatch):
    """Sandboxes create their workspace under P2E_WORKSPACE_ROOT; keep tests out of the real ~/Library/Caches."""
    monkeypatch.setenv("P2E_WORKSPACE_ROOT", str(tmp_path / "_workspaces"))


@pytest.fixture(autouse=True)
def _luna_profile(monkeypatch):
    """Price everything as gpt-6-luna; no test talks to a provider."""
    monkeypatch.setenv("P2E_MODEL", "luna")


@pytest.fixture
def toy_case(tmp_path, monkeypatch):
    """A local git repo whose script prints an accuracy, plus task/case files for it."""
    return make_toy_case(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _empty_skill_library(tmp_path, monkeypatch):
    """Tests do not depend on the live skill library (skills/); tests of p2e.skills build their own."""
    from p2e import skills
    monkeypatch.setattr(skills, "ROOT", tmp_path / "_skills")
