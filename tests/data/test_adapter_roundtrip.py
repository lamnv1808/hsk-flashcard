"""Legacy<->canonical round-trip characterization (Phase 1). Pure Python.

Proves the PROTOTYPE adapter preserves every legacy field byte-for-byte across
legacy -> canonical -> legacy, for all 5,002 production cards and for edge-case
fixtures, and that optional canonical metadata never alters the legacy output.
Uses ordered key comparison so a reordered/renamed field is caught.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "support"))
from datajs import load_cards, emit, CARD_FIELDS
from legacy_card_adapter import to_canonical, to_legacy, round_trip, LEGACY_FIELDS

def identical(a, b):
    # ordered keys + equal values (byte-identical dict serialization)
    return list(a.keys()) == list(b.keys()) and all(a[k] == b[k] for k in a)

def main():
    fails = []
    cards = load_cards()

    # 1) every production card round-trips identically
    mismatches = 0
    first = None
    for c in cards:
        rt = round_trip(c)
        if not identical(c, rt):
            mismatches += 1
            if first is None:
                first = {"id": c["id"], "before": {k: c[k] for k in CARD_FIELDS},
                         "after": rt}
    if mismatches:
        fails.append(f"{mismatches} card(s) not byte-identical after round-trip; first={first}")

    # 2) canonical field mapping is complete (the 8 legacy fields are all reachable)
    if LEGACY_FIELDS != CARD_FIELDS:
        fails.append("adapter LEGACY_FIELDS drifted from data contract CARD_FIELDS")

    # 3) optional metadata (packId/audio/tags/extra/levelOrder) does NOT leak into legacy
    sample = cards[0]
    canon = to_canonical(sample, pack_id="acme", audio_lang="fr-FR")
    canon["tags"] = ["x"]; canon["extra"] = {"note": "y"}
    leg = to_legacy(canon)
    if list(leg.keys()) != CARD_FIELDS:
        fails.append(f"legacy output keys changed by metadata: {list(leg.keys())}")
    if any(k in leg for k in ("packId", "audio", "tags", "extra", "levelOrder")):
        fails.append("additive canonical metadata leaked into legacy output")
    if not identical(sample, leg):
        fails.append("legacy output changed when optional metadata present")

    # 4) edge-case fixtures (tone marks, unicode, punctuation, brackets in pinyin)
    fixtures = [
        {"id": 999001, "level": "HSK4", "word": "爱情", "pinyin": "ài qíng [ái tình]",
         "meaning": "tình yêu", "example": "他们的爱情很美好。",
         "examplePinyin": "Tāmen de àiqíng hěn měihǎo.", "translation": "Tình yêu của họ rất đẹp."},
        {"id": 999002, "level": "HSK6", "word": "哎哟", "pinyin": "āi yōu",
         "meaning": "ái chà", "example": "哎哟，这个问题真让人头疼。",
         "examplePinyin": "āiyō, zhège wèntí zhēn ràng rén tóuténg.",
         "translation": "Ôi chao, vấn đề này thật nhức đầu."},
    ]
    for fx in fixtures:
        if not identical(fx, round_trip(fx)):
            fails.append(f"fixture id={fx['id']} not byte-identical after round-trip")

    return emit("adapter_roundtrip", fails, {
        "cardsChecked": len(cards), "roundTripMismatches": mismatches,
        "metadataLeakSafe": True if not fails else None,
    })

if __name__ == "__main__":
    sys.exit(main())
