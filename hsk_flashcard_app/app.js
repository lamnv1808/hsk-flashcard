
const cards = window.HSK_CARDS || [];
// All HSK levels present in the data, ordered by numeric suffix.
// Auto-detected from the cards, so adding HSK5/HSK6 (or later HSK7…) needs no code change.
const LEVELS = window.HSKUtil.levels.levelsFromCards(cards);
// Storage keys: namespaced per logged-in account when cloud accounts are active,
// otherwise the original global keys (unchanged local-only behavior).
const AUTH = window.HSK_AUTH || {};
const stateKey = AUTH.progressKey || "hsk_flashcard_progress_v2";
const settingsKey = AUTH.settingsKey || "hsk_flashcard_settings_v2";
let progress = JSON.parse(localStorage.getItem(stateKey) || "{}");
let settings = JSON.parse(localStorage.getItem(settingsKey) || "{}");
let session = [], current = 0, selectedLevels = settings.selectedLevels || ["HSK1"], flipped = false, sessionGrades = [];
let snapshots = {};   // in-memory per-session-index undo history for SRS (never persisted)

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

function currentCard(){ return session[current]; }
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
function levelCards(level){ return cards.filter(c=>c.level===level); }

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
  $("sessionSize").value=settings.sessionSize || "20";
  $("speechRate").value=String(normSpeechRate(settings.speechRate));
  $("autoReadWord").checked=!!settings.autoReadWord;
  $("autoReadExample").checked=!!settings.autoReadExample;
  $("showFrontPinyin").checked=settings.showFrontPinyin!==false;   // default on
  $("totalWords").textContent=cards.length.toLocaleString("vi-VN");   // total vocab count, automatic
  const grid=$("deckGrid"); grid.innerHTML="";
  LEVELS.forEach(level=>{
    const all=levelCards(level), learned=all.filter(c=>getCardState(c.id).reps>0).length, due=dueCards([level]).length;
    const pct=Math.round(learned/all.length*100);
    const btn=document.createElement("button");
    btn.className="deck-card";
    btn.innerHTML=`<div class="deck-level">${level}</div><div class="deck-count">${all.length} từ · ${due} cần ôn</div><div class="deck-progress"><span style="width:${pct}%"></span></div><div class="deck-meta"><span>Đã học ${learned}</span><span>${pct}%</span></div>`;
    btn.onclick=()=>{ selectedLevels=[level]; settings.selectedLevels=selectedLevels; saveSettings(); renderLevelPicker(); };
    grid.appendChild(btn);
  });
  const learned=cards.filter(c=>getCardState(c.id).reps>0).length;
  const attempts=Object.values(progress).reduce((s,x)=>s+(x.attempts||0),0);
  const correct=Object.values(progress).reduce((s,x)=>s+(x.correct||0),0);
  $("learnedStat").textContent=learned;
  $("retentionStat").textContent=attempts?Math.round(correct/attempts*100)+"%":"0%";
  $("streakStat").textContent=settings.streak||0;
  $("dueCount").textContent=dueCards(LEVELS).length;
}

function updateStreak(){
  const d=today(), last=settings.lastStudy;
  if(last===d) return;
  const y=new Date(); y.setDate(y.getDate()-1);
  settings.streak = last===y.toISOString().slice(0,10) ? (settings.streak||0)+1 : 1;
  settings.lastStudy=d; saveSettings();
}

function startStudy(levels){
  const sizeSetting=$("sessionSize").value;
  settings.sessionSize=sizeSetting; settings.selectedLevels=levels; saveSettings();

  const due=dueCards(levels);
  const fresh=cards.filter(c=>levels.includes(c.level) && getCardState(c.id).reps===0);
  const merged=[...due, ...fresh.filter(c=>!due.some(d=>d.id===c.id))];
  const limit=sizeSetting==="all"?merged.length:Number(sizeSetting);
  session=merged.slice(0,limit);

  if(!session.length){
    const fallback=cards.filter(c=>levels.includes(c.level)).sort(()=>Math.random()-.5);
    session=fallback.slice(0, sizeSetting==="all"?fallback.length:Number(sizeSetting));
  }

  current=0; sessionGrades=[]; snapshots={}; updateStreak(); showView("studyView"); renderCard();
}

