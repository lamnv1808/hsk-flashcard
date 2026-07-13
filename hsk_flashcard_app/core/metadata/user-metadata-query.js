/* ============================================================
 *  core/metadata/user-metadata-query.js  (FlashEdu — Phase 7)
 *  Read-only USER-METADATA read seam for bookmarks and notes.
 *  Bookmarks and notes share ONE user-scoped lifecycle (both live
 *  inside the per-user settings blob), so they share ONE cohesive
 *  read boundary rather than two fragmented modules. Future WRITE
 *  repositories (BookmarkRepository / NoteRepository) are deferred.
 *
 *  STRICT READ-ONLY CONTRACT:
 *    - never mutates bookmarks/notes/settings/progress/cards/source arrays
 *    - never writes localStorage, marks dirty, enqueues sync, calls Supabase
 *    - never creates/removes metadata, never cleans up invalid entries
 *    - no DOM, no audio, no network
 *
 *  Behavior is frozen to the CURRENT runtime (metadata.js + insights.js).
 *  Card resolution goes through CardRepository; the query hardcodes NO
 *  HSK/Chinese card fields (word/pinyin/meaning) — bookmark SEARCH stays
 *  in presentation. Only generic card.level filtering lives here.
 * ============================================================ */
(function (NS) {
  "use strict";

  // deps:
  //   cardRepository   - Phase 3 repo (getById / getManyByIds)
  //   metadataProvider - () => the live metadata container (the settings blob:
  //                      { bookmarks:int[], notes:{ "<id>":string } , ... }).
  //                      Re-read every call so cloud-pull reassignment / account
  //                      switch are observed (no stale capture).
  function createUserMetadataQuery(deps) {
    deps = deps || {};
    var repo = deps.cardRepository;
    var read = (typeof deps.metadataProvider === "function")
      ? deps.metadataProvider
      : function () { return deps.metadataProvider; };

    function meta() {
      var m = read();
      return (m && typeof m === "object") ? m : {};
    }

    // --- bookmarks (settings.bookmarks: int[], insertion order) ---
    // Guard mirrors metadata.js bookmarks(); returns a COPY so callers can't
    // mutate the source array (writes go through the existing metadata path).
    function getBookmarkIds() {
      var b = meta().bookmarks;
      return Array.isArray(b) ? b.slice() : [];
    }
    // strict indexOf membership, same as metadata.js isBookmarked()
    function isBookmarked(cardId) {
      var b = meta().bookmarks;
      return Array.isArray(b) && b.indexOf(cardId) >= 0;
    }
    // Resolve bookmark ids to cards via the repo: requested (insertion) order,
    // keeps duplicates, skips missing — exactly insights.bookmarkCards().
    // Optional generic level filter (card.level); no HSK field assumptions.
    function getBookmarkedCards(options) {
      var cards = repo.getManyByIds(getBookmarkIds().map(Number));
      var level = options && options.level;
      if (level && level !== "all") {
        cards = cards.filter(function (c) { return c.level === level; });
      }
      return cards;
    }
    function countBookmarks(options) { return getBookmarkedCards(options).length; }

    // --- notes (settings.notes: { "<id>": string }) ---
    // Guard mirrors metadata.js notesMap(); COPY (shallow) so the source object
    // is never exposed for mutation.
    function getNotesMap() {
      var n = meta().notes;
      if (!n || typeof n !== "object") return {};
      var out = {}, k;
      for (k in n) if (Object.prototype.hasOwnProperty.call(n, k)) out[k] = n[k];
      return out;
    }
    // getNote/hasNote mirror metadata.js exactly (number id coerces to string key).
    function getNote(cardId) {
      var n = meta().notes;
      var v = (n && typeof n === "object") ? n[cardId] : undefined;
      return v ? String(v) : "";
    }
    function hasNote(cardId) {
      return String(getNote(cardId) == null ? "" : getNote(cardId)).trim() !== "";
    }

    // Cohesive per-card read model.
    function getCardMetadata(cardId) {
      return {
        cardId: cardId,
        bookmarked: isBookmarked(cardId),
        hasNote: hasNote(cardId),
        note: getNote(cardId)
      };
    }

    return {
      isBookmarked: isBookmarked,
      getBookmarkIds: getBookmarkIds,
      getBookmarkedCards: getBookmarkedCards,
      countBookmarks: countBookmarks,
      hasNote: hasNote,
      getNote: getNote,
      getNotesMap: getNotesMap,
      getCardMetadata: getCardMetadata
    };
  }

  NS.createUserMetadataQuery = createUserMetadataQuery;
  // Shared instance. Bookmarks/notes are nested in the settings blob, so the
  // provider is exactly metadata.js's S(): the active account's live settings.
  NS.userMetadata = createUserMetadataQuery({
    cardRepository: NS.cards,
    metadataProvider: function () { return (window.HSK_APP && window.HSK_APP.getSettings()) || {}; }
  });

})(window.HSKUtil = window.HSKUtil || {});
