/* ============================================================
 *  core/util/shuffle.js — authoritative Fisher–Yates shuffle.
 *  Pure/deterministic given the injected random fn. No DOM/storage/state.
 *  Preserves the EXACT algorithm previously inlined in test.js:
 *      for (i = n-1; i>0; i--) { j = (rnd() * (i+1)) | 0; swap(i, j); }
 *  Two explicit variants preserve each call site's copy/in-place intent.
 *  NOTE: app.js's `sort(()=>Math.random()-.5)` is a DIFFERENT algorithm and
 *  is intentionally NOT migrated here (would change randomness distribution).
 * ============================================================ */
(function () {
  "use strict";
  var NS = (window.HSKUtil = window.HSKUtil || {});

  // Shuffle IN PLACE; returns the same array reference. rnd defaults to Math.random.
  function shuffleInPlace(arr, rnd) {
    rnd = rnd || Math.random;
    for (var i = arr.length - 1; i > 0; i--) {
      var j = (rnd() * (i + 1)) | 0;
      var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }

  // Shuffle a COPY; the input array is not mutated.
  function shuffledCopy(arr, rnd) {
    return shuffleInPlace((arr || []).slice(), rnd);
  }

  NS.shuffle = { shuffleInPlace: shuffleInPlace, shuffledCopy: shuffledCopy };
})();
