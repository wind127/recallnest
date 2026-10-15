"""Install the RecallNest workflow and register its local-only MCP server.

Run from a source checkout: uv run --locked python scripts/install_codex.py
No auth tokens, personal history, model settings or unrelated skills are read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_atomic(path, text):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_codex(command, arguments):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run([command, *arguments], capture_output=True, text=True, encoding="utf-8", timeout=30, **options)


def install(*, data_dir, skills_dir, codex_command=None, dry_run=False):
    checkout = Path(__file__).resolve().parents[1]
    skill = (checkout / "skills" / "recallnest" / "SKILL.md").read_text(encoding="utf-8")
    target = skills_dir.expanduser().resolve() / "recallnest"
    data_dir = data_dir.expanduser().resolve()
    args = ["-m", "recallnest", "mcp", "--local-only", "--data-dir", str(data_dir)]
    command = codex_command or shutil.which("codex.cmd" if os.name == "nt" else "codex")
    result = {"skill_dir": str(target), "data_dir": str(data_dir), "mcp": {"command": sys.executable, "args": args},
              "dry_run": dry_run, "restart_codex": True}
    manifest_path = target / ".recallnest-install.json"
    skill_path = target / "SKILL.md"
    if target.is_symlink() or (target.exists() and getattr(target.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise ValueError("Skill destination is a link; choose a regular --skills-dir")
    if target.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing = skill_path.read_text(encoding="utf-8")
            if manifest.get("managed_by") != "recallnest" or digest(existing) != manifest.get("skill_sha256"):
                raise ValueError()
        except (OSError, ValueError):
            raise ValueError("Existing recallnest skill is unmanaged or edited; preserve it and choose another --skills-dir") from None
    if dry_run:
        return result
    if not command:
        raise ValueError("Codex CLI not found; install it or use the manual MCP configuration in docs/codex.md")
    current = run_codex(command, ["mcp", "get", "recallnest", "--json"])
    if current.returncode == 0:
        try:
            previous = json.loads(current.stdout)["transport"]
            previous_args = previous.get("args", [])
            if previous.get("type") != "stdio" or previous_args[:3] != ["-m", "recallnest", "mcp"]:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ValueError("An unrelated MCP server already uses the name recallnest; preserve it and configure manually") from None
    elif "No MCP server named" not in current.stderr:
        raise ValueError("Unable to inspect the recallnest MCP entry; no configuration was changed")
    target.mkdir(parents=True, exist_ok=True)
    write_atomic(skill_path, skill)
    write_atomic(manifest_path, json.dumps({"managed_by": "recallnest", "skill_sha256": digest(skill)}, indent=2) + "\n")
    registered = run_codex(command, ["mcp", "add", "recallnest", "--", sys.executable, *args])
    if registered.returncode:
        raise ValueError("Skill installed, but MCP registration failed; retry setup or configure manually (docs/codex.md)")
    return result


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Connect local RecallNest to Codex without a model API key")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("RECALLNEST_DATA_DIR", "~/.recallnest")))
    parser.add_argument("--skills-dir", type=Path, default=Path("~/.agents/skills"))
    parser.add_argument("--codex-command", help="Explicit Codex CLI executable")
    parser.add_argument("--dry-run", action="store_true", help="Show paths and MCP configuration without writing anything")
    options = parser.parse_args(argv)
    try:
        result = install(**vars(options))
    except ValueError as error:
        print("RecallNest setup: " + str(error), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        # Subprocess output may contain unrelated host configuration; never echo it.
        print("RecallNest setup failed. Check CLI availability and existing skill/MCP names; see docs/codex.md. Existing personal data is untouched.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
