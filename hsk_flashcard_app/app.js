
const cards = window.HSK_CARDS || [];
const cardRepo = window.HSKUtil.cards;   // read-only CardRepository over the same source (built once)
// Deck identity/order comes from the active ContentPack (Phase 11); the pack derives
// its decks from the cards once at construction, so this is exactly equivalent to the
// previous levelsFromCards(cards) — HSK1..HSK6 (and future HSK7…) with no code change.
const LEVELS = window.HSKUtil.contentPack.getDeckIds();
// Storage keys: namespaced per logged-in account when cloud accounts are active,
// otherwise the original global keys (unchanged local-only behavior). Read through the
// read-only AuthContextQuery (Phase 15) — exactly equivalent to the previous
// `HSK_AUTH.progressKey || base` bootstrap selection.
const authContext = window.HSKUtil.authContext;
const stateKey = authContext.getProgressKey();
const settingsKey = authContext.getSettingsKey();
let progress = JSON.parse(localStorage.getItem(stateKey) || "{}");
let settings = JSON.parse(localStorage.getItem(settingsKey) || "{}");
// Read-only settings accessor (Phase 4). Bound to a provider over the LIVE
// `settings` binding, so it observes reloadState() reassignments after a cloud
// pull and is usable during the first renderHome() (before HSK_APP exists).
// It never writes/marks-dirty; the existing write path (saveSettings) is unchanged.
const settingsRepo = window.HSKUtil.createSettingsRepository(() => settings);
// Read-only progress read seam (Phase 8) over the live `progress` binding: freezes
// the getCardState default-state contract. Injected into the read-only queries below
// so they no longer read the raw progress object. The write path (gradeCard/save/
// getCardState) is unchanged and does NOT go through this repository.
const progressRepo = window.HSKUtil.createProgressRepository({ progressProvider: () => progress });
// Write-capable grading boundary (Phase 12). Owns the per-card grade transaction only:
// read current state (via progressRepo) -> pure SRS math (HSKUtil.srsScheduler.computeNext,
// Phase 18) -> assign the live progress row -> save() -> HSKSync.markDirty(). Writes to the
// live `progress` binding, so cloud-pull reassignment / account switch are honored.
const progressWriter = window.HSKUtil.createProgressWriter({
  progressProvider: () => progress,
  progressRepository: progressRepo,
  srsCalculator: window.HSKUtil.srsScheduler.computeNext,   // pure SRS math (Phase 18)
  save: save,
  markDirty: (id) => { if(window.HSKSync) HSKSync.markDirty(id); },
  dateProvider: () => new Date(),
  // reset transaction (Phase 14): replaceProgress reassigns the live `progress` binding
  // (so every read consumer observes the new empty object); onReset is the existing
  // sync-guarded callback. Both stay owned by the controller; the writer just orchestrates.
  replaceProgress: (next) => { progress = next; },
  onReset: () => { if(window.HSKSync) HSKSync.onReset(); }
});
// Read-only Study session card-SELECTION seam (Phase 5). Owns no session state:
// it only reads cards/progress/date/random and returns the card list to seed a
// session. Progress is read through the ProgressRepository so cloud-pull reassignment
// and account switches are observed (no stale progress). today() is hoisted below.
const sessionQuery = window.HSKUtil.createStudySessionQuery({
  cardRepository: cardRepo,
  progressRepository: progressRepo,
  dateProvider: () => today(),
  randomProvider: Math.random
});
// Read-only analytics/dashboard read-model seam (Phase 6). Reads progress via the
// ProgressRepository (live `progress` binding) so it works during the first
// renderHome() (before HSK_APP) and observes reloadState(). Returns data only.
const analytics = window.HSKUtil.createAnalyticsQuery({
  cardRepository: cardRepo,
  progressRepository: progressRepo,
  settingsRepository: settingsRepo,
  dailyCountsProvider: () => (window.HSKMeta && window.HSKMeta.dailyCounts()) || {},
  dateProvider: () => new Date()
});
// Read-only Study session/card read-model engine (Phase 16): composes the seams to
// build sessions (delegating to StudySessionQuery) and describe session/card read
// models. Owns NO mutable state and no DOM — app.js still owns session/current/flip/
// snapshots/rendering. today() is hoisted below.
const studyEngine = window.HSKUtil.createStudySessionEngine({
  contentPack: window.HSKUtil.contentPack,
  cardRepository: cardRepo,
  progressRepository: progressRepo,
  settingsRepository: settingsRepo,
  studySessionQuery: sessionQuery,
  userMetadataQuery: window.HSKUtil.userMetadata,
  dateProvider: () => today()
});
let session = [], selectedLevels = settings.selectedLevels || ["HSK1"];
// Authoritative mutable Study session state (Phase 20). The pure StudySessionStateMachine
// owns cardIds/currentIndex/flipped/gradesByIndex/status + all navigation transitions;
// app.js keeps `session` (resolved card objects, same order as cardIds) as the render
// source and `snapshots` as opaque undo payloads.
const sessionSM = window.HSKUtil.createStudySessionStateMachine();
let sessionState = sessionSM.createInitialState();
let snapshots = {};   // in-memory per-session-index undo history for SRS (never persisted)
// Phase 21: transient origin of the current session, used ONLY to gate the completion-screen
// UX ("Học tiếp" continues a level-based session with the same levels). Never persisted, never
// synced, never part of sessionState / the state machine / cloud payloads.
let studySource = null;   // null | {type:"levels", levels:string[]} | {type:"explicit"}

