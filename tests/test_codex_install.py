import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def installer():
    path = Path(__file__).resolve().parents[1] / "scripts" / "install_codex.py"
    spec = importlib.util.spec_from_file_location("recallnest_codex_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_dry_run_never_reads_or_writes_personal_data(tmp_path, installer, monkeypatch):
    monkeypatch.setattr(installer, "run_codex", lambda *a: pytest.fail("dry run called Codex"))
    data = tmp_path / "private"
    result = installer.install(data_dir=data, skills_dir=tmp_path / "skills", dry_run=True)
    assert result["mcp"]["args"][-3:] == ["--local-only", "--data-dir", str(data)]
    assert list(tmp_path.iterdir()) == []


def test_installer_idempotent_registration_and_preserves_edited_skill(tmp_path, installer, monkeypatch):
    calls = []
    def codex(command, args):
        calls.append(args)
        if args[1] == "get":
            return SimpleNamespace(returncode=1, stderr="Error: No MCP server named 'recallnest' found.", stdout="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(installer, "run_codex", codex)
    data, skills = tmp_path / "私有 data", tmp_path / "skills"
    kwargs = dict(data_dir=data, skills_dir=skills, codex_command="fake")
    installer.install(**kwargs)
    result = installer.install(**kwargs)
    assert calls[-1] == ["mcp", "add", "recallnest", "--", result["mcp"]["command"], *result["mcp"]["args"]]
    assert not data.exists()
    installed = skills / "recallnest" / "SKILL.md"
    original = installed.read_text(encoding="utf-8")
    assert original == (Path(__file__).resolve().parents[1] / "skills/recallnest/SKILL.md").read_text(encoding="utf-8")
    installed.write_text(original + "\nLocal customization\n", encoding="utf-8")
    count = len(calls)
    with pytest.raises(ValueError, match="edited"):
        installer.install(**kwargs)
    assert len(calls) == count and installed.read_text(encoding="utf-8").endswith("Local customization\n")


def test_installer_preserves_unrelated_same_name_mcp_and_skill(tmp_path, installer, monkeypatch):
    calls = []
    def codex(command, args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"transport": {"type": "stdio", "command": "other", "args": ["private"]}}))
    monkeypatch.setattr(installer, "run_codex", codex)
    with pytest.raises(ValueError, match="unrelated MCP"):
        installer.install(data_dir=tmp_path / "data", skills_dir=tmp_path / "skills", codex_command="fake")
    assert len(calls) == 1 and not (tmp_path / "skills").exists()
    destination = tmp_path / "skills" / "recallnest"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("private skill")
    with pytest.raises(ValueError, match="unmanaged"):
        installer.install(data_dir=tmp_path / "data", skills_dir=tmp_path / "skills", codex_command="fake")
    assert len(calls) == 1


def test_installer_does_not_assume_get_failures_mean_server_missing(tmp_path, installer, monkeypatch):
    monkeypatch.setattr(installer, "run_codex", lambda *a: SimpleNamespace(returncode=1, stderr="permission error with sensitive config", stdout=""))
    with pytest.raises(ValueError, match="no configuration was changed"):
        installer.install(data_dir=tmp_path / "data", skills_dir=tmp_path / "skills", codex_command="fake")
    assert not (tmp_path / "skills").exists()
