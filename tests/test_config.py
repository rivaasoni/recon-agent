"""Smoke tests for Phase 1.

A "smoke test" is a cheap test that answers one question: is the thing wired up
at all? It will not catch subtle bugs, and that is fine — its job is to fail
loudly if the project structure or imports are broken.
"""

from pathlib import Path

from recon.config import settings


def test_project_root_is_this_repo():
    """settings.project_root should point at the folder holding CLAUDE.md."""
    assert (settings.project_root / "CLAUDE.md").exists()


def test_paths_are_inside_the_project():
    """Nothing should resolve to somewhere unexpected on the filesystem."""
    for path in (settings.raw_dir, settings.processed_dir, settings.duckdb_path):
        assert isinstance(path, Path)
        assert settings.project_root in path.parents


def test_ensure_dirs_is_safe_to_run_twice():
    """Calling it repeatedly must not raise."""
    settings.ensure_dirs()
    settings.ensure_dirs()
    assert settings.raw_dir.is_dir()
    assert settings.processed_dir.is_dir()


def test_missing_api_key_gives_a_helpful_error(monkeypatch):
    """A missing key should explain the fix, not just blow up with a KeyError.

    `monkeypatch` is a pytest helper that temporarily changes the environment
    and automatically undoes it when the test finishes.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    try:
        settings.anthropic_api_key()
    except RuntimeError as err:
        assert "cp .env.example .env" in str(err)
    else:
        raise AssertionError("Expected a RuntimeError when the key is missing")


def test_model_defaults_to_opus_5(monkeypatch):
    """Without RECON_MODEL set, we should fall back to the documented default."""
    monkeypatch.delenv("RECON_MODEL", raising=False)

    from recon.config import Settings

    assert Settings().model == "claude-opus-5"