const $ = id => document.getElementById(id);

// Allowed speech speeds; any other/legacy value safely falls back to 1x.
const SPEECH_RATES = [0.5, 0.75, 1, 1.25, 1.5];
function normSpeechRate(v){ v = Number(v); return SPEECH_RATES.includes(v) ? v : 1; }

/* ---------- Speech (browser SpeechSynthesis) ---------- */
const speech = {
  supported: typeof window !== "undefined" && "speechSynthesis" in window,
  voices: [],
  rate: normSpeechRate(settings.speechRate),
  token: 0
};
// Language prefixes we accept. Android often reports Mandarin as "cmn-*".
const LANG_ALIASES = { zh: ["zh", "cmn"], vi: ["vi"] };

function loadVoices(){
  if(!speech.supported) return;
  speech.voices = window.speechSynthesis.getVoices() || [];
}
if(speech.supported){
  loadVoices();
  window.speechSynthesis.onvoiceschanged = loadVoices;
}

function pickVoice(lang){
  if(!speech.supported) return null;
  if(!speech.voices.length) loadVoices();
  const base = lang.split("-")[0].toLowerCase();
  const prefixes = LANG_ALIASES[base] || [base];
  const norm = v => (v.lang || "").toLowerCase().replace("_", "-");
  const matches = speech.voices.filter(v => prefixes.some(p => norm(v).startsWith(p)));
  if(!matches.length) return null;
  const exact = matches.filter(v => norm(v) === lang.toLowerCase());
  const pool = exact.length ? exact : matches;
  return pool.find(v => /google/i.test(v.name))
    || pool.find(v => /microsoft/i.test(v.name))
    || pool[0];
}

// Speaking indicator: highlight the element being read + toggle body.speaking.
function setSpeaking(on, el){
  document.body.classList.toggle("speaking", !!on);
  document.querySelectorAll(".reading").forEach(n => n.classList.remove("reading"));
  if(on && el) el.classList.add("reading");
}

function stopSpeech(){
  speech.token++;               // invalidates any pending onend/pause callbacks
  setSpeaking(false);
  if(speech.supported) window.speechSynthesis.cancel();
}

// items: [{text, lang, el?, pauseAfter?}] spoken in order with optional pause between.
// First utterance is queued synchronously so iOS keeps the user-gesture activation.
function speak(items){
  if(!speech.supported) return;
  const list = items.filter(i => i && i.text);
  stopSpeech();                 // cancel current + bump token
  if(!list.length) return;
  const myToken = speech.token;
  let i = 0;
  const step = () => {
    if(myToken !== speech.token) return;        // superseded by a newer request/stop
    if(i >= list.length){ setSpeaking(false); return; }
    const item = list[i++];
    const u = new SpeechSynthesisUtterance(item.text);
    u.lang = item.lang;
    u.rate = speech.rate;
    const v = pickVoice(item.lang);
    if(v) u.voice = v;
    u.onstart = () => { if(myToken === speech.token) setSpeaking(true, item.el || null); };
    u.onend = () => {
      if(myToken !== speech.token) return;
      if(item.pauseAfter) setTimeout(step, item.pauseAfter); else step();
    };
    u.onerror = () => { if(myToken === speech.token) step(); };
    window.speechSynthesis.speak(u);
  };
  setSpeaking(true, list[0].el || null);        // immediate visual feedback
  step();
}

