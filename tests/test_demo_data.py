from rating import CARD_FIELDS
from storage import load_demo_card, load_drafts


def test_every_demo_draft_has_editable_seed_card():
    drafts = load_drafts()
    assert len(drafts) >= 5
    for draft in drafts:
        card = load_demo_card(draft["demo_card_id"])
        assert card["title"]
        assert card["context"]
        assert card["need"]
        assert all(field in card for field in CARD_FIELDS)
