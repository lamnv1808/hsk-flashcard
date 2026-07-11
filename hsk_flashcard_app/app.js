
const cards = window.HSK_CARDS || [];
const stateKey = "hsk_flashcard_progress_v2";
const settingsKey = "hsk_flashcard_settings_v2";
let progress = JSON.parse(localStorage.getItem(stateKey) || "{}");
let settings = JSON.parse(localStorage.getItem(settingsKey) || "{}");
let session = [], current = 0, selectedLevels = settings.selectedLevels || ["HSK1"], flipped = false, sessionGrades = [];

const $ = id => document.getElementById(id);
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
}

function flipCard(){
  flipped=!flipped; $("flashcard").classList.toggle("flipped",flipped);
  $("ratingArea").classList.toggle("hidden",!flipped);
  $("nextBtn").classList.toggle("hidden",!flipped);
  $("flipHint").textContent=flipped?"Chọn mức độ nhớ, hoặc Next để bỏ qua chấm điểm.":"Bấm vào thẻ để lật";
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
  $("progressBar").style.width="100%"; showView("completeView");
  const graded=sessionGrades.filter(x=>x!=="skip");
  const good=graded.filter(x=>x==="good"||x==="easy").length;
  const skipped=sessionGrades.filter(x=>x==="skip").length;
  $("completeText").textContent=`Bạn đã xem ${sessionGrades.length} thẻ, chấm điểm ${graded.length} thẻ, nhớ tốt ${good} thẻ${skipped?`, bỏ qua ${skipped} thẻ`:""}.`;
}

$("flashcard").onclick=flipCard;
document.querySelectorAll(".rate").forEach(b=>b.onclick=e=>{e.stopPropagation();gradeCard(b.dataset.grade)});
$("nextBtn").onclick=skipCard;
$("logicBtn").onclick=()=>$("logicPanel").classList.toggle("hidden");
$("startMixedBtn").onclick=()=>startStudy(selectedLevels);
$("sessionSize").onchange=()=>{settings.sessionSize=$("sessionSize").value;saveSettings();};
$("backBtn").onclick=()=>{showView("homeView");renderHome()};
$("homeBtn").onclick=()=>{showView("homeView");renderHome()};
$("shuffleBtn").onclick=()=>{session.sort(()=>Math.random()-.5);current=0;renderCard()};
$("resetBtn").onclick=()=>{if(confirm("Xóa toàn bộ tiến độ học?")){progress={};save();renderHome();}};
$("themeBtn").onclick=()=>{document.body.classList.toggle("dark");settings.dark=document.body.classList.contains("dark");saveSettings();};
if(settings.dark)document.body.classList.add("dark");
if("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(()=>{});
renderHome();