// Vocab pinyin (column C): shown on the FRONT by default; when the setting is off it
// moves to the back (above the meaning). Never both sides; example pinyin is untouched.
function applyPinyinDisplay(){
  const showFP = settings.showFrontPinyin !== false;   // undefined => true (existing users unchanged)
  $("pinyin").style.display = showFP ? "" : "none";
  $("backWordBlock").style.display = showFP ? "none" : "";
  $("flashcard").classList.toggle("no-front-pinyin", !showFP);  // lets CSS fit the denser back on mobile
}

function renderCard(){
  if(current>=session.length) return finishSession();
  const c=session[current];
  const fc=$("flashcard");
  // P0 answer-leak fix: reset the flip WITHOUT the un-flip animation, so the back
  // face never rotates through a viewer-facing angle while it already holds the
  // next card's answer. Disable the face transition, drop .flipped + write the new
  // content on the front, force a reflow so it applies instantly, then re-enable the
  // transition for user-initiated flips.
  fc.classList.add("no-flip-anim");
  flipped=false;
  fc.classList.remove("flipped");
  $("ratingArea").classList.add("hidden");
  $("nextBtn").classList.add("hidden");
  $("logicPanel").classList.add("hidden");
  $("sheetBackdrop").classList.add("hidden");
  $("flipHint").textContent="Bấm vào thẻ để lật";
  $("studyLevel").textContent=[...new Set(session.map(x=>x.level))].join(" + ");
  $("cardIndex").textContent=current+1; $("cardTotal").textContent=session.length;
  $("progressBar").style.width=((current/session.length)*100)+"%";
  $("levelBadge").textContent=c.level; $("word").textContent=c.word; $("pinyin").textContent=c.pinyin;
  $("meaning").textContent=c.meaning; $("example").textContent=c.example; $("examplePinyin").textContent=c.examplePinyin; $("translation").textContent=c.translation;
  // Front vocab pinyin (column C) shows on the front by default; when disabled it moves to the back.
  $("backWord").textContent=c.word; $("backPinyin").textContent=c.pinyin;
  applyPinyinDisplay();
  if(window.HSKMeta) HSKMeta.syncCard();   // bookmark state + hide note zone (front)
  void fc.offsetWidth;                     // force reflow: front + new content painted with no animation
  fc.classList.remove("no-flip-anim");     // restore the flip animation for the next user flip
  $("flashcard").setAttribute("aria-label",`Thẻ ${current+1}/${session.length}. Từ: ${c.word}. Bấm hoặc nhấn Space để xem nghĩa.`);
  $("srStatus").textContent=`Thẻ ${current+1} trên ${session.length}. ${c.level}: ${c.word}.`;
  stopSpeech();                       // always stop audio when the card changes
  if(settings.autoReadWord) speakWord();
  $("flashcard").focus({preventScroll:true});   // keep keyboard focus without scroll jumps
}