function currentCard(){ return session[sessionState.currentIndex]; }
function speakWord(){ const c = currentCard(); if(c) speak([{ text: c.word, lang: "zh-CN", el: $("word") }]); }       // never reads pinyin
function speakExample(){ const c = currentCard(); if(c) speak([{ text: c.example, lang: "zh-CN", el: $("example") }]); } // never reads pinyin
// Read All: Chinese word -> 500ms pause -> Chinese example. No pinyin, no Vietnamese by default.
function readAll(){
  const c = currentCard(); if(!c) return;
  speak([
    { text: c.word, lang: "zh-CN", el: $("word"), pauseAfter: 500 },
    { text: c.example, lang: "zh-CN", el: $("example") }
  ]);
}
const views = ["homeView","studyView","completeView"];
function showView(id){
  views.forEach(v => $(v).classList.toggle("active", v===id));
  document.body.classList.toggle("studying", id==="studyView");  // enables one-screen mobile layout
}
function today(){ return new Date().toISOString().slice(0,10); }
function getCardState(id){ return progress[id] || {due: today(), interval:0, reps:0, correct:0, attempts:0}; }
function save(){ localStorage.setItem(stateKey, JSON.stringify(progress)); }
function saveSettings(){ localStorage.setItem(settingsKey, JSON.stringify(settings)); if(window.HSKSync) HSKSync.onSettingsChanged(); }
function dueCards(levels){
  const now=today();
  return cards.filter(c=>levels.includes(c.level) && getCardState(c.id).due<=now);
}
function levelCards(level){ return cardRepo.getByLevel(level); }

function renderLevelPicker(){
  const wrap=$("levelPicker"); wrap.innerHTML="";
  LEVELS.forEach(level=>{
    const btn=document.createElement("button");
    btn.className="level-chip"+(selectedLevels.includes(level)?" active":"");
    btn.textContent=level;
    btn.onclick=()=>{
      if(selectedLevels.includes(level)){
        if(selectedLevels.length===1) return;
        selectedLevels=selectedLevels.filter(x=>x!==level);
      } else selectedLevels.push(level);
      selectedLevels.sort();
      settings.selectedLevels=selectedLevels; saveSettings();
      renderLevelPicker();
    };
    wrap.appendChild(btn);
  });
}

function renderHome(){
  renderLevelPicker();
  $("sessionSize").value=settingsRepo.getSessionSize();
  $("speechRate").value=String(settingsRepo.getSpeechRate());
  $("autoReadWord").checked=settingsRepo.getAutoReadWordEnabled();
  $("autoReadExample").checked=settingsRepo.getAutoReadExampleEnabled();
  $("showFrontPinyin").checked=settingsRepo.getFrontPinyinEnabled();   // default on
  $("totalWords").textContent=cardRepo.count().toLocaleString("vi-VN");   // total vocab count, automatic
  const grid=$("deckGrid"); grid.innerHTML="";
  // Read-only analytics (Phase 6): per-level {total,learned,due,pct}. DOM stays here.
  analytics.getLevelSummary(LEVELS).forEach(({level,total,learned,due,pct})=>{
    const btn=document.createElement("button");
    btn.className="deck-card";
    btn.innerHTML=`<div class="deck-level">${level}</div><div class="deck-count">${total} từ · ${due} cần ôn</div><div class="deck-progress"><span style="width:${pct}%"></span></div><div class="deck-meta"><span>Đã học ${learned}</span><span>${pct}%</span></div>`;
    btn.onclick=()=>{ selectedLevels=[level]; settings.selectedLevels=selectedLevels; saveSettings(); renderLevelPicker(); };
    grid.appendChild(btn);
  });
  const summary=analytics.getHomeSummary(LEVELS);
  $("learnedStat").textContent=summary.learned;
  $("retentionStat").textContent=summary.retentionText;
  $("streakStat").textContent=settingsRepo.getStreak();
  $("dueCount").textContent=summary.dueCount;
  renderDailyGoal();
}

// Phase 22A daily goal (additive, display-only). "Today learned" = unique cards graded during
// the current LOCAL day (existing semantics, unchanged). Normally read through HSKMeta (the
// locked source); metadata.js loads AFTER app.js, so before it is ready we read the SAME
// underlying data (settings.dailyCounts keyed by the local day) so the first Home paint isn't
// wrongly 0 — identical value, identical day-key, no semantic change.
function dailyLearnedToday(){
  if(window.HSKMeta) return HSKMeta.dailyCounts()[HSKMeta.localDay()] || 0;
  const dc=(settings && settings.dailyCounts) || {};
  return dc[window.HSKUtil.date.localDay()] || 0;
}
// Pure read model shared by Home and the completion screen (no writes / storage / mutation).
function dailyGoalModel(){
  const learned=dailyLearnedToday();
  const goal=settingsRepo.getDailyGoal();
  const percent=Math.min(100, Math.round(learned/goal*100));   // goal is always >=10
  return { learned, goal, percent, reached: learned>=goal };
}
// Render-only: reflect the current goal + today's progress on Home. Never writes settings.
function renderDailyGoal(){
  const dg=dailyGoalModel();
  $("dailyGoalSelect").value=String(dg.goal);
  $("dailyGoalText").textContent=`${dg.learned}/${dg.goal} thẻ`;
  $("dailyGoalBarFill").style.width=dg.percent+"%";
  const bar=$("dailyGoalBar");
  bar.setAttribute("aria-valuemax",String(dg.goal));
  bar.setAttribute("aria-valuenow",String(dg.learned));
}

