"""Tests of the notes of a beta release."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("beta_notes", ROOT / "scripts" / "beta_notes.py")
beta_notes = importlib.util.module_from_spec(_spec)
sys.modules["beta_notes"] = beta_notes
_spec.loader.exec_module(beta_notes)

TAGS = ["v0.3.1", "v0.4.0-beta.1", "v0.4.0-beta.2", "v0.4.0", "v0.5.0-beta.1", "v0.5.0-beta.2", "v0.10.0"]
TITLES = beta_notes.sections(json.loads((ROOT / "release-please-config.json").read_text()))
REPO = "owner/repo"


def _commit(subject: str, body: str = "") -> object:
    return beta_notes.Commit(sha="a" * 40, subject=subject, body=body)


@pytest.mark.parametrize(
    ("tag", "previous"),
    [
        ("v0.5.0-beta.1", "v0.4.0"),
        ("v0.5.0-beta.2", "v0.5.0-beta.1"),
        ("v0.5.0-beta.3", "v0.5.0-beta.2"),
        ("v0.4.0-beta.1", "v0.3.1"),
        ("v0.11.0-beta.1", "v0.10.0"),
        ("v0.1.0-beta.1", None),
    ],
)
def test_a_beta_is_measured_from_the_beta_or_release_before(tag: str, previous: str | None) -> None:
    assert beta_notes.previous_tag(tag, TAGS) == previous


def test_a_release_tag_has_no_beta_notes() -> None:
    with pytest.raises(ValueError):
        beta_notes.previous_tag("v0.5.0", TAGS)


def test_every_earlier_beta_of_the_version_is_listed_back_to_the_release() -> None:
    assert beta_notes.rounds("v0.5.0-beta.3", TAGS) == [
        ("v0.5.0-beta.3", "v0.5.0-beta.2"),
        ("v0.5.0-beta.2", "v0.5.0-beta.1"),
        ("v0.5.0-beta.1", "v0.4.0"),
    ]


def test_the_notes_have_the_form_of_a_release_by_release_please() -> None:
    commits = [
        _commit("fix(panel): catch up after the connection returns (#93)"),
        _commit("chore(deps): update renovate (#91)"),
        _commit("feat(store): keep counts (#90)"),
        _commit("feat: drop the old api (#89)", body="BREAKING CHANGE: the old api is gone"),
        _commit("not a conventional subject"),
    ]

    text = beta_notes.notes([beta_notes.Round("v0.5.0-beta.1", "v0.4.0", "2026-11-21", commits)], TITLES, REPO)

    url = "https://github.com/owner/repo"
    assert text.startswith(
        f"## [0.5.0-beta.1]({url}/compare/v0.4.0...v0.5.0-beta.1) (2026-11-21)\n\n\n### ⚠ BREAKING CHANGES\n\n"
    )
    assert f"* **store:** keep counts ([#90]({url}/issues/90)) ([aaaaaaa]({url}/commit/{'a' * 40}))" in text
    assert "renovate" not in text
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings[1:] == ["### ⚠ BREAKING CHANGES", "### New", "### Fixed"]


def test_a_later_beta_lists_the_earlier_ones_below_as_release_please_lists_versions() -> None:
    betas = [
        beta_notes.Round("v0.5.0-beta.2", "v0.5.0-beta.1", "2026-11-22", [_commit("fix(panel): second (#2)")]),
        beta_notes.Round("v0.5.0-beta.1", "v0.4.0", "2026-11-21", [_commit("feat(store): first (#1)")]),
    ]

    text = beta_notes.notes(betas, TITLES, REPO)

    headings = [line.split("](")[0] for line in text.splitlines() if line.startswith("#")]
    assert headings == ["## [0.5.0-beta.2", "### Fixed", "## [0.5.0-beta.1", "### New"]
    assert "(#2)" not in text and text.index("second") < text.index("first")
    assert "\n\n## [0.5.0-beta.1]" in text


def test_a_beta_without_notable_changes_has_its_heading_only() -> None:
    text = beta_notes.notes(
        [beta_notes.Round("v0.5.0-beta.1", "v0.4.0", "2026-11-21", [_commit("chore: tidy (#1)")])], TITLES, REPO
    )

    assert text.count("\n") == 1
