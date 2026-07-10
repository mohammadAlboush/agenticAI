// Assembliert den Single-File-Präsenter demo-day.html aus dd-folie-01..12.html.
// Wiederverwendetes Viewer-Framework (Design/Interaktivität) aus Vortrag.html;
// FONTCSS (eingebettete Inter/Cascadia-Fonts) wird aus Vortrag.html extrahiert.
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const DIR = process.argv[2] || 'C:/Users/moham/Desktop/Projekte/SEO - GEO/seogeo/ProjektPitch/docs/präsentation'
const N = 13

// --- Folien einlesen ---
const FOLIES = []
for (let i = 1; i <= N; i++) {
  const nn = String(i).padStart(2, '0')
  FOLIES.push(readFileSync(join(DIR, `dd-folie-${nn}.html`), 'utf8'))
}

// --- FONTCSS aus Vortrag.html extrahieren (const FONTCSS="....";) ---
// Vortrag.html kann in docs/präsentation/ ODER eine Ebene höher in docs/ liegen.
const vortragCandidates = [join(DIR, 'Vortrag.html'), join(DIR, '..', 'Vortrag.html')]
const vortragPath = vortragCandidates.find((p) => existsSync(p))
if (!vortragPath) throw new Error('Vortrag.html nicht gefunden (docs/präsentation/ oder docs/)')
const vortrag = readFileSync(vortragPath, 'utf8')
const m = vortrag.match(/const FONTCSS=("(?:\\.|[^"\\])*");/)
if (!m) throw new Error('FONTCSS in Vortrag.html nicht gefunden')
const FONTCSS_LITERAL = m[1] // bereits ein gültiges JS-String-Literal

