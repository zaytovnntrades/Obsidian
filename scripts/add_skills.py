#!/usr/bin/env python3
"""Stack skills from any Git repo into this project's .claude/skills/ and wire them to agents.

    python3 scripts/add_skills.py https://github.com/obsidianmd/obsidian-skills.git
    python3 scripts/add_skills.py <repo-url> --only defuddle,knap --agent web-clipper
    python3 scripts/add_skills.py <repo-url> --ref v1.2.0          # pin a tag/branch
    python3 scripts/add_skills.py --update                          # re-pull every repo in the lock file
    python3 scripts/add_skills.py --list

Every folder containing a SKILL.md becomes .claude/skills/<name>/. Sources and commits are recorded in
.claude/skills/skills.lock.json and an index is written to .claude/skills/README.md, which the
research-desk orchestrator reads to decide which agent should use which skill.

Skills are instructions your agents will follow, so READ new ones before relying on them.
This script only copies files; it never runs anything from the cloned repo.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".claude" / "skills"
AGENTS = ROOT / ".claude" / "agents"
LOCK = SKILLS / "skills.lock.json"
INDEX = SKILLS / "README.md"
NAME_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    out: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t", "-")):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def load_lock() -> dict:
    return json.loads(LOCK.read_text()) if LOCK.exists() else {}


def save_lock(lock: dict) -> None:
    LOCK.write_text(json.dumps(dict(sorted(lock.items())), indent=2) + "\n")


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def install(url: str, ref: str | None, only: set[str] | None, force: bool) -> list[str]:
    lock = load_lock()
    added: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "repo"
        clone = ["clone", "--depth", "1", "-q"] + (["--branch", ref] if ref else []) + [url, str(dest)]
        git(*clone)
        commit = git("rev-parse", "HEAD", cwd=dest)
        for skill_md in sorted(dest.rglob("SKILL.md")):
            if ".git" in skill_md.parts:
                continue
            src_dir = skill_md.parent
            meta = frontmatter(skill_md.read_text(errors="replace"))
            name = meta.get("name") or src_dir.name
            if only and name not in only:
                continue
            if not NAME_OK.match(name):
                print(f"  skip {name!r}: unsafe skill name")
                continue
            prev = lock.get(name)
            if prev and prev.get("repo") not in (url, "local") and not force:
                print(f"  skip {name}: already installed from {prev['repo']} (use --force to replace)")
                continue
            if prev and prev.get("repo") == "local":
                print(f"  skip {name}: a local project skill already uses this name")
                continue
            target = SKILLS / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src_dir, target, ignore=shutil.ignore_patterns(".git"))
            executables = [str(p.relative_to(target)) for p in target.rglob("*") if p.is_file() and p.stat().st_mode & 0o111]
            lock[name] = {
                "repo": url,
                "ref": ref,
                "commit": commit,
                "path": str(src_dir.relative_to(dest)),
                "description": meta.get("description", "")[:300],
            }
            added.append(name)
            note = f"  (contains executable files: {', '.join(executables)} - review them)" if executables else ""
            print(f"  + {name}{note}")
    save_lock(lock)
    return added


def register_local_skills() -> None:
    """Skills written directly in .claude/skills/ (not from a repo) are tracked as 'local'."""
    lock = load_lock()
    for skill_md in SKILLS.glob("*/SKILL.md"):
        name = skill_md.parent.name
        if name not in lock:
            meta = frontmatter(skill_md.read_text(errors="replace"))
            lock[name] = {"repo": "local", "description": meta.get("description", "")[:300]}
    for name in [n for n, v in lock.items() if not (SKILLS / n / "SKILL.md").exists()]:
        del lock[name]
    save_lock(lock)


def attach(agent: str, names: list[str]) -> None:
    path = AGENTS / f"{agent}.md"
    if not path.exists():
        sys.exit(f"No agent at {path}. Existing: {', '.join(p.stem for p in AGENTS.glob('*.md'))}")
    text = path.read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        sys.exit(f"{path} has no frontmatter")
    fm = m.group(1)
    current: list[str] = []
    if "skills:" in fm:
        block = re.search(r"^skills:\s*\n((?:[ \t]+-[^\n]*\n?)*)", fm, re.M)
        current = re.findall(r"-\s+(\S+)", block.group(1)) if block else []
        fm = fm[: block.start()] + fm[block.end() :] if block else fm
    merged = list(dict.fromkeys(current + names))
    fm = fm.rstrip("\n") + "\nskills:\n" + "".join(f"  - {n}\n" for n in merged)
    path.write_text("---\n" + fm.rstrip("\n") + "\n---\n" + text[m.end() :])
    print(f"  {agent}: skills = {', '.join(merged)}")


def agent_skill_map() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in AGENTS.glob("*.md"):
        m = re.match(r"^---\s*\n(.*?)\n---", path.read_text(), re.S)
        block = re.search(r"^skills:\s*\n((?:[ \t]+-[^\n]*\n?)*)", m.group(1), re.M) if m else None
        for name in re.findall(r"-\s+(\S+)", block.group(1)) if block else []:
            result.setdefault(name, []).append(path.stem)
    return result


def write_index() -> None:
    lock = load_lock()
    used = agent_skill_map()
    lines = [
        "# Skill stack",
        "",
        "Generated by `scripts/add_skills.py`. Do not edit by hand.",
        "The research-desk orchestrator reads this table to route work to agents.",
        "",
        "| Skill | Preloaded by agents | Source | Description |",
        "|---|---|---|---|",
    ]
    for name, info in sorted(lock.items()):
        src = "local" if info["repo"] == "local" else f"{info['repo'].removesuffix('.git').split('github.com/')[-1]}@{info['commit'][:7]}"
        desc = info.get("description", "").replace("|", "\\|")
        lines.append(f"| `{name}` | {', '.join(used.get(name, [])) or '(none: any agent can load it on demand)'} | {src} | {desc} |")
    INDEX.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="Git URL of a repo containing SKILL.md folders")
    ap.add_argument("--ref", help="branch or tag to install")
    ap.add_argument("--only", help="comma-separated skill names to install")
    ap.add_argument("--agent", action="append", default=[], help="agent to preload the installed skills into (repeatable)")
    ap.add_argument("--force", action="store_true", help="replace same-named skills from another repo")
    ap.add_argument("--update", action="store_true", help="re-pull every repo in the lock file")
    ap.add_argument("--list", action="store_true", help="print the skill index")
    args = ap.parse_args()
    SKILLS.mkdir(parents=True, exist_ok=True)

    if args.list:
        register_local_skills()
        write_index()
        print(INDEX.read_text())
        return
    if args.update:
        repos = {(v["repo"], v.get("ref")) for v in load_lock().values() if v["repo"] != "local"}
        for url, ref in sorted(repos, key=lambda r: r[0]):
            print(f"Updating {url}")
            install(url, ref, None, force=False)
    elif args.url:
        print(f"Installing skills from {args.url}")
        added = install(args.url, args.ref, set(args.only.split(",")) if args.only else None, args.force)
        for agent in args.agent:
            attach(agent, added)
        if not added:
            print("  nothing installed")
    else:
        ap.print_help()
        return
    register_local_skills()
    write_index()
    print(f"Index: {INDEX.relative_to(ROOT)}  |  Review new skills before relying on them.")


if __name__ == "__main__":
    main()
