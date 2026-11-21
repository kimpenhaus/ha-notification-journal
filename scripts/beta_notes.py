"""Write the release notes of a beta tag in release-please's form: a block for it and one for each earlier beta of its
version, newest first, each with what changed since the tag before it (the beta before, else the release).

Usage: python3 scripts/beta_notes.py v0.5.0-beta.2 > notes.md (run in a clone with all tags). The sections and the
types they hold come from release-please-config.json, so a beta lists what its release will, in the same form.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")
SUBJECT = re.compile(r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<text>.+?)(?: \(#(?P<pr>\d+)\))?$")
BREAKING = "⚠ BREAKING CHANGES"
FOOTER = re.compile(r"^BREAKING[ -]CHANGE: (?P<note>.+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    subject: str
    body: str = ""


@dataclass(frozen=True, slots=True)
class Round:
    """A beta, the day it was tagged, and what changed since the tag before it."""

    tag: str
    previous: str | None
    date: str
    commits: list[Commit]


def rounds(tag: str, tags: list[str]) -> list[tuple[str, str | None]]:
    """This beta and each earlier beta of its version, newest first, each with the tag it is measured from: the beta
    before it, else the newest release below the version."""
    if (match := TAG.match(tag)) is None or match[4] is None:
        raise ValueError(f"not a beta tag: {tag}")
    version, number = tuple(map(int, match.groups()[:3])), int(match[4])
    betas, releases = [], []
    for other in tags:
        if (found := TAG.match(other)) is None:
            continue
        other_version = tuple(map(int, found.groups()[:3]))
        if found[4] is None and other_version < version:
            releases.append((other_version, other))
        elif found[4] is not None and other_version == version and int(found[4]) < number:
            betas.append((int(found[4]), other))
    chain = [tag, *(beta for _, beta in sorted(betas, reverse=True)), max(releases)[1] if releases else None]
    return list(pairwise(chain))


def sections(config: dict) -> dict[str, str]:
    """The visible changelog section of each commit type, in the order of the config."""
    entries = config["packages"]["."]["changelog-sections"]
    return {entry["type"]: entry["section"] for entry in entries if not entry.get("hidden")}


def notes(betas: list[Round], titles: dict[str, str], repo: str) -> str:
    """One block per beta, newest first, as release-please writes a release and CHANGELOG.md."""
    url = f"https://github.com/{repo}"
    return "\n".join(_block(beta, titles, url) for beta in betas)


def _block(beta: Round, titles: dict[str, str], url: str) -> str:
    version = beta.tag.removeprefix("v")
    if beta.previous is None:
        text = f"## {version} ({beta.date})\n"
    else:
        text = f"## [{version}]({url}/compare/{beta.previous}...{beta.tag}) ({beta.date})\n"
    grouped: dict[str, list[tuple[str, str]]] = {}
    for commit in beta.commits:
        if (match := SUBJECT.match(commit.subject)) is None:
            continue
        scope, subject, pr = match["scope"], match["text"], match["pr"]
        links = (f" ([#{pr}]({url}/issues/{pr}))" if pr else "") + f" ([{commit.sha[:7]}]({url}/commit/{commit.sha}))"
        prefix = f"**{scope}:** " if scope else ""
        footer = FOOTER.search(commit.body)
        if match["breaking"] or footer:
            note = footer["note"] if footer else subject
            grouped.setdefault(BREAKING, []).append(((scope or note).lower(), f"* {prefix}{note}{links}"))
        if (title := titles.get(match["type"])) is not None:
            grouped.setdefault(title, []).append(((scope or subject).lower(), f"* {prefix}{subject}{links}"))
    for title in (title for title in [BREAKING, *dict.fromkeys(titles.values())] if title in grouped):
        text += f"\n\n### {title}\n\n" + "\n".join(line for _, line in sorted(grouped[title])) + "\n"
    return text


def _git(*args: str) -> str:
    env = {**os.environ, "TZ": "UTC"}
    return subprocess.run(["git", *args], cwd=ROOT, env=env, check=True, capture_output=True, text=True).stdout


def _tagged(tag: str) -> str:
    """The day the tag was made, in UTC as release-please dates a release."""
    return _git("for-each-ref", "--format=%(creatordate:format-local:%Y-%m-%d)", f"refs/tags/{tag}").strip()


def _commits(previous: str | None, tag: str) -> list[Commit]:
    log = _git("log", "--format=%H%x1f%s%x1f%b%x1e", f"{previous}..{tag}" if previous else tag)
    return [Commit(*entry.strip("\n").split("\x1f", 2)) for entry in log.split("\x1e") if entry.strip()]


def main(tag: str) -> None:
    tags = _git("tag", "--list", "v*", "--merged", tag).split()
    betas = [Round(beta, previous, _tagged(beta), _commits(previous, beta)) for beta, previous in rounds(tag, tags)]
    config = json.loads((ROOT / "release-please-config.json").read_text())
    repo = os.environ.get("GITHUB_REPOSITORY", "kimpenhaus/ha-notification-journal")
    sys.stdout.write(notes(betas, sections(config), repo))


if __name__ == "__main__":
    main(sys.argv[1])