// --- Metadaten (einzige Quelle der Wahrheit) ---
const TITLES = [
  'geo-audit-loop · Titel',
  'Problem · Sichtbarkeit = zitiert werden',
  'Lösung · geschlossener Regelkreis',
  'Live-Demo · Steuerzentrale',
  'Live-Demo · Setup',
  'Live-Demo · Messen (Top/Flop)',
  'Live-Demo · Verstehen & Fixen',
  'Live-Demo · Lernen (Effekt → Gedächtnis)',
  'Architektur · Hexagonal',
  'Architektur · Entscheidungen',
  'Der Lern-Hebel · Code UND Prompt',
  'Reflexion',
  'Danke · Fragen?',
]
const SHORTS = [
  'Titel', 'Problem', 'Lösung', 'Live-Demo', 'Demo-Setup', 'Messen', 'Verstehen & Fixen',
  'Lernen', 'Architektur', 'Entscheidungen', 'Lern-Hebel', 'Reflexion', 'Danke',
]
const MAXBEATS = [4, 3, 2, 3, 3, 2, 4, 4, 3, 2, 4, 2, 3]
const NOTES = [
  // 01 Titel
  `Guten Tag. Ich stelle geo-audit-loop vor — einen selbstlernenden agentischen Regelkreis für GEO, \
also die Optimierung darauf, in Such- und AI-Engines zitiert zu werden. In sieben Minuten zeige ich: \
das Problem und meine Lösung, dann live den kompletten Loop, die Architektur mit ihren Kernentscheidungen \
und zum Schluss meine wichtigste Erkenntnis.`,
  // 02 Problem
  `Früher war Sichtbarkeit gleich Ranking — Platz eins bei Google. Das hat sich verschoben: AI-Engines \
synthetisieren die Antwort selbst und nennen nur wenige Quellen. Wer nicht zitiert wird, ist unsichtbar, \
egal wie gut das Ranking war. Und die Engines haben eigene Präferenzen — die Überlappung mit den klassischen \
Google-Treffern ist stark gesunken. Das Problem: kaum jemand misst systematisch, ob und warum die eigene \
Seite zitiert wird. Genau das macht mein System.`,
  // 03 Lösung
  `Meine Lösung ist ein geschlossener Regelkreis aus fünf spezialisierten Agenten. Wir messen zuerst neutral, \
welche Seiten zitiert werden. Dann auditieren wir die Schwachstellen gegen Best-Practice-Templates. Der \
Fix-Agent schlägt konkrete Patches vor — die ein Mensch freigibt. Nach dem Deploy messen wir den Effekt \
erneut und schreiben ihn als Hypothese ins Gedächtnis. Dieser letzte Schritt schließt den Kreis: der Effekt \
fließt zurück und macht den nächsten Lauf besser. Das zeige ich jetzt live.`,
  // 04 Live-Demo · Steuerzentrale
  `Und zwar nicht auf Folien, sondern in einer echten Weboberfläche. Ein Klick startet den Lauf gegen echte \
AI-Engines — die Probe-Matrix füllt sich vor Ihren Augen. Ehrlich dabei: nur die tatsächlich live geprobten \
Engines sind grün markiert, simulierte klar als solche. Von hier laufen alle Schritte durch — messen, \
verstehen, fixen, lernen — und genau das gehen wir jetzt gemeinsam durch.`,
  // 05 Demo-Setup
  `Das komplette System läuft mit einem einzigen Befehl. Eine Domain, ein fester Seed, eine feste Prompt-Version \
— damit ist jeder Lauf über run_id und Fingerprint voll nachvollziehbar. In diesem Lauf: 240 Probes über vier \
Engines, zwölf Prompts und fünf Proxy-IPs. Der Median über die IPs eliminiert Personalisierungs-Effekte. Das \
läuft gegen echte AI-Engines — und dank hartem Budget-Cap und Checkpointing bleibt es sicher und fortsetzbar.`,
  // 05 Messen
  `Der Sampler feuert 240 Probes ab. Statt einer personalisierten Sicht nehmen wir den Median über fünf \
Proxy-IPs. Jede der vier Engines liefert Zitate in einem anderen Format — die normalisieren wir auf ein \
einziges Citation-Modell. Ergebnis ist diese Top/Flop-Liste. Oben: die NIS2-Seite wird in 30 Prozent der \
Antworten zitiert. Unten die Verlierer — die Security-Awareness-Seite kommt auf drei Prozent. Diese \
Flop-Seiten nehmen wir uns jetzt vor.`,
  // 06 Verstehen & Fixen
  `Jetzt wird der Loop schlau. Der Pattern-Miner schaut sich die Gewinner an und mint ein wiederverwendbares \
Template — etwa: ein Antwortblock von vierzig bis sechzig Wörtern direkt nach der Überschrift, verankert in \
Hebel zwei, Extrahierbarkeit. Der GEO-Auditor hält die Flop-Seite dagegen: hier fehlt genau dieser Block — \
Schweregrad hoch. Der Fix-Agent macht daraus einen konkreten Patch: fertiger Antwortblock plus FAQ-Schema \
als JSON-LD. Und die eiserne Regel: kein Patch ohne menschliche Freigabe — sonst fliegt DeployBlocked.`,
  // 07 Lernen
  `Nach dem Deploy messen wir denselben Matrix-Schnitt noch einmal — die Re-Probe. Für die gepatchte \
Seite steigt die Zitationsrate von drei auf elf Prozent. Daraus baut der Effekt-Analyst eine strukturierte \
EffectHypothesis: Vorher, Nachher, Delta, und eine Confidence, die rein deterministisch berechnet wird — \
kein LLM, also reproduzierbar. Diese Hypothese wandert ins Gedächtnis. Der Clou: beim nächsten Lauf ruft der \
Loop sie ab und ordnet den Fix-Plan messbar um. Das System lernt — der Kreis ist geschlossen.`,
  // 08 Architektur
  `Zur Architektur — meine wichtigste technische Entscheidung. Das ist hexagonal aufgebaut, Ports und \
Adapters. Der Kern in der Mitte — reine Domänenlogik plus Port-Interfaces — kennt keine konkrete Außenwelt: \
kein HTTP, kein WordPress, kein Proxy-Detail. Drumherum die Adapter, die diese Ports implementieren. Effekt: \
jeder externe Aufruf ist im Test mockbar, und eine fünfte Engine ergänze ich, ohne den Kern anzufassen. Die \
Agenten hängen ausschließlich an den Ports.`,
  // 09 Entscheidungen
  `Weil das ein Forschungsprojekt ist, zählt Nachvollziehbarkeit. Vier Entscheidungen tragen das: erstens \
harte Pydantic-Datenverträge zwischen allen Agenten — nie Freitext. Zweitens für jeden Port ein Mock- und ein \
Live-Adapter hinter demselben Interface, damit Tests ohne Netz laufen. Drittens volle Reproduzierbarkeit über \
run_id, festen Seed und einen Fingerprint — in den sogar der gemessene Effekt einfließt. Viertens: alles, was \
deterministisch sein kann, ist es auch. Über allem das harte Human-in-the-Loop-Gate: kein Auto-Deploy.`,
  // 10 Lern-Hebel
  `Das ist der innovativste — und riskanteste — Teil, deshalb bin ich hier besonders sorgfältig. Wie \
beeinflusst eine abgerufene Hypothese den nächsten Fix? Nicht implizit, sondern auf zwei explizite Wege. Der \
Loop ruft passende Hypothesen ab. Erstens deterministisch im Code: apply_memory_prior verschiebt die Konfidenz \
der Patches, prioritize_proposals ordnet den Plan messbar um. Zweitens im Prompt: der Fix-Agent bekommt in \
Version zwei die Hypothesen direkt mitgegeben. Beides sorgt dafür, dass der nächste Lauf nachweislich anders fixt.`,
  // 11 Reflexion
  `Zur Reflexion. Mein größtes Learning: Contracts-first zahlt sich massiv aus. Weil die Pydantic-Verträge \
und die Mock-Live-Symmetrie von Anfang an standen, war jeder Agent sofort testbar, und ich konnte den Loop \
Sprint für Sprint erweitern, ohne den Kern zu brechen. Und Determinismus ist ein Feature — der bit-genaue \
Fingerprint hat mich zu sauberen Grenzen gezwungen. Was ich anders machen würde: einen dünnen \
End-to-End-Durchstich noch früher, und die kostenlosen Live-Engines früher evaluieren.`,
  // 12 Danke
  `Damit ist der Regelkreis geschlossen: messen, auditieren, fixen, re-proben, lernen — jeder Lauf macht den \
nächsten besser. Vielen Dank für Ihre Aufmerksamkeit, ich freue mich auf Ihre Fragen.`,
]