function updateStreak(){
  const d=today(), last=settings.lastStudy;
  if(last===d) return;
  const y=new Date(); y.setDate(y.getDate()-1);
  settings.streak = last===y.toISOString().slice(0,10) ? (settings.streak||0)+1 : 1;
  settings.lastStudy=d; saveSettings();
}

function startStudy(levels){
  studySource={ type:"levels", levels:levels.slice() };   // Phase 21: completion-UX gating only
  const sizeSetting=$("sessionSize").value;
  settings.sessionSize=sizeSetting; settings.selectedLevels=levels; saveSettings();

  // Read-only construction via StudySessionEngine (Phase 16; delegates to StudySessionQuery
  // Phase 5: due -> fresh(not-in-due) -> random fallback). app.js still owns the mutable
  // session state, streak write, view + first render.
  session=studyEngine.buildSession({ levels, sessionSize: sizeSetting }).cards;

  sessionState=sessionSM.startSession({ cardIds: session.map(c=>c.id) });   // currentIndex 0, flipped false, no grades
  snapshots={}; updateStreak(); showView("studyView"); renderCard();
}

// Vocab pinyin (column C): shown on the FRONT by default; when the setting is off it
// moves to the back (above the meaning). Never both sides; example pinyin is untouched.
function applyPinyinDisplay(){
  const showFP = settingsRepo.getFrontPinyinEnabled();   // undefined => true (existing users unchanged)
  $("pinyin").style.display = showFP ? "" : "none";
  $("backWordBlock").style.display = showFP ? "none" : "";
  $("flashcard").classList.toggle("no-front-pinyin", !showFP);  // lets CSS fit the denser back on mobile
}

function renderCard(){
  if(sessionState.currentIndex>=session.length) return finishSession();
  const c=session[sessionState.currentIndex];
  const fc=$("flashcard");
  // P0 answer-leak fix: reset the flip WITHOUT the un-flip animation, so the back
  // face never rotates through a viewer-facing angle while it already holds the
  // next card's answer. Disable the face transition, drop .flipped + write the new
  // content on the front, force a reflow so it applies instantly, then re-enable the
  // transition for user-initiated flips.
  fc.classList.add("no-flip-anim");
  // sessionState.flipped is already false here (every path into renderCard goes through a
  // flipped=false transition: start/grade/skip/prev/shuffle). The DOM reset below is the
  // visual P0 answer-leak guard and is unchanged.
  fc.classList.remove("flipped");
  $("ratingArea").classList.add("hidden");
  $("nextBtn").classList.add("hidden");
  $("logicPanel").classList.add("hidden");
  $("sheetBackdrop").classList.add("hidden");
  $("flipHint").textContent="Bấm vào thẻ để lật";
  // Read-only session description (Phase 16). app.js still formats the DOM below.
  const desc=studyEngine.describeSession({ cards: session, currentIndex: sessionState.currentIndex });
  $("studyLevel").textContent=desc.deckLabel;
  $("cardIndex").textContent=desc.currentNumber; $("cardTotal").textContent=desc.total;
  $("progressBar").style.width=desc.progressPct+"%";
  // Card presentation read model (Phase 17). `front` carries only the prompt (answer-leak
  // safe) and maps to the FRONT-face elements; `back` maps to the (CSS-hidden) BACK face.
  // app.js still owns the DOM writes, flip-reset animation guard and audio execution.
  const m=studyEngine.describeCard({ card: c, flipped: false });
  $("levelBadge").textContent=m.deckId; $("word").textContent=m.front.primary; $("pinyin").textContent=m.front.pronunciation;
  $("meaning").textContent=m.back.definition; $("example").textContent=m.back.example; $("examplePinyin").textContent=m.back.examplePronunciation; $("translation").textContent=m.back.translation;
  // Front vocab pinyin (column C) shows on the front by default; when disabled it moves to the back.
  $("backWord").textContent=m.back.primary; $("backPinyin").textContent=m.back.pronunciation;
  applyPinyinDisplay();
  if(window.HSKMeta) HSKMeta.syncCard();   // bookmark state + hide note zone (front)
  void fc.offsetWidth;                     // force reflow: front + new content painted with no animation
  fc.classList.remove("no-flip-anim");     // restore the flip animation for the next user flip
  $("flashcard").setAttribute("aria-label",`Thẻ ${sessionState.currentIndex+1}/${session.length}. Từ: ${m.front.primary}. Bấm hoặc nhấn Space để xem nghĩa.`);
  $("srStatus").textContent=`Thẻ ${sessionState.currentIndex+1} trên ${session.length}. ${m.deckId}: ${m.front.primary}.`;
  stopSpeech();                       // always stop audio when the card changes
  if(m.autoReadWord) speakWord();
  $("flashcard").focus({preventScroll:true});   // keep keyboard focus without scroll jumps
}

