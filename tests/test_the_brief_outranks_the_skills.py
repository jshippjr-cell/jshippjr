"""Twelve generic marketing skills were installed, and the brief still wins.

`marcosmodly/marketing-skill` (MIT, installed 2026-10-08) is competent, general
marketing tooling that knows nothing about this company. Every one of its skills reads
ONE file before producing anything — `references/brand-voice.md` — and ships it
UNCONFIGURED with placeholder defaults ("general B2B software buyers", "confident,
plain-spoken, a little dry"). That hook is the whole enforcement: configure it from the
brief and the skills comply by construction rather than by a future session remembering
to read a pointer.

So this file guards the hook. The failure it exists to prevent is quiet and plausible:
somebody runs the skills' own `marketing-setup`, which rewrites this file from a
conversation, and the four rules the founder struck his own copy over go back to being
things no marketing tool has ever heard of.

Each rule below is one he struck himself, and the test names the line it cost.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VOICE = ROOT / ".claude" / "marketing-kit" / "references" / "brand-voice.md"
BRIEF = ROOT / "docs" / "marketing" / "00-brief.md"
SKILLS = ROOT / ".claude" / "skills"

#: The twelve, by directory name.
INSTALLED = [
    "ad-copy-generator", "community-post-generator", "competitor-research",
    "content-calendar", "content-repurposer", "email-outreach", "email-sequence",
    "full-pipeline", "publish-pipeline", "seo-brief", "short-form-video",
    "visual-brief-generator",
]


def _voice() -> str:
    assert VOICE.exists(), "the file every skill reads first is gone"
    return VOICE.read_text()


def test_the_hook_is_configured_and_not_the_shipped_placeholder():
    """UNCONFIGURED makes a skill pause and ask the user to set preferences — which
    is a conversation that can go anywhere. Configured, it is the brief's deputy."""
    first = _voice().splitlines()[0]
    assert "MARKETING-SKILL:UNCONFIGURED" not in first, (
        "brand-voice.md is back to the shipped placeholder; the skills will onboard "
        "from a conversation instead of from the canon")
    assert "MARKETING-SKILL:CONFIGURED" in first


def test_it_names_the_brief_as_the_authority_over_itself():
    v = _voice()
    assert "docs/marketing/00-brief.md" in v, "the deputy does not name its authority"
    assert re.search(r"brief\s+wins", re.sub(r"\s+", " ", v), re.I), (
        "nothing in the file says which document wins when they differ")


@pytest.mark.parametrize("rule, cost", [
    # Each is a line the founder struck from his own copy, and why.
    ("Never define a word to the reader",
     '"Composed means written for this campaign" — teaching a producer their own word'),
    ("Never volunteer a weakness",
     '"Chordential has no paying client yet" on every surface, unprompted'),
    ("Never flatter the reader",
     '"I learn more from producers than from anyone" — false, and audible'),
    ("Never lift ourselves by lowering an adjacent craft",
     '"one of the few places left that will pay a composer properly"'),
])
def test_the_four_rules_of_restraint_survive(rule, cost):
    """No marketing tool ships with rules about what NOT to say, so these are the
    first to be lost and the last to be noticed."""
    assert rule in re.sub(r"\s+", " ", _voice()), f"lost: {rule} — it cost {cost}"


def test_money_is_split_by_reader_not_dropped():
    """The rule is not "never mention money". It is never to a BUYER, and published
    in full to a CREATOR, where the terms are the offer. A skill told only half of
    that gets the composer side wrong in the direction that loses composers."""
    # Whitespace-tolerant: these files are hand-wrapped at 88 columns and a phrase
    # that happens to straddle a line break is not a missing rule.
    v = re.sub(r"\s+", " ", _voice())
    assert re.search(r"[Nn]ever to a buyer", v), "the buyer half of the money rule is gone"
    assert re.search(r"[Ll]ifted for a creator", v), "the creator half is gone"


def test_machine_made_music_is_refused_out_loud():
    """Several of these skills offer to generate audio. This is the one refusal that
    would contradict the whole position, so declining silently is not enough."""
    v = re.sub(r"\s+", " ", _voice()).lower()
    assert "no machine-made music" in v
    assert "decline" in v, "a skill offering to generate a soundtrack is not told to refuse"


def test_the_installed_skills_still_read_the_hook():
    """If a skill stops reading brand-voice.md, configuring it protects nothing."""
    missing = [
        n for n in INSTALLED
        if "brand-voice.md" not in (SKILLS / n / "SKILL.md").read_text()
    ]
    assert not missing, f"these no longer read the voice config: {missing}"


def test_no_skill_still_hunts_for_a_plugin_root_that_does_not_exist():
    """They were installed as repo skills, not as a plugin, so every
    ${CLAUDE_PLUGIN_ROOT} path was rewritten to a real one. A re-copy from upstream
    would reintroduce paths that resolve to nothing and fail silently."""
    bad = []
    for n in INSTALLED:
        text = (SKILLS / n / "SKILL.md").read_text()
        if "${CLAUDE_PLUGIN_ROOT}" in text:
            bad.append(n)
    assert not bad, f"unresolvable plugin paths are back in: {bad}"


def test_the_skills_are_committed_rather_than_left_on_a_disk_that_is_rebuilt():
    """The container is rebuilt from the repository every session, so a skill that is
    only on local disk is a skill that is gone next time. `.gitignore` used to ignore
    this whole directory on the reasoning that skills are "kept on local disk"."""
    ignore = (ROOT / ".gitignore").read_text()
    for line in ignore.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert stripped not in (".claude/skills/", ".claude/skills"), (
            "the skills directory is ignored again — anything added to it from now on "
            "will vanish with the container")


def test_the_brief_itself_is_still_there_to_win():
    assert BRIEF.exists(), "the authority this all defers to does not exist"
    b = BRIEF.read_text()
    assert "## 7. The refusals" in b
    assert "machine-made music" in b