if ([TITLES, SHORTS, MAXBEATS, NOTES].some(a => a.length !== N))
  throw new Error('Metadaten-Länge != ' + N)

// --- Viewer zusammenbauen ---
const J = (x) => JSON.stringify(x)
// Eingebettete Folien-HTML sicher in ein <script> legen: </script> würde den
// Eltern-<script> vorzeitig schließen -> zu <\/script> escapen (im srcdoc wieder </script>).
const embed = (x) => J(x).replace(/<\/(script)/gi, '<\\/$1')
const html = `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo Day · geo-audit-loop</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:#12140d;overflow:hidden;
  font-family:"Inter","Segoe UI","Segoe UI Variable Text",system-ui,sans-serif}
#frame{position:fixed;inset:0;width:100%;height:100%;border:0;background:#f6f5f1;display:block}
#progress{position:fixed;top:0;left:0;height:3px;width:0;background:#71b127;z-index:30;
  transition:width .35s cubic-bezier(.16,1,.3,1);box-shadow:0 0 7px rgba(113,177,39,.55)}
.chrome{position:fixed;z-index:30;transition:opacity .4s ease}
#deck.idle .chrome{opacity:0;pointer-events:none}
#bar{bottom:16px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:12px;
  background:rgba(22,26,17,.86);border:1px solid rgba(255,255,255,.08);border-radius:999px;
  padding:7px 10px 7px 12px;color:#e9ecdf;box-shadow:0 8px 28px rgba(0,0,0,.28)}
#bar button{appearance:none;border:0;background:transparent;color:#cfd6c4;cursor:pointer;
  font-size:16px;line-height:1;padding:6px 9px;border-radius:999px;transition:background .2s,color .2s}
#bar button:hover{background:rgba(255,255,255,.1);color:#fff}
#dots{display:flex;gap:5px;align-items:center;padding:0 4px}
.dot{width:8px;height:8px;border-radius:50%;background:#565d4b;cursor:pointer;padding:0;
  transition:all .25s cubic-bezier(.16,1,.3,1)}
.dot:hover{background:#8a9179}
.dot.on{background:#8fd47f;width:20px;border-radius:4px}
#count{font-family:"Cascadia Code","Consolas",monospace;font-size:12px;color:#aeb6a0;
  min-width:52px;text-align:center;letter-spacing:.03em}
#label{font-size:12.5px;color:#e9ecdf;max-width:230px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;padding-right:4px;border-left:1px solid rgba(255,255,255,.12);padding-left:12px}
#help{position:fixed;bottom:16px;right:18px;font-family:"Cascadia Code","Consolas",monospace;
  font-size:11px;color:rgba(233,236,223,.55);text-align:right;line-height:1.7}
#help b{color:rgba(233,236,223,.8)}
#overview{position:fixed;inset:0;z-index:40;background:rgba(14,16,10,.96);
  opacity:0;pointer-events:none;transition:opacity .3s ease;
  display:flex;flex-direction:column;padding:clamp(30px,5vw,64px)}
#overview.open{opacity:1;pointer-events:auto}
#ovhead{font-family:"Cascadia Code","Consolas",monospace;font-size:12px;letter-spacing:.16em;
  text-transform:uppercase;color:#8fd47f;margin-bottom:22px}
#ovlist{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;overflow:auto}
.ovitem{text-align:left;appearance:none;cursor:pointer;color:#dfe4d5;
  background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:12px;
  padding:14px 16px;font-size:14.5px;display:flex;gap:12px;align-items:center;transition:all .2s}
.ovitem:hover{background:rgba(113,177,39,.16);border-color:rgba(143,212,127,.5);color:#fff}
.ovitem.on{border-color:#8fd47f;background:rgba(113,177,39,.14)}
.ovn{font-family:"Cascadia Code","Consolas",monospace;font-size:12px;color:#8fd47f;font-weight:700}
#script{position:fixed;left:0;right:0;bottom:0;z-index:35;height:clamp(170px,33vh,320px);
  background:rgba(16,19,12,.97);border-top:2px solid #71b127;color:#eef1e6;
  transform:translateY(101%);transition:transform .35s cubic-bezier(.16,1,.3,1);
  padding:15px clamp(28px,5vw,72px) 22px;display:flex;flex-direction:column;
  box-shadow:0 -14px 44px rgba(0,0,0,.42)}
#script.open{transform:translateY(0)}
#scripthead{display:flex;justify-content:space-between;align-items:center;
  font-family:"Cascadia Code","Consolas",monospace;font-size:12px;letter-spacing:.12em;
  text-transform:uppercase;color:#8fd47f;margin-bottom:12px}
#scripthead button{appearance:none;border:0;background:transparent;color:#9aa88a;cursor:pointer;font-size:16px;line-height:1}
#scripttext{font-size:clamp(15px,1.85vw,22px);line-height:1.55;color:#e8eddb;overflow:auto;
  font-family:"Inter","Segoe UI",system-ui,sans-serif;max-width:1100px}
</style>
</head>
<body>
<div id="deck">
  <div id="progress" class="chrome"></div>
  <iframe id="frame" title="Folie" allow="fullscreen"></iframe>
  <div id="bar" class="chrome">
    <button id="prev" title="Zurück (←)">‹</button>
    <div id="dots"></div>
    <span id="count">1 / ${N}</span>
    <span id="label"></span>
    <button id="next" title="Weiter (Leertaste)">›</button>
    <button id="scriptBtn" title="Skript (S)">≡</button>
    <button id="presBtn" title="Presenter · 2. Bildschirm (P)">⧉</button>
    <button id="ovBtn" title="Übersicht (O)">▦</button>
    <button id="fsBtn" title="Vollbild (F)">⤢</button>
  </div>
  <div id="help" class="chrome"><b>Leertaste</b> weiter · <b>←</b> zurück · <b>S</b> Skript · <b>P</b> Presenter · <b>O</b> Übersicht · <b>F</b> Vollbild</div>
  <div id="overview">
    <div id="ovhead">Übersicht · ${N} Folien</div>
    <div id="ovlist"></div>
  </div>
  <div id="script">
    <div id="scripthead"><span id="scriptnum"></span><button id="scriptClose" title="Schließen (S)">✕</button></div>
    <div id="scripttext"></div>
  </div>
</div>
<script>
const FOLIES=[${FOLIES.map(embed).join(',\n')}];
const TITLES=${J(TITLES)};
const SHORTS=${J(SHORTS)};
const NOTES=${J(NOTES)};
const MAXBEATS=${J(MAXBEATS)};
const FONTCSS=${FONTCSS_LITERAL};
(function(){const s=document.createElement('style');s.textContent=FONTCSS;document.head.appendChild(s);})();
const N=FOLIES.length;
const frame=document.getElementById('frame');
const deck=document.getElementById('deck');
const dotsEl=document.getElementById('dots');
const countEl=document.getElementById('count');
const labelEl=document.getElementById('label');
const progress=document.getElementById('progress');
const overview=document.getElementById('overview');
const ovlist=document.getElementById('ovlist');
const scriptEl=document.getElementById('script');
const scriptText=document.getElementById('scripttext');
const scriptNum=document.getElementById('scriptnum');
let cur=0, beatCount=0, ovOpen=false, scriptOpen=false;
for(let i=0;i<N;i++){
  const d=document.createElement('button'); d.className='dot'; d.title=(i+1)+' · '+SHORTS[i];
  d.onclick=()=>go(i); dotsEl.appendChild(d);
  const li=document.createElement('button'); li.className='ovitem';
  li.innerHTML='<span class="ovn">'+String(i+1).padStart(2,'0')+'</span><span>'+SHORTS[i]+'</span>';
  li.onclick=()=>{ go(i); toggleOverview(false); }; ovlist.appendChild(li);
}
function updateChrome(){
  countEl.textContent=(cur+1)+' / '+N;
  labelEl.textContent=SHORTS[cur];
  progress.style.width=((cur+1)/N*100)+'%';
  [...dotsEl.children].forEach((d,i)=>d.classList.toggle('on',i===cur));
  [...ovlist.children].forEach((li,i)=>li.classList.toggle('on',i===cur));
}
function updateScript(){
  scriptNum.textContent='Skript · Folie '+(cur+1)+' / '+N+'  ·  '+SHORTS[cur];
  scriptText.textContent=NOTES[cur];
}
function go(i){
  cur=Math.max(0,Math.min(N-1,i));
  beatCount=0;
  frame.srcdoc=FOLIES[cur];
  updateChrome(); updateScript(); activity(); broadcast();
}
function domFinished(){
  try{ const d=frame.contentDocument;
    if(cur===0 && d.querySelector('.stage.b4')) return true;   // Titel (Auto-Play)
    if(d.querySelector('.finished')) return true;              // Inhalts- & Danke-Folien
    return false;
  }catch(e){ return false; }
}
function slideDone(){ return beatCount>=(MAXBEATS[cur]||0) || domFinished(); }
function forward(){
  if(slideDone()){ if(cur<N-1) go(cur+1); }
  else{
    beatCount++;
    try{ const w=frame.contentWindow;
      w.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',code:'Space',bubbles:true}));
    }catch(e){}
    activity(); broadcast();
  }
}
frame.addEventListener('load',()=>{
  try{
    const w=frame.contentWindow, d=frame.contentDocument;
    const st=d.createElement('style'); st.textContent=FONTCSS+'.hint{display:none!important}'; d.head.appendChild(st);
    w.addEventListener('keydown',frameKey,true);
    w.addEventListener('mousemove',activity,true);
    w.addEventListener('mousedown',activity,true);
    w.focus();
  }catch(e){}
});
function navKey(e){
  const k=e.key;
  if(k===' '||e.code==='Space'||k==='Enter'||k==='ArrowRight'||k==='PageDown'){ forward(); return true; }
  if(k==='ArrowLeft'||k==='PageUp'){ go(cur-1); return true; }
  if(k==='Home'){ go(0); return true; }
  if(k==='End'){ go(N-1); return true; }
  if(k==='f'||k==='F'){ toggleFs(); return true; }
  if(k==='o'||k==='O'){ toggleOverview(); return true; }
  if(k==='s'||k==='S'){ toggleScript(); return true; }
  if(k==='p'||k==='P'){ openPresenter(); return true; }
  if(k==='Escape'){ if(ovOpen){toggleOverview(false);return true;} if(scriptOpen){toggleScript(false);return true;} }
  return false;
}
function frameKey(e){ if(!e.isTrusted) return; if(navKey(e)){ e.preventDefault(); e.stopImmediatePropagation(); } }
window.addEventListener('keydown',(e)=>{ if(navKey(e)){ e.preventDefault(); } });
document.getElementById('prev').onclick=()=>go(cur-1);
document.getElementById('next').onclick=forward;
document.getElementById('fsBtn').onclick=toggleFs;
document.getElementById('ovBtn').onclick=()=>toggleOverview();
document.getElementById('scriptBtn').onclick=()=>toggleScript();
document.getElementById('scriptClose').onclick=()=>toggleScript(false);
document.getElementById('presBtn').onclick=()=>openPresenter();
function toggleFs(){ try{ if(!document.fullscreenElement){ document.documentElement.requestFullscreen(); } else { document.exitFullscreen(); } }catch(e){} }
function toggleOverview(force){
  ovOpen=(force===undefined)?!ovOpen:force;
  overview.classList.toggle('open',ovOpen);
  if(ovOpen){ deck.classList.remove('idle'); } else { try{frame.contentWindow.focus();}catch(e){} }
}
function toggleScript(force){
  scriptOpen=(force===undefined)?!scriptOpen:force;
  scriptEl.classList.toggle('open',scriptOpen);
  if(scriptOpen){ deck.classList.remove('idle'); } else { try{frame.contentWindow.focus();}catch(e){} }
}
let idleT; function activity(){ deck.classList.remove('idle'); clearTimeout(idleT);
  idleT=setTimeout(()=>{ if(!ovOpen && !scriptOpen) deck.classList.add('idle'); },2800); }
window.addEventListener('mousemove',activity); window.addEventListener('mousedown',activity);

/* ===== Presenter-Ansicht auf zweitem Bildschirm (Taste P) =====
   Oeffnet ein eigenes Fenster (auf den 2. Monitor ziehen). Bei jedem Schritt schickt
   das Deck Folie, Sprechertext (Satz fuer Satz), Beats und naechste Folie per postMessage.
   Steuerung funktioniert in beide Richtungen. */
let presenterWin=null;
function noteChunks(i){
  var t=(NOTES[i]||'').trim(); if(!t) return [''];
  var parts=t.split('. ');
  return parts.map(function(p,k){ return (k<parts.length-1)?p+'.':p; });
}
function presenterState(){
  var chunks=noteChunks(cur); var mb=(MAXBEATS[cur]||0);
  var active = mb>0 ? Math.round(beatCount/mb*(chunks.length-1)) : 0;
  active=Math.max(0,Math.min(active,chunks.length-1));
  return { type:'state', num:cur+1, total:N, short:SHORTS[cur], chunks:chunks, active:active,
    beat:beatCount, maxbeat:mb, nextShort:(cur<N-1?SHORTS[cur+1]:''), done:slideDone() };
}
function broadcast(){ if(presenterWin && !presenterWin.closed){ try{ presenterWin.postMessage(presenterState(),'*'); }catch(e){} } }
const PRESENTER_HTML='<!doctype html><html lang="de"><head><meta charset="utf-8">'
+'<meta name="viewport" content="width=device-width,initial-scale=1">'
+'<title>Presenter · geo-audit-loop</title><style>'
+'*{margin:0;padding:0;box-sizing:border-box}html,body{height:100%}'
+'body{background:#12140d;color:#eef1e6;font-family:"Inter","Segoe UI",system-ui,sans-serif;'
+'display:flex;flex-direction:column;padding:clamp(20px,3.4vw,46px);gap:16px;overflow:hidden}'
+'#top{display:flex;justify-content:space-between;align-items:center;'
+'font-family:"Cascadia Code","Consolas",monospace;font-size:13px;letter-spacing:.14em;'
+'text-transform:uppercase;color:#8fd47f}'
+'#top .r{display:flex;gap:22px;align-items:center;color:#aeb6a0;letter-spacing:.05em}#timer{color:#eef1e6}'
+'#folie{font-family:"Cascadia Code","Consolas",monospace;font-size:15px;color:#aeb6a0;letter-spacing:.03em}'
+'#folie b{color:#8fd47f}'
+'#beats{display:flex;gap:8px;align-items:center;min-height:8px}'
+'.pill{width:36px;height:8px;border-radius:4px;background:#3a4130;transition:background .2s}'
+'.pill.on{background:#71b127;box-shadow:0 0 8px rgba(113,177,39,.5)}'
+'#note{flex:1;overflow:auto;padding-right:10px;display:flex;flex-direction:column;gap:14px}'
+'.chunk{font-size:clamp(20px,2.7vw,34px);line-height:1.45;padding-left:16px;border-left:4px solid transparent;transition:color .2s,opacity .2s,border-color .2s}'
+'.chunk.done{color:#7f8a72;opacity:.5}.chunk.cur{color:#f2f5ec;border-left-color:#71b127}.chunk.next{color:#9aa48c;opacity:.5}'
+'#bottom{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;border-top:1px solid rgba(255,255,255,.1);padding-top:14px}'
+'#step{font-family:"Cascadia Code","Consolas",monospace;font-size:14px;color:#aeb6a0;margin-bottom:5px}'
+'#next{font-size:18px;color:#cfd6c4}#next b{color:#8fd47f}'
+'#hint{font-family:"Cascadia Code","Consolas",monospace;font-size:11px;color:rgba(233,236,223,.45);text-align:right;line-height:1.8}#hint b{color:rgba(233,236,223,.75)}'
+'</style></head><body>'
+'<div id="top"><span>Presenter · geo-audit-loop</span>'
+'<span class="r"><span id="clock">--:--</span><span id="timer">00:00</span></span></div>'
+'<div id="folie"></div><div id="beats"></div>'
+'<div id="note">Warte auf das Deck …</div>'
+'<div id="bottom"><div><div id="step"></div><div id="next"></div></div>'
+'<div id="hint"><b>Leertaste</b> weiter · <b>&larr;</b> zurueck · <b>R</b> Timer 0 · <b>F</b> Vollbild</div></div>'
+'<scr'+'ipt>(function(){'
+'function pad(n){return String(n).padStart(2,"0");}var startT=Date.now();'
+'function tick(){var d=new Date();document.getElementById("clock").textContent=pad(d.getHours())+":"+pad(d.getMinutes());'
+'var s=Math.floor((Date.now()-startT)/1000);document.getElementById("timer").textContent=pad(Math.floor(s/60))+":"+pad(s%60);}'
+'setInterval(tick,1000);tick();'
+'function render(s){document.getElementById("folie").innerHTML="Folie <b>"+s.num+"</b> / "+s.total+" · "+s.short;'
+'var note=document.getElementById("note");note.innerHTML="";var chunks=s.chunks||[];var act=(typeof s.active==="number"?s.active:0);var curEl=null;'
+'for(var j=0;j<chunks.length;j++){var c=document.createElement("div");c.className="chunk "+(j<act?"done":(j===act?"cur":"next"));c.textContent=chunks[j];note.appendChild(c);if(j===act)curEl=c;}'
+'if(curEl){curEl.scrollIntoView({block:"center"});}'
+'document.getElementById("step").textContent=s.maxbeat>0?("Schritt "+Math.min(s.beat,s.maxbeat)+" / "+s.maxbeat):"—";'
+'document.getElementById("next").innerHTML=s.nextShort?("Als Naechstes &rarr; <b>"+s.nextShort+"</b>"):"<b>Ende der Praesentation</b>";'
+'var b=document.getElementById("beats");b.innerHTML="";for(var i=0;i<s.maxbeat;i++){var p=document.createElement("div");p.className="pill"+(i<s.beat?" on":"");b.appendChild(p);}}'
+'window.addEventListener("message",function(e){var d=e.data||{};if(d.type==="state")render(d);});'
+'window.addEventListener("keydown",function(e){var k=e.key;'
+'if(k==="r"||k==="R"){startT=Date.now();tick();e.preventDefault();return;}'
+'if(k==="f"||k==="F"){try{document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();}catch(_){}e.preventDefault();return;}'
+'if(window.opener&&!window.opener.closed){window.opener.postMessage({type:"key",key:k,code:e.code},"*");e.preventDefault();}});'
+'if(window.opener&&!window.opener.closed){window.opener.postMessage({type:"ready"},"*");}'
+'})();<\/scr'+'ipt></body></html>';
function openPresenter(){
  if(presenterWin && !presenterWin.closed){ presenterWin.focus(); broadcast(); return; }
  presenterWin=window.open('','geoPresenter','width=1024,height=700');
  if(!presenterWin){ alert('Bitte Pop-ups fuer diese Seite erlauben — dann oeffnet sich der Presenter in einem zweiten Fenster, das Sie auf den 2. Bildschirm ziehen koennen.'); return; }
  presenterWin.document.open(); presenterWin.document.write(PRESENTER_HTML); presenterWin.document.close();
  try{ frame.contentWindow.focus(); }catch(e){}
}
window.addEventListener('message',function(e){
  const d=e.data||{};
  if(d.type==='ready'){ broadcast(); return; }
  if(d.type==='key'){ navKey({key:d.key,code:d.code,preventDefault:function(){}}); }
});
window.addEventListener('beforeunload',function(){ try{ if(presenterWin && !presenterWin.closed) presenterWin.close(); }catch(e){} });

go(0); activity();
</script>
</body>
</html>
`

writeFileSync(join(DIR, 'demo-day.html'), html, 'utf8')
console.log('demo-day.html geschrieben:', (html.length / 1024).toFixed(0), 'KB · Folien:', N)