function flipCard(){
  sessionState=sessionSM.flip(sessionState);   // pure toggle; app.js applies the DOM/audio below
  const flipped=sessionState.flipped;
  $("flashcard").classList.toggle("flipped",flipped);
  $("ratingArea").classList.toggle("hidden",!flipped);
  $("nextBtn").classList.toggle("hidden",!flipped);
  $("flipHint").textContent=flipped?"Chọn mức độ nhớ, hoặc Next để bỏ qua chấm điểm.":"Bấm vào thẻ để lật";
  const c=currentCard();
  if(c){
    $("flashcard").setAttribute("aria-label",flipped?`Đáp án. Nghĩa: ${c.meaning}. Bấm để lật lại.`:`Từ: ${c.word}. Bấm để xem nghĩa.`);
    $("srStatus").textContent=flipped?`Nghĩa: ${c.meaning}.`:`Từ: ${c.word}.`;
  }
  if(flipped){ stopSpeech(); if(settingsRepo.getAutoReadExampleEnabled()) speakExample(); } else stopSpeech();
  if(window.HSKMeta) HSKMeta.onFlip(flipped);   // note zone shows only on the back side
}

// Per-session-index undo history so revisiting a card can't double-count SRS.
function captureSnapshot(index,id){
  const k="i"+index;
  if(!(k in snapshots)){
    const had=Object.prototype.hasOwnProperty.call(progress,id);
    snapshots[k]={id,had,state:had?JSON.parse(JSON.stringify(progress[id])):null};
  }
}
function revertSnapshot(index){
  const snap=snapshots["i"+index];
  if(!snap) return;
  if(snap.had) progress[snap.id]=JSON.parse(JSON.stringify(snap.state));
  else delete progress[snap.id];
}

// SRS next-state math now lives in core/srs/scheduler.js (Phase 18) and is injected into
// ProgressWriter as srsCalculator above. app.js no longer owns any SRS formula.

function gradeCard(grade){
  if(!sessionState.flipped) return;   // guard: only grade a flipped card -> blocks double-grade / rapid repeats
  const idx=sessionState.currentIndex;
  const c=session[idx];
  captureSnapshot(idx,c.id);          // remember pre-grade state (once per position)
  revertSnapshot(idx);                // undo any earlier grade at this position before re-applying
  // Write transaction FIRST (read -> SRS -> assign progress[id] -> save -> markDirty) owned by
  // ProgressWriter (Phase 12); the session state only advances AFTER the write, so a write
  // failure never leaves a partial advance. Snapshot/undo + daily-learn stay here.
  progressWriter.grade({ cardId: c.id, grade });
  if(window.HSKMeta) HSKMeta.recordDailyLearn(c.id);   // daily-learning chart (Study Mode grades only)
  sessionState=sessionSM.grade(sessionState, grade);   // record grade@idx + advance + flipped=false
  renderCard();
}

function skipCard(){
  const idx=sessionState.currentIndex;
  const k="i"+idx;
  if(k in snapshots){  // this position was graded before -> undo its SRS effect
    const snap=snapshots[k];
    delete snapshots[k];
    // Restore/delete + save + markDirty owned by ProgressWriter (Phase 13); snapshot map,
    // session index and navigation stay controller-owned. No write from navigation itself.
    progressWriter.restore({ cardId: snap.id, hadState: snap.had, previousState: snap.state });
  }
  sessionState=sessionSM.skip(sessionState);   // record "skip"@idx + advance + flipped=false
  renderCard();
}

// Swipe LEFT = Next/Skip (no grading). Swipe RIGHT = previous card (pure navigation).
function swipeNext(){ skipCard(); }
function swipePrev(){ if(sessionState.currentIndex>0){ sessionState=sessionSM.prev(sessionState); renderCard(); } }

// Phase 21: count the session's grades from the authoritative gradesByIndex (no mutation).
// Values are "again"/"hard"/"good"/"easy"/"skip"; a never-graded hole (undefined) is counted
// as "ungraded" (does not occur in normal completion, but handled defensively).
function tallyGrades(gradesByIndex){
  const c={again:0,hard:0,good:0,easy:0,skip:0,ungraded:0,total:gradesByIndex.length};
  for(let i=0;i<gradesByIndex.length;i++){
    const g=gradesByIndex[i];
    if(g==="again")c.again++; else if(g==="hard")c.hard++; else if(g==="good")c.good++;
    else if(g==="easy")c.easy++; else if(g==="skip")c.skip++; else c.ungraded++;
  }
  return c;
}
function cbCell(cls,label,n){ return `<div class="cb-cell ${cls}"><strong>${n}</strong><span>${label}</span></div>`; }
function chItem(n,label){ return `<div class="ch-item"><strong>${n}</strong><span>${label}</span></div>`; }

