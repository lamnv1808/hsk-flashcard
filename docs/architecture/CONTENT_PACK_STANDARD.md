# CONTENT PACK STANDARD (Phase 0, proposed)

A content pack is a self-contained, versioned bundle of learning content plus the
rules the engine needs to present and test it. **HSK is the first implementation.**
Nothing here changes current HSK runtime data; this defines the target contract.

## 1. Pack manifest

```jsonc
{
  "packId": "hsk",                      // stable slug, unique
  "name": "HSK Tiếng Trung",
  "version": "1.0.0",                   // semver; bump on content change
  "provenance": {                        // import audit
    "source": "source_data/HSK1-HSK6.xlsx",
    "importer": "scripts/import_hsk_excel.py",
    "generatedAt": "2026-07-12",
    "idPolicy": "preserve-existing-by-(level,word); new = max+1"
  },
  "languages": { "prompt": "zh", "reading": "pinyin", "meaning": "vi", "audio": "zh-CN" },
  "capabilities": ["study", "test", "audio", "bookmarks", "notes", "analytics"],
  "display": {
    "readingLabel": "Pinyin",
    "frontReadingPreference": true,      // maps to showFrontPinyin
    "readingSystem": "pinyin"
  },
  "audioRules": {
    "speakFields": ["prompt", "example.prompt"],  // Chinese only
    "neverSpeak": ["reading", "meaning", "example.reading", "example.translation"],
    "lang": "zh-CN"
  },
  "testModes": [1,2,3,4,5,6],            // which MCQ types are valid for this pack
  "levels": [
    {"id":"HSK1","order":1},{"id":"HSK2","order":2},{"id":"HSK3","order":3},
    {"id":"HSK4","order":4},{"id":"HSK5","order":5},{"id":"HSK6","order":6}
  ],
  "decks": [],                            // optional sub-grouping
  "tags": [],
  "cardCount": 5002,
  "idRange": [1, 5002]
}
```

## 2. Card records
Cards satisfy the canonical `Card` in `DATA_CONTRACTS.md §8.1`. For HSK the pack's
build step maps the legacy `data.js` fields through the adapter (`DATA_CONTRACTS §9`).
Runtime today keeps the flat legacy shape; the pack manifest is *descriptive* until
the domain consumes canonical cards (a later phase).

## 3. Capabilities & test modes
- `capabilities` gate which features render for a pack (e.g., a pack with no
  `reading` hides pinyin UI; a pack without `audio` hides speech controls).
- `testModes` list restricts Test Mode generation to what makes sense for the pack's
  fields (a word/meaning-only pack would expose a subset).
- The engine must **degrade gracefully**: unknown/absent fields → feature hidden,
  never a crash.

## 4. Validation report (produced by the importer/loader)
```jsonc
{
  "packId": "hsk", "version": "1.0.0", "ok": true,
  "cards": 5002, "byLevel": {"HSK1":149,"HSK2":150,"HSK3":295,"HSK4":600,"HSK5":1295,"HSK6":2513},
  "idsUnique": true, "idsContiguous": true, "idRange": [1,5002],
  "missingRequiredFields": 0, "duplicateVisible": 0,
  "warnings": [], "errors": []
}
```
Validation rules: IDs unique; required fields per capability non-empty; declared
`languages`/`levels` consistent with data; `idPolicy` preserved existing IDs. A
failing report **blocks** writing generated output (matches the importer's current
fail-safe behavior).

## 5. HSK expressed as one pack (mapping summary)
`word→prompt(zh)`, `pinyin→reading(pinyin)`, `meaning→meaning(vi)`,
`example/examplePinyin/translation→example{prompt,reading,translation}`,
`level→level`, audio `zh-CN`, testModes all six, display frontReadingPreference =
current `showFrontPinyin`. This is exactly today's behavior, re-described in
pack terms — proving the standard is a faithful superset, not a change.

## 6. Multi-pack & multi-tenant notes (future)
- Card IDs are unique **within a pack**; the global join key becomes `(packId, cardId)`.
  For the single existing pack, `packId="hsk"` is injected and the legacy integer id
  is unchanged — no data migration.
- A client/tenant selects one or more packs via config (`DOMAIN_BOUNDARIES §4`).
- Progress rows gain an optional `pack_id` only when a second pack ships (an approved
  migration), defaulting existing rows to `"hsk"`.
