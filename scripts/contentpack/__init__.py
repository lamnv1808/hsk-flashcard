"""FlashEdu deterministic Content Pack build pipeline (Phase 24D).

Build-time tooling only. Nothing in this package is loaded by the runtime app,
and nothing here may write inside hsk_flashcard_app/.

Pipeline stages:
    source -> parse -> validate -> normalize -> resolve stable ids
           -> ContentPack v1 artifacts -> checksums -> QA reports
           -> registry handoff -> atomic publish

Dependencies: Python standard library, plus openpyxl for the .xlsx frontend.
No network access, no credentials, no content generation.
"""

# Recorded in QA metadata only. Deliberately NOT part of any content identity
# checksum: a tool refactor must never look like a content change.
BUILD_TOOL_VERSION = "24d.1"

# CSI (Canonical Source Intermediate) structural version. A bump here changes
# sourceChecksum for every pack, so it is a deliberate, reviewed act.
CSI_VERSION = 1

# Ledger structural version.
LEDGER_VERSION = 1

__all__ = ["BUILD_TOOL_VERSION", "CSI_VERSION", "LEDGER_VERSION"]