function finishSession(){
  stopSpeech();
  $("progressBar").style.width="100%"; showView("completeView");
  const c=tallyGrades(sessionState.gradesByIndex);
  const graded=c.again+c.hard+c.good+c.easy;
  const goodCount=c.good+c.easy;
  // Existing summary sentence — format unchanged.
  $("completeText").textContent=`Bạn đã xem ${c.total} thẻ, chấm điểm ${graded} thẻ, nhớ tốt ${goodCount} thẻ${c.skip?`, bỏ qua ${c.skip} thẻ`:""}.`;

  // Grade breakdown grid (counts only; labels mirror the rating buttons).
  $("completeBreakdown").innerHTML=
    cbCell("cb-again","Chưa nhớ",c.again)+cbCell("cb-hard","Khó",c.hard)+
    cbCell("cb-good","Nhớ được",c.good)+cbCell("cb-easy","Rất dễ",c.easy)+
    cbCell("cb-skip","Bỏ qua",c.skip)+
    (c.ungraded?cbCell("cb-ungraded","Chưa chấm",c.ungraded):"");

  // Habit row + continue gating. Due-remaining is read AFTER this session's grade writes
  // (gradeCard writes synchronously before advancing into finishSession) and only for the
  // selected levels, via the existing dueCards() read — no new query module.
  const isLevels=studySource && studySource.type==="levels";
  const dueRemaining=isLevels ? dueCards(studySource.levels).length : 0;
  const dg=dailyGoalModel();   // Phase 22A: same today-count source, now goal-aware (no duplicate item)
  const streak=settingsRepo.getStreak();
  let habit="";
  if(isLevels && dueRemaining===0) habit+=`<div class="complete-allclear">Hôm nay tạm ổn rồi 🎉</div>`;
  if(isLevels && dueRemaining>0) habit+=chItem(dueRemaining,"Còn cần ôn");
  // The existing "Đã học hôm nay" item is made goal-aware (learned/goal), not duplicated.
  habit+=chItem(`${dg.learned}/${dg.goal}`,"Đã học hôm nay")+chItem(streak,"Chuỗi ngày");
  habit+=`<div class="complete-goalbar dg-bar" role="progressbar" aria-label="Tiến độ mục tiêu hôm nay" aria-valuemin="0" aria-valuemax="${dg.goal}" aria-valuenow="${dg.learned}"><span style="width:${dg.percent}%"></span></div>`;
  if(dg.reached) habit+=`<div class="complete-goal-done">Đã hoàn thành mục tiêu hôm nay.</div>`;
  $("completeHabit").innerHTML=habit;

  // "Học tiếp N thẻ": only for level-based sessions that still have due cards. N is the size
  // of the NEXT batch (min of the current session size and the due-remaining count; all due
  // when size = "Tất cả thẻ đến hạn"). Clicking reuses the normal startStudy(levels) path.
  const contBtn=$("continueStudyBtn");
  if(isLevels && dueRemaining>0){
    const sizeSetting=$("sessionSize").value;
    const nextN=sizeSetting==="all" ? dueRemaining : Math.min(parseInt(sizeSetting,10)||dueRemaining, dueRemaining);
    contBtn.textContent=`Học tiếp ${nextN} thẻ`;
    contBtn.hidden=false;
    $("homeBtn").className="secondary-btn";
  } else {
    contBtn.hidden=true;
    $("homeBtn").className="primary-btn";
  }
}

function exitStudy(){ stopSpeech(); showView("homeView"); renderHome(); $("startMixedBtn").focus(); }

/* ---------- Swipe / mouse-drag navigation on the flashcard ---------- */
const SWIPE_THRESHOLD=80, DRAG_ACTIVATE=10;
let drag=null, suppressClick=false;
const fc=$("flashcard");

