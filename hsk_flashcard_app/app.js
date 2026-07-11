
const cards = window.HSK_CARDS || [];
const stateKey = "hsk_flashcard_progress_v2";
const settingsKey = "hsk_flashcard_settings_v2";
let progress = JSON.parse(localStorage.getItem(stateKey) || "{}");
let settings = JSON.parse(localStorage.getItem(settingsKey) || "{}");
let session = [], current = 0, selectedLevels = settings.selectedLevels || ["HSK1"], flipped = false, sessionGrades = [];

const $ = id => document.getElementById(id);

/* ---------- Speech (browser SpeechSynthesis) ---------- */
const speech = {
  supported: typeof window !== "undefined" && "speechSynthesis" in window,
  voices: [],
  rate: Number(settings.speechRate) || 1,
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
function showView(id){ views.forEach(v => $(v).classList.toggle("active", v===id)); }
function today(){ return new Date().toISOString().slice(0,10); }
function getCardState(id){ return progress[id] || {due: today(), interval:0, reps:0, correct:0, attempts:0}; }
function save(){ localStorage.setItem(stateKey, JSON.stringify(progress)); }
function saveSettings(){ localStorage.setItem(settingsKey, JSON.stringify(settings)); }
function dueCards(levels){
  const now=today();
  return cards.filter(c=>levels.includes(c.level) && getCardState(c.id).due<=now);
}
function levelCards(level){ return cards.filter(c=>c.level===level); }

function renderLevelPicker(){
  const wrap=$("levelPicker"); wrap.innerHTML="";
  ["HSK1","HSK2","HSK3","HSK4"].forEach(level=>{
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
  $("speechRate").value=String(settings.speechRate || 1);
  $("autoReadWord").checked=!!settings.autoReadWord;
  $("autoReadExample").checked=!!settings.autoReadExample;
  const grid=$("deckGrid"); grid.innerHTML="";
  ["HSK1","HSK2","HSK3","HSK4"].forEach(level=>{
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
  $("dueCount").textContent=dueCards(["HSK1","HSK2","HSK3","HSK4"]).length;
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

  current=0; sessionGrades=[]; updateStreak(); showView("studyView"); renderCard();
}

function renderCard(){
  if(current>=session.length) return finishSession();
  const c=session[current]; flipped=false;
  $("flashcard").classList.remove("flipped");
  $("ratingArea").classList.add("hidden");
  $("nextBtn").classList.add("hidden");
  $("logicPanel").classList.add("hidden");
  $("flipHint").textContent="Bấm vào thẻ để lật";
  $("studyLevel").textContent=[...new Set(session.map(x=>x.level))].join(" + ");
  $("cardIndex").textContent=current+1; $("cardTotal").textContent=session.length;
  $("progressBar").style.width=((current/session.length)*100)+"%";
  $("levelBadge").textContent=c.level; $("word").textContent=c.word; $("pinyin").textContent=c.pinyin;
  $("meaning").textContent=c.meaning; $("example").textContent=c.example; $("examplePinyin").textContent=c.examplePinyin; $("translation").textContent=c.translation;
  $("flashcard").setAttribute("aria-label",`Thẻ ${current+1}/${session.length}. Từ: ${c.word}. Bấm hoặc nhấn Space để xem nghĩa.`);
  $("srStatus").textContent=`Thẻ ${current+1} trên ${session.length}. ${c.level}: ${c.word}.`;
  stopSpeech();                       // always stop audio when the card changes
  if(settings.autoReadWord) speakWord();
  $("flashcard").focus();             // keep keyboard focus on the card
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
}

function gradeCard(grade){
  const c=session[current], s=getCardState(c.id), now=new Date();
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
  sessionGrades.push(grade); current++; renderCard();
}

function skipCard(){
  sessionGrades.push("skip");
  current++;
  renderCard();
}

function finishSession(){
  stopSpeech();
  $("progressBar").style.width="100%"; showView("completeView");
  const graded=sessionGrades.filter(x=>x!=="skip");
  const good=graded.filter(x=>x==="good"||x==="easy").length;
  const skipped=sessionGrades.filter(x=>x==="skip").length;
  $("completeText").textContent=`Bạn đã xem ${sessionGrades.length} thẻ, chấm điểm ${graded.length} thẻ, nhớ tốt ${good} thẻ${skipped?`, bỏ qua ${skipped} thẻ`:""}.`;
}

function exitStudy(){ stopSpeech(); showView("homeView"); renderHome(); $("startMixedBtn").focus(); }

$("flashcard").onclick=flipCard;
document.querySelectorAll(".rate").forEach(b=>b.onclick=e=>{e.stopPropagation();gradeCard(b.dataset.grade)});
$("nextBtn").onclick=skipCard;
$("logicBtn").onclick=()=>$("logicPanel").classList.toggle("hidden");
$("startMixedBtn").onclick=()=>startStudy(selectedLevels);
$("sessionSize").onchange=()=>{settings.sessionSize=$("sessionSize").value;saveSettings();};
$("backBtn").onclick=exitStudy;
$("homeBtn").onclick=()=>{stopSpeech();showView("homeView");renderHome()};
$("shuffleBtn").onclick=()=>{session.sort(()=>Math.random()-.5);current=0;renderCard()};

// Click the Chinese word / example to hear it (without flipping the card).
$("word").addEventListener("click",e=>{e.stopPropagation();speakWord()});
$("example").addEventListener("click",e=>{e.stopPropagation();speakExample()});

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
$("speechRate").onchange=()=>{speech.rate=Number($("speechRate").value)||1;settings.speechRate=speech.rate;saveSettings();};
$("autoReadWord").onchange=()=>{settings.autoReadWord=$("autoReadWord").checked;saveSettings();};
$("autoReadExample").onchange=()=>{settings.autoReadExample=$("autoReadExample").checked;saveSettings();};
if(!speech.supported){
  $("speechBar").style.display="none";
  ["speechRate","autoReadWord","autoReadExample"].forEach(id=>$(id).disabled=true);
} else {
  $("speechUnsupported").style.display="none";
}
$("resetBtn").onclick=()=>{if(confirm("Xóa toàn bộ tiến độ học?")){progress={};save();renderHome();}};
$("themeBtn").onclick=()=>{document.body.classList.toggle("dark");settings.dark=document.body.classList.contains("dark");saveSettings();};
if(settings.dark)document.body.classList.add("dark");
if("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(()=>{});
renderHome();
