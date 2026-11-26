"""Tests for scripts/add_skills.py using a throwaway local git repo of skills."""

import importlib.util
import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "add_skills.py"


def load(tmp: Path):
    spec = importlib.util.spec_from_file_location("add_skills", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SKILLS = tmp / ".claude/skills"
    mod.AGENTS = tmp / ".claude/agents"
    mod.LOCK = mod.SKILLS / "skills.lock.json"
    mod.INDEX = mod.SKILLS / "README.md"
    mod.SKILLS.mkdir(parents=True)
    mod.AGENTS.mkdir(parents=True)
    return mod


def make_repo(tmp: Path) -> str:
    repo = tmp / "src-repo"
    for name in ("alpha", "beta"):
        d = repo / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: The {name} skill\n---\nDo {name}.\n")
    (repo / "skills" / "alpha" / "ref.md").write_text("extra file")
    bad = repo / "skills" / "evil"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: ../../escape\n---\n")
    cmds = [["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]]
    for c in cmds:
        subprocess.run(["git", *c], cwd=repo, check=True)
    return str(repo)


def test_install_attach_index_and_reject_unsafe_names(tmp_path):
    mod = load(tmp_path)
    (mod.AGENTS / "writer.md").write_text("---\nname: writer\ndescription: d\ntools: Read\n---\nBody stays.\n")
    url = make_repo(tmp_path)

    added = mod.install(url, None, None, force=False)
    assert sorted(added) == ["alpha", "beta"]  # unsafe '../../escape' skipped
    assert (mod.SKILLS / "alpha" / "ref.md").exists()
    assert not (tmp_path / "escape").exists()

    mod.attach("writer", ["alpha"])
    mod.attach("writer", ["alpha", "beta"])  # idempotent merge
    text = (mod.AGENTS / "writer.md").read_text()
    assert text.count("  - alpha") == 1 and "  - beta" in text and text.endswith("Body stays.\n")

    (mod.SKILLS / "local-one").mkdir()
    (mod.SKILLS / "local-one" / "SKILL.md").write_text("---\nname: local-one\ndescription: mine\n---\n")
    mod.register_local_skills()
    mod.write_index()
    lock = json.loads(mod.LOCK.read_text())
    assert lock["local-one"]["repo"] == "local" and lock["alpha"]["repo"] == url
    index = mod.INDEX.read_text()
    assert "| `alpha` | writer |" in index and "`local-one`" in index


def test_same_name_from_other_repo_needs_force(tmp_path):
    mod = load(tmp_path)
    url = make_repo(tmp_path)
    mod.install(url, None, {"alpha"}, force=False)
    lock = json.loads(mod.LOCK.read_text())
    lock["alpha"]["repo"] = "https://example.com/other.git"
    mod.LOCK.write_text(json.dumps(lock))
    assert mod.install(url, None, {"alpha"}, force=False) == []
    assert mod.install(url, None, {"alpha"}, force=True) == ["alpha"]