fc.addEventListener("pointerdown",e=>{
  if(e.pointerType==="mouse" && e.button!==0) return;      // primary button only
  suppressClick=false;
  drag={x0:e.clientX,y0:e.clientY,dx:0,dy:0,id:e.pointerId,decided:false};
});
fc.addEventListener("pointermove",e=>{
  if(!drag || e.pointerId!==drag.id) return;
  drag.dx=e.clientX-drag.x0; drag.dy=e.clientY-drag.y0;
  if(!drag.decided){
    if(Math.abs(drag.dx)>DRAG_ACTIVATE && Math.abs(drag.dx)>Math.abs(drag.dy)){
      drag.decided=true; fc.classList.add("dragging");
      try{ fc.setPointerCapture(e.pointerId); }catch(_){}
    } else if(Math.abs(drag.dy)>DRAG_ACTIVATE){ drag=null; return; }   // vertical intent -> let it scroll
  }
  if(drag.decided){ e.preventDefault(); fc.style.setProperty("--drag-x",drag.dx+"px"); }
});
function endDrag(){
  if(!drag) return;
  const {dx,dy,decided}=drag; drag=null;
  fc.classList.remove("dragging");
  fc.style.removeProperty("--drag-x");
  if(decided){
    suppressClick=true;                                    // a drag must never flip/read
    if(Math.abs(dx)>=SWIPE_THRESHOLD && Math.abs(dx)>Math.abs(dy)){
      if(dx<0) swipeNext(); else swipePrev();
    }                                                      // else: snap back (transition to 0)
  }
}
fc.addEventListener("pointerup",endDrag);
fc.addEventListener("pointercancel",()=>{ if(drag){ drag=null; fc.classList.remove("dragging"); fc.style.removeProperty("--drag-x"); } });

fc.onclick=()=>{ if(suppressClick){ suppressClick=false; return; } flipCard(); };
document.querySelectorAll(".rate").forEach(b=>b.onclick=e=>{e.stopPropagation();gradeCard(b.dataset.grade)});
$("nextBtn").onclick=skipCard;
function toggleLogic(force){
  const p=$("logicPanel"), show=force!==undefined?force:p.classList.contains("hidden");
  p.classList.toggle("hidden",!show);
  $("sheetBackdrop").classList.toggle("hidden",!show);
}
$("logicBtn").onclick=()=>toggleLogic();
$("sheetBackdrop").onclick=()=>toggleLogic(false);
$("logicClose").onclick=()=>toggleLogic(false);
$("startMixedBtn").onclick=()=>startStudy(selectedLevels);
$("sessionSize").onchange=()=>{settings.sessionSize=$("sessionSize").value;saveSettings();};
// Phase 22A: pick the daily goal. Accept only 10/20/30/50; persist once; re-render the goal UI
// (rendering itself never writes). The <select> only offers the allowed values.
$("dailyGoalSelect").onchange=()=>{
  const v=parseInt($("dailyGoalSelect").value,10);
  if([10,20,30,50].indexOf(v)>=0){ settings.dailyGoal=v; saveSettings(); }
  renderDailyGoal();
};
$("backBtn").onclick=exitStudy;
$("homeBtn").onclick=()=>{stopSpeech();showView("homeView");renderHome()};
// Phase 21: "Học tiếp" — restart a level-based session with the same selected levels via the
// normal startStudy path (existing session size, fresh selection, next card front-side).
$("continueStudyBtn").onclick=()=>{ if(studySource && studySource.type==="levels"){ stopSpeech(); startStudy(studySource.levels); } };
$("shuffleBtn").onclick=()=>{session.sort(()=>Math.random()-.5);sessionState=sessionSM.startSession({cardIds:session.map(c=>c.id)});snapshots={};renderCard()};

// Click the Chinese word / example to hear it (without flipping the card, and not after a drag).
// Shared word-audio binding for the two places the vocab word can be shown (depending on
// the front-pinyin setting): the FRONT word (#word) and the BACK word block (#backWordBlock
// = hanzi + pinyin line, shown on the back only when front pinyin is off). Reuses speakWord
// (reads the zh-CN word only — no pinyin/Vietnamese); stopPropagation so it reads instead of
// flipping the card; suppressClick guards against reading after a drag / double playback.
function bindWordAudio(el){ if(el) el.addEventListener("click",e=>{e.stopPropagation(); if(suppressClick){suppressClick=false;return;} speakWord();}); }
bindWordAudio($("word"));            // front face — always shows the word
bindWordAudio($("backWordBlock"));   // back face — shows word+pinyin when front pinyin is off
$("example").addEventListener("click",e=>{e.stopPropagation(); if(suppressClick){suppressClick=false;return;} speakExample();});

$("speakWordBtn").onclick=e=>{e.stopPropagation();speakWord()};
$("speakExampleBtn").onclick=e=>{e.stopPropagation();speakExample()};
$("readAllBtn").onclick=e=>{e.stopPropagation();readAll()};
$("stopSpeechBtn").onclick=e=>{e.stopPropagation();stopSpeech()};