function flipCard(){
  flipped=!flipped; $("flashcard").classList.toggle("flipped",flipped);
  $("ratingArea").classList.toggle("hidden",!flipped);
  $("nextBtn").classList.toggle("hidden",!flipped);
  $("flipHint").textContent=flipped?"Chọn mức độ nhớ, hoặc Next để bỏ qua chấm điểm.":"Bấm vào thẻ để lật";
  const c=currentCard();
  if(c){
    $("flashcard").setAttribute("aria-label",flipped?`Đáp án. Nghĩa: ${c.meaning}. Bấm để lật lại.`:`Từ: ${c.word}. Bấm để xem nghĩa.`);
    $("srStatus").textContent=flipped?`Nghĩa: ${c.meaning}.`:`Từ: ${c.word}.`;
  }
  if(flipped){ stopSpeech(); if(settings.autoReadExample) speakExample(); } else stopSpeech();
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

function gradeCard(grade){
  if(!flipped) return;             // guard: only grade a flipped card -> blocks double-grade / rapid repeats
  const c=session[current];
  captureSnapshot(current,c.id);   // remember pre-grade state (once per position)
  revertSnapshot(current);         // undo any earlier grade at this position before re-applying
  const s=getCardState(c.id), now=new Date();
  let days;
  if(grade==="again"){
    days=0;
    now.setMinutes(now.getMinutes()+1);
    s.interval=0;
  } else if(grade==="hard"){
    days=Math.max(1, s.interval ? Math.round(s.interval*1.2) : 1);
    now.setDate(now.getDate()+days);
    s.interval=days;
  } else if(grade==="good"){
    days=Math.max(3, s.interval ? Math.round(s.interval*2.0) : 3);
    now.setDate(now.getDate()+days);
    s.interval=days;
  } else {
    days=Math.max(7, s.interval ? Math.round(s.interval*3.0) : 7);
    now.setDate(now.getDate()+days);
    s.interval=days;
  }
  s.due=now.toISOString().slice(0,10);
  s.reps=(s.reps||0)+1;
  s.attempts=(s.attempts||0)+1;
  if(grade==="good"||grade==="easy") s.correct=(s.correct||0)+1;
  progress[c.id]=s; save();
  if(window.HSKSync) HSKSync.markDirty(c.id);   // queue only this card for cloud sync
  if(window.HSKMeta) HSKMeta.recordDailyLearn(c.id);   // daily-learning chart (Study Mode grades only)
  sessionGrades[current]=grade;    // index-addressed: re-grading overwrites, never duplicates
  current++; renderCard();
}

function skipCard(){
  if(("i"+current) in snapshots){  // this position was graded before -> undo its SRS effect
    const sid=snapshots["i"+current].id;
    revertSnapshot(current);
    delete snapshots["i"+current];
    save();
    if(window.HSKSync) HSKSync.markDirty(sid);
  }
  sessionGrades[current]="skip";
  current++;
  renderCard();
}

// Swipe LEFT = Next/Skip (no grading). Swipe RIGHT = previous card (pure navigation).
function swipeNext(){ skipCard(); }
function swipePrev(){ if(current>0){ current--; renderCard(); } }

function finishSession(){
  stopSpeech();
  $("progressBar").style.width="100%"; showView("completeView");
  const graded=sessionGrades.filter(x=>x!=="skip");
  const good=graded.filter(x=>x==="good"||x==="easy").length;
  const skipped=sessionGrades.filter(x=>x==="skip").length;
  $("completeText").textContent=`Bạn đã xem ${sessionGrades.length} thẻ, chấm điểm ${graded.length} thẻ, nhớ tốt ${good} thẻ${skipped?`, bỏ qua ${skipped} thẻ`:""}.`;
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
$("backBtn").onclick=exitStudy;
$("homeBtn").onclick=()=>{stopSpeech();showView("homeView");renderHome()};
$("shuffleBtn").onclick=()=>{session.sort(()=>Math.random()-.5);current=0;snapshots={};sessionGrades=[];renderCard()};

// Click the Chinese word / example to hear it (without flipping the card, and not after a drag).
$("word").addEventListener("click",e=>{e.stopPropagation(); if(suppressClick){suppressClick=false;return;} speakWord();});
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
  } else if(k==="1"){ if(flipped){e.preventDefault();gradeCard("again");} }
  else if(k==="2"){ if(flipped){e.preventDefault();gradeCard("hard");} }
  else if(k==="3"){ if(flipped){e.preventDefault();gradeCard("good");} }
  else if(k==="4"){ if(flipped){e.preventDefault();gradeCard("easy");} }
  else if(k==="n"||k==="N"){ e.preventDefault(); skipCard(); }
  else if(k==="s"||k==="S"){ e.preventDefault(); flipped?speakExample():speakWord(); }
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
$("resetBtn").onclick=()=>{if(confirm("Xóa toàn bộ tiến độ học?")){progress={};save();if(window.HSKSync)HSKSync.onReset();renderHome();}};
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
    const byId = window.HSKUtil.cardIndex.buildCardById(cards);
    const list=[]; const seen=new Set();
    (ids||[]).forEach(id=>{ const c=byId.get(id); if(c && !seen.has(c.id)){ seen.add(c.id); list.push(c); } });
    if(!list.length) return false;
    session=list; current=0; sessionGrades=[]; snapshots={};
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
