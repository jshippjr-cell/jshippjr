"""Channel-aware Respond button — picks the right reply channel + a prepared draft."""

from types import SimpleNamespace

from chordential_oia.outreach import respond_action

PLAN = SimpleNamespace(
    email_subject="Re: Original score",
    first_touch_message="Hi there, Chordential here…",
    linkedin_search_url="https://www.linkedin.com/search/results/people/?keywords=x",
)


def _row(**kw):
    base = {"source": "", "url": "", "contact_email": "", "contact_handle": "",
            "contact_linkedin": "", "need": "Original score"}
    base.update(kw)
    return base


def test_reddit_with_handle_builds_dm_compose():
    a = respond_action(_row(source="/r/gameDevClassifieds",
                            url="https://reddit.com/r/x/comments/abc/",
                            contact_handle="dev1"), PLAN)
    assert a["channel"] == "Reddit DM"
    assert a["url"].startswith("https://www.reddit.com/message/compose/?to=dev1")
    assert "message=" in a["url"] and a["opens_compose"] is True


def test_reddit_without_handle_opens_post():
    a = respond_action(_row(source="reddit",
                            url="https://reddit.com/r/x/comments/abc/"), PLAN)
    assert a["channel"] == "Reddit"
    assert a["url"] == "https://reddit.com/r/x/comments/abc/"
    assert a["opens_compose"] is False


def test_email_source_builds_mailto():
    a = respond_action(_row(source="productionhub",
                            contact_email="dana@buyer.com"), PLAN)
    assert a["channel"] == "Email"
    assert a["url"].startswith("mailto:dana@buyer.com?subject=")
    assert "body=" in a["url"] and a["opens_compose"] is True


def test_email_source_without_address_still_email():
    a = respond_action(_row(source="mandy"), PLAN)
    assert a["channel"] == "Email" and a["url"].startswith("mailto:?subject=")


def test_linkedin_source_opens_profile():
    a = respond_action(_row(source="linkedin",
                            contact_linkedin="https://linkedin.com/in/dana"), PLAN)
    assert a["channel"] == "LinkedIn"
    assert a["url"] == "https://linkedin.com/in/dana"


def test_unknown_source_with_url_opens_listing():
    a = respond_action(_row(source="behance", url="https://behance.net/job/1"), PLAN)
    assert a["channel"] == "Open source" and a["url"] == "https://behance.net/job/1"


def test_unknown_source_no_url_falls_back_to_email():
    a = respond_action(_row(source="unknown"), PLAN)
    assert a["channel"] == "Email" and a["url"].startswith("mailto:")