// Keyboard shortcuts (study view only): Space=Flip, 1-4=grade, N=Next, S=speak, Esc=Exit.
document.addEventListener("keydown",e=>{
  if(!$("studyView").classList.contains("active")) return;
  const tag=(e.target.tagName||"").toLowerCase();
  if(tag==="input"||tag==="textarea"||tag==="select") return;
  const k=e.key;
  if(k===" "||k==="Spacebar"){
    if(tag==="button") return;                 // let a focused button activate natively
    e.preventDefault(); flipCard();
  } else if(k==="1"){ if(sessionState.flipped){e.preventDefault();gradeCard("again");} }
  else if(k==="2"){ if(sessionState.flipped){e.preventDefault();gradeCard("hard");} }
  else if(k==="3"){ if(sessionState.flipped){e.preventDefault();gradeCard("good");} }
  else if(k==="4"){ if(sessionState.flipped){e.preventDefault();gradeCard("easy");} }
  else if(k==="n"||k==="N"){ e.preventDefault(); skipCard(); }
  else if(k==="s"||k==="S"){ e.preventDefault(); sessionState.flipped?speakExample():speakWord(); }
  else if(k==="Escape"){ e.preventDefault(); exitStudy(); }
});

// Custom PWA install prompt.
let deferredInstall=null;
window.addEventListener("beforeinstallprompt",e=>{ e.preventDefault(); deferredInstall=e; $("installBtn").hidden=false; });
$("installBtn").onclick=async()=>{
  if(!deferredInstall) return;
  deferredInstall.prompt();
  try{ await deferredInstall.userChoice; }catch(_){}
  deferredInstall=null; $("installBtn").hidden=true;
};
window.addEventListener("appinstalled",()=>{ deferredInstall=null; $("installBtn").hidden=true; });
$("speechRate").onchange=()=>{speech.rate=normSpeechRate($("speechRate").value);settings.speechRate=speech.rate;saveSettings();};
$("autoReadWord").onchange=()=>{settings.autoReadWord=$("autoReadWord").checked;saveSettings();};
$("autoReadExample").onchange=()=>{settings.autoReadExample=$("autoReadExample").checked;saveSettings();};
$("showFrontPinyin").onchange=()=>{settings.showFrontPinyin=$("showFrontPinyin").checked;saveSettings();applyPinyinDisplay();};
if(!speech.supported){
  $("speechBar").style.display="none";
  ["speechRate","autoReadWord","autoReadExample"].forEach(id=>$(id).disabled=true);
} else {
  $("speechUnsupported").style.display="none";
}
$("resetBtn").onclick=()=>{if(confirm("Xóa toàn bộ tiến độ học?")){progressWriter.reset();renderHome();}};   // reset transaction (replace->save->onReset) owned by ProgressWriter (Phase 14)
$("themeBtn").onclick=()=>{document.body.classList.toggle("dark");settings.dark=document.body.classList.contains("dark");saveSettings();};
if(settings.dark)document.body.classList.add("dark");
// Lock the study screen to the real visible height (robust dvh alternative for iOS/dynamic toolbars).
function setAppHeight(){ document.documentElement.style.setProperty("--app-h", window.innerHeight+"px"); }
setAppHeight();
window.addEventListener("resize", setAppHeight);
window.addEventListener("orientationchange", setAppHeight);

if("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(()=>{});
renderHome();

// Bridge for the (optional) cloud-sync layer. No-op in local-only mode.
window.HSK_APP = {
  keys(){ return { stateKey, settingsKey }; },
  getProgress(){ return progress; },
  getSettings(){ return settings; },
  cards(){ return cards; },
  levels(){ return LEVELS; },
  // Start a normal Study Mode session from an explicit, de-duplicated list of card IDs
  // (used by "Ôn các từ này" / "Học các từ đã lưu"). Reuses the existing renderer, audio,
  // grading and SRS exactly.
  startSession(ids){
    // Read-only construction via StudySessionEngine (Phase 16; delegates to Phase 5:
    // resolve ids in requested order, dedup, skip missing).
    const list=studyEngine.buildExplicitSession({ cardIds: ids }).cards;
    if(!list.length) return false;
    studySource={ type:"explicit" };   // Phase 21: no same-level "Học tiếp" for explicit sessions
    session=list; sessionState=sessionSM.startSession({ cardIds: list.map(c=>c.id) }); snapshots={};
    // Deactivate any non-core view (Weak Words / Bookmarks / etc.) before entering
    // Study Mode, since showView() only manages home/study/complete.
    document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
    updateStreak(); showView("studyView"); renderCard();
    return true;
  },
  // Re-read localStorage into memory after a cloud pull merges new data.
  // Never disrupts an active study session.
  reloadState(){
    progress = JSON.parse(localStorage.getItem(stateKey) || "{}");
    settings = JSON.parse(localStorage.getItem(settingsKey) || "{}");
    if(settings.selectedLevels && settings.selectedLevels.length) selectedLevels = settings.selectedLevels;
    speech.rate = normSpeechRate(settings.speechRate);
    document.body.classList.toggle("dark", !!settings.dark);
    applyPinyinDisplay();
    if(!$("studyView").classList.contains("active")) renderHome();
  }
};
