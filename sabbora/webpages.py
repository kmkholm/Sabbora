"""Self-contained HTML pages served by webserver.py (no external files, works offline)."""

_COMMON_CSS = r"""
:root{--hdr1:#0B3B5C;--hdr2:#0E7C86;--bg:#F3F6FA;--card:#fff;--text:#0F172A;--muted:#64748B;
--primary:#0E7C86;--danger:#E11D48;--warn:#F59E0B;--border:#DCE3EC;--accent:#FBBF24}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);
font-family:"Segoe UI",Tahoma,system-ui,-apple-system,Roboto,"Noto Sans Arabic",sans-serif}
header{background:linear-gradient(90deg,var(--hdr1),var(--hdr2));color:#fff;padding:10px 14px;
display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:5}
header img{width:34px;height:34px}
header .t{font-weight:700;font-size:17px;flex:1}
header .s{font-size:12px;opacity:.85}
button{font:inherit;border:1px solid var(--border);background:var(--card);color:var(--text);
border-radius:12px;padding:11px 14px;cursor:pointer}
button:active{transform:scale(.97)}
button.p{background:var(--primary);color:#fff;border:none;font-weight:600}
button.d{background:var(--danger);color:#fff;border:none;font-weight:600}
button.w{background:var(--warn);color:#1F1300;border:none;font-weight:600}
button.on{background:var(--warn);color:#1F1300;border-color:var(--warn)}
button.hb{background:rgba(255,255,255,.15);color:#fff;border:1px solid rgba(255,255,255,.4);padding:6px 10px;border-radius:10px}
input{font:inherit;width:100%;padding:12px;border:1px solid #C9D3DF;border-radius:12px;background:#fff;color:var(--text)}
input:focus{outline:2px solid var(--primary);border-color:transparent}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;margin:14px}
.muted{color:var(--muted);font-size:13px}
.err{color:var(--danger);font-weight:600;min-height:20px}
.modal{position:fixed;inset:0;background:rgba(15,23,42,.55);display:none;align-items:center;justify-content:center;z-index:20;padding:16px}
.modal.show{display:flex}
.modal .box{background:var(--card);border-radius:18px;padding:18px;max-width:520px;width:100%;max-height:85vh;overflow:auto;box-shadow:0 10px 40px rgba(0,0,0,.3)}
.modal h3{margin:0 0 10px;color:var(--hdr1)}
.row{display:flex;gap:8px;flex-wrap:wrap}
.row>*{flex:1}
.toast{position:fixed;left:50%;transform:translateX(-50%);bottom:90px;background:#0F172A;color:#fff;
padding:10px 16px;border-radius:12px;z-index:30;display:none;max-width:90%;text-align:center}
"""

STUDENT_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0B3B5C">
<link rel="icon" href="/icon.png"><link rel="apple-touch-icon" href="/icon.png">
<title>Sabbora · سبّورة</title>
<style>""" + _COMMON_CSS + r"""
#stage{position:relative;background:#0B1220;margin:0;min-height:calc(100vh - 190px);display:flex;align-items:center;justify-content:center;overflow:auto}
#screen{max-width:100%;max-height:calc(100vh - 190px);display:none;touch-action:pinch-zoom}
#stage.full{position:fixed;inset:0;z-index:15;min-height:100vh}
#stage.full #screen{max-height:100vh}
#wait{color:#9FB3AA;text-align:center;padding:30px;font-size:16px}
#bar{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--border);
display:flex;gap:6px;padding:8px 8px calc(8px + env(safe-area-inset-bottom));z-index:10}
#bar button{flex:1;padding:10px 4px;font-size:13px;display:flex;flex-direction:column;align-items:center;gap:2px}
#bar .ic{font-size:20px;line-height:1}
#info{display:flex;align-items:center;gap:8px;padding:8px 14px;background:var(--card);border-bottom:1px solid var(--border);font-size:14px}
#info b{color:var(--hdr1)}
#dot{width:10px;height:10px;border-radius:50%;background:#94A3B8;flex:none}
#dot.ok{background:#059669}
#timer{position:fixed;top:64px;inset-inline-end:12px;background:#0B3B5C;color:#fff;border-radius:14px;padding:8px 14px;z-index:12;display:none;text-align:center;box-shadow:0 4px 14px rgba(0,0,0,.25)}
#timer .tt{font-size:12px;opacity:.85}#timer .tv{font-size:26px;font-weight:800}
#lock{position:fixed;inset:0;z-index:25;display:none;flex-direction:column;align-items:center;justify-content:center;
background:linear-gradient(#0B3B5C,#06202F);color:#fff;text-align:center;padding:24px}
#lock .big{font-size:64px}#lock h2{margin:10px 0}
#files{margin:0 14px 90px}
#files a{display:block;padding:10px;border:1px solid var(--border);border-radius:10px;margin:6px 0;background:#fff;color:var(--primary);text-decoration:none;font-weight:600}
.opt{width:100%;margin:5px 0;text-align:start}
.opt.sel{background:var(--primary);color:#fff;border-color:var(--primary)}
.bar2{height:22px;background:#E2E8F0;border-radius:8px;overflow:hidden;margin:4px 0}
.bar2 i{display:block;height:100%;background:var(--primary)}
textarea{width:100%;min-height:110px;font:inherit;padding:10px;border-radius:12px;border:1px solid #C9D3DF}
</style></head><body>
<header><img src="/icon.png" alt=""><div><div class="t" data-i="title"></div><div class="s" data-i="sub"></div></div>
<div style="flex:1"></div><button class="hb" id="langBtn"></button></header>

<section id="join" class="card">
  <h3 style="margin-top:0;color:#0B3B5C" data-i="joinH"></h3>
  <p class="muted" data-i="joinP"></p>
  <label data-i="name"></label><input id="name" autocomplete="name">
  <div style="height:10px"></div>
  <label data-i="code"></label><input id="code" inputmode="numeric" maxlength="12">
  <div style="height:14px"></div>
  <button class="p" id="joinBtn" style="width:100%"></button>
  <p class="err" id="err"></p>
</section>

<section id="cls" style="display:none">
  <div id="info"><span id="dot"></span><span id="course"></span><span style="flex:1"></span></div>
  <div id="stage"><div id="wait" data-i="wait"></div><img id="screen" alt=""></div>
  <div id="files"></div>
  <div id="bar">
    <button id="handBtn"><span class="ic">✋</span><span data-i="hand"></span></button>
    <button id="askBtn"><span class="ic">💬</span><span data-i="ask"></span></button>
    <button id="sendBtn"><span class="ic">📤</span><span data-i="submit"></span></button>
    <button id="photoBtn"><span class="ic">📷</span><span data-i="photo"></span></button>
    <button id="fullBtn"><span class="ic">⛶</span><span data-i="full"></span></button>
  </div>
</section>
<input type="file" id="fileIn" hidden>
<input type="file" id="camIn" accept="image/*" capture="environment" hidden>

<div id="timer"><div class="tt" id="timerT"></div><div class="tv" id="timerV"></div></div>
<div id="lock"><div class="big">🔒</div><h2 data-i="locked"></h2><p id="lockText"></p></div>
<div class="modal" id="modal"><div class="box" id="mbox"></div></div>
<div class="toast" id="toast"></div>

<script>
const WS_PORT = %%WS_PORT%%, VERSION = "%%VERSION%%";
const TXT = {
 ar:{title:"سبّورة",sub:"الطالب — من المتصفح",joinH:"دخول المحاضرة",joinP:"اكتب اسمك ورمز الصف الظاهر على شاشة المحاضر.",
  name:"اسمك",code:"رمز الصف",join:"دخول",visible:"",wait:"بانتظار أن يعرض المحاضر شاشته…",hand:"رفع اليد",handDown:"إنزال اليد",
  ask:"سؤال",submit:"تسليم ملف",photo:"صورة",full:"ملء الشاشة",locked:"الشاشة مقفلة من المحاضر",needName:"اكتب اسمك أولًا.",
  needCode:"اكتب رمز الصف.",badCode:"رمز الصف غير صحيح.",connecting:"جارٍ الاتصال…",lost:"انقطع الاتصال — إعادة المحاولة…",
  ok:"حسنًا",send:"إرسال",cancel:"إلغاء",askH:"سؤال للمحاضر",askP:"اكتب سؤالك أو رسالتك:",sent:"وصلت رسالتك إلى المحاضر.",
  msgH:"رسالة من المحاضر",pollH:"تصويت",pollNote:"اختر إجابة؛ يمكنك تغييرها قبل انتهاء التصويت.",voted:"✅ وصلت إجابتك.",
  pollEnd:"انتهى التصويت.",result:"النتيجة",timeLeft:"الوقت المتبقي",timeUp:"⏰ انتهى الوقت",pick:"🎲 وقع عليك الاختيار للإجابة!",
  collectH:"طلب تسليم",collectP:"يطلب المحاضر تسليم:",chooseFile:"📤 اختيار ملف",takePhoto:"📷 تصوير",
  clipH:"نص من المحاضر",copy:"نسخ",copied:"تم النسخ",uploading:"جارٍ التسليم",uploaded:"✅ تم التسليم:",rejected:"❌ لم يُقبل الملف",
  fileFrom:"ملف من المحاضر:",linkH:"رابط من المحاضر",open:"فتح",kicked:"أنهى المحاضر اتصالك.",bye:"أغلق المحاضر الجلسة — سيعاد الاتصال تلقائيًا.",
  tooBig:"الحد الأقصى 200 ميغابايت.",lang:"English"},
 en:{title:"Sabbora",sub:"Student — in the browser",joinH:"Join the lecture",joinP:"Type your name and the class code shown on the teacher's screen.",
  name:"Your name",code:"Class code",join:"Join",visible:"",wait:"Waiting for the teacher to share the screen…",hand:"Raise hand",handDown:"Lower hand",
  ask:"Ask",submit:"Submit file",photo:"Photo",full:"Full screen",locked:"Screen locked by the teacher",needName:"Type your name first.",
  needCode:"Type the class code.",badCode:"Wrong class code.",connecting:"Connecting…",lost:"Connection lost — retrying…",
  ok:"OK",send:"Send",cancel:"Cancel",askH:"Question for the teacher",askP:"Type your question or message:",sent:"Your message reached the teacher.",
  msgH:"Message from the teacher",pollH:"Poll",pollNote:"Choose one answer; you can change it until the poll ends.",voted:"✅ Your answer was received.",
  pollEnd:"The poll has ended.",result:"Result",timeLeft:"Time left",timeUp:"⏰ Time's up",pick:"🎲 You have been picked to answer!",
  collectH:"Assignment request",collectP:"The teacher asks you to submit:",chooseFile:"📤 Choose file",takePhoto:"📷 Take photo",
  clipH:"Text from the teacher",copy:"Copy",copied:"Copied",uploading:"Submitting",uploaded:"✅ Submitted:",rejected:"❌ File not accepted",
  fileFrom:"File from the teacher:",linkH:"Link from the teacher",open:"Open",kicked:"The teacher disconnected you.",bye:"The teacher closed the session — reconnecting automatically.",
  tooBig:"The limit is 200 MB.",lang:"العربية"}};
const $ = id => document.getElementById(id);
function store(k, v){ try{ if(v===undefined) return localStorage.getItem(k); localStorage.setItem(k, v); }catch(e){ return null; } }
let LANG = store("sb_lang") || ((navigator.language||"").toLowerCase().startsWith("ar") ? "ar" : "%%LANG%%");
const t = k => { const d = TXT[LANG] || TXT.en; return (k in d) ? d[k] : k; };
function applyLang(){
  document.documentElement.lang = LANG; document.documentElement.dir = LANG === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i]").forEach(e => e.textContent = t(e.dataset.i));
  $("joinBtn").textContent = t("join"); $("langBtn").textContent = "🌐 " + t("lang");
  $("handBtn").querySelector("[data-i]").textContent = hand ? t("handDown") : t("hand");
}
let hand = false;
$("langBtn").onclick = () => { LANG = LANG === "ar" ? "en" : "ar"; store("sb_lang", LANG); applyLang(); };

const params = new URLSearchParams(location.search);
$("code").value = params.get("c") || store("sb_code") || "";
$("name").value = store("sb_name") || "";
let sid = store("sb_id"); if(!sid){ sid = "web-" + Math.random().toString(36).slice(2, 12); store("sb_id", sid); }

function device(){
  const ua = navigator.userAgent;
  if(/iPhone/.test(ua)) return "iPhone"; if(/iPad/.test(ua)) return "iPad";
  if(/Android/.test(ua)) return /Mobile/.test(ua) ? "Android phone" : "Android tablet";
  if(/CrOS/.test(ua)) return "Chromebook"; if(/Mac OS/.test(ua)) return "Mac"; if(/Windows/.test(ua)) return "Windows browser";
  return "Browser";
}
function toast(msg, ms){ const e = $("toast"); e.textContent = msg; e.style.display = "block"; clearTimeout(toast.h); toast.h = setTimeout(() => e.style.display = "none", ms || 3500); }
function beep(){ try{ const a = new (window.AudioContext||window.webkitAudioContext)(); const o = a.createOscillator(); o.frequency.value = 880; o.connect(a.destination); o.start(); setTimeout(() => { o.stop(); a.close(); }, 180); }catch(e){} if(navigator.vibrate) navigator.vibrate(150); }
const mq = [];
function modal(html, setup){ mq.push([html, setup]); if(!$("modal").classList.contains("show")) nextModal(); }
function nextModal(){ const it = mq.shift(); if(!it){ $("modal").classList.remove("show"); return; }
  $("mbox").innerHTML = it[0]; $("modal").classList.add("show"); if(it[1]) it[1]($("mbox")); }
function closeModal(){ nextModal(); }
function esc(s){ return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

let ws = null, want = false, welcomed = false, code = "", name = "";
function send(o){ if(ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
$("joinBtn").onclick = () => {
  name = $("name").value.trim(); code = $("code").value.trim();
  if(!name){ $("err").textContent = t("needName"); return; }
  if(!code){ $("err").textContent = t("needCode"); return; }
  store("sb_name", name); store("sb_code", code); want = true; $("err").textContent = t("connecting"); connect();
};
function connect(){
  try{ if(ws) ws.close(); }catch(e){}
  ws = new WebSocket("ws://" + location.hostname + ":" + WS_PORT + "/");
  ws.binaryType = "arraybuffer";
  ws.onopen = () => send({t:"hello", id:sid, name:name, code:code, host:device(), user:"", os:navigator.platform||"", kind:"web", ver:VERSION, screen:[screen.width, screen.height]});
  ws.onmessage = e => { if(typeof e.data === "string"){ let m; try{ m = JSON.parse(e.data); }catch(x){ return; } onText(m); } else onBin(new Uint8Array(e.data)); };
  ws.onclose = () => { const was = welcomed; welcomed = false; $("dot").classList.remove("ok"); unlock();
    if(want){ if(was) toast(t("lost")); else if($("join").style.display !== "none") $("err").textContent = t("lost"); setTimeout(() => want && connect(), 3000); } };
}

// ------------------------------------------------------------- lecture image
let lastUrl = null;
function showFrame(bytes){
  const url = URL.createObjectURL(new Blob([bytes], {type:"image/jpeg"}));
  const img = $("screen");
  img.onload = () => { if(lastUrl) URL.revokeObjectURL(lastUrl); lastUrl = url; send({t:"ack_b"}); };
  img.onerror = () => send({t:"ack_b"});
  img.src = url; img.style.display = "block"; $("wait").style.display = "none";
}
$("fullBtn").onclick = () => {
  const st = $("stage");
  if(st.requestFullscreen && !document.fullscreenElement){ st.requestFullscreen().catch(() => st.classList.toggle("full")); }
  else if(document.fullscreenElement){ document.exitFullscreen(); }
  else st.classList.toggle("full");
};
$("stage").ondblclick = () => $("fullBtn").onclick();

// ------------------------------------------------------------- files from the teacher
const recv = {};
function onBin(d){
  const kind = d[0];
  if(kind === 1){ showFrame(d.subarray(1)); return; }
  if(kind === 3){
    const v = new DataView(d.buffer, d.byteOffset + 1, 8), fid = v.getUint32(0), idx = v.getUint32(4), r = recv[fid];
    if(!r || idx !== r.parts.length) return;
    r.parts.push(d.slice(9)); send({t:"file_ack", fid:fid, n:r.parts.length});
  }
}
function fileDone(fid){
  const r = recv[fid]; if(!r) return; delete recv[fid];
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(r.parts)); a.download = r.name;
  a.textContent = "📁 " + t("fileFrom") + " " + r.name; $("files").prepend(a);
  send({t:"file_ok", name:r.name}); toast("📁 " + r.name); beep();
}

// ------------------------------------------------------------- uploads (assignments / photos)
let upId = 0; const ups = {};
function submit(file){
  if(!welcomed || !file) return;
  if(file.size > 200 * 1024 * 1024){ toast(t("tooBig")); return; }
  const fid = ++upId, CH = 262144, chunks = Math.ceil(file.size / CH);
  ups[fid] = {file:file, chunks:chunks, next:0, acked:0, sending:false};
  send({t:"up_begin", fid:fid, name:file.name || ("photo-" + Date.now() + ".jpg"), size:file.size, chunks:chunks});
  pump(fid);
}
async function pump(fid){
  const u = ups[fid]; if(!u || u.sending) return; u.sending = true;
  const CH = 262144;
  while(u.next < u.chunks && u.next - u.acked < 8){
    const buf = new Uint8Array(await u.file.slice(u.next * CH, (u.next + 1) * CH).arrayBuffer());
    const msg = new Uint8Array(9 + buf.length), v = new DataView(msg.buffer);
    msg[0] = 0x12; v.setUint32(1, fid); v.setUint32(5, u.next); msg.set(buf, 9);
    ws.send(msg); u.next++;
  }
  u.sending = false;
  toast(t("uploading") + " " + Math.floor(100 * u.acked / Math.max(1, u.chunks)) + "%", 1500);
  if(u.acked >= u.chunks) send({t:"up_end", fid:fid});
}
$("sendBtn").onclick = () => $("fileIn").click();
$("photoBtn").onclick = () => $("camIn").click();
$("fileIn").onchange = e => { submit(e.target.files[0]); e.target.value = ""; };
$("camIn").onchange = e => { submit(e.target.files[0]); e.target.value = ""; };

// ------------------------------------------------------------- hand, question
$("handBtn").onclick = () => { hand = !hand; $("handBtn").classList.toggle("on", hand); applyLang(); send({t:"hand", up:hand}); };
$("askBtn").onclick = () => {
  modal('<h3>' + t("askH") + '</h3><p class="muted">' + t("askP") + '</p><textarea id="q"></textarea><div style="height:10px"></div>' +
    '<div class="row"><button id="qc">' + t("cancel") + '</button><button class="p" id="qs">' + t("send") + '</button></div>', b => {
  b.querySelector("#qc").onclick = closeModal;
  b.querySelector("#qs").onclick = () => { const v = b.querySelector("#q").value.trim(); if(v){ send({t:"chat", text:v}); toast(t("sent")); } closeModal(); }; });
};

// ------------------------------------------------------------- lock, timer
function lock(text){ $("lockText").textContent = text || ""; $("lock").style.display = "flex"; send({t:"status", locked:true}); }
function unlock(){ if($("lock").style.display === "flex"){ $("lock").style.display = "none"; send({t:"status", locked:false}); } }
let timerEnd = 0, timerH = null;
function startTimer(sec, title){
  timerEnd = Date.now() + sec * 1000; $("timerT").textContent = "⏱ " + (title || t("timeLeft")); $("timer").style.display = "block";
  clearInterval(timerH); timerH = setInterval(tick, 500); tick();
}
function tick(){
  const left = Math.round((timerEnd - Date.now()) / 1000);
  if(left > 0){ $("timerV").textContent = String(Math.floor(left / 60)).padStart(2, "0") + ":" + String(left % 60).padStart(2, "0"); $("timerV").style.color = left <= 10 ? "#FF6B5B" : "#fff"; }
  else if(left > -8){ $("timerV").textContent = t("timeUp"); if(left === 0) beep(); }
  else stopTimer();
}
function stopTimer(){ clearInterval(timerH); $("timer").style.display = "none"; }

// ------------------------------------------------------------- poll
let pollId = null;
function showPoll(m){
  pollId = m.pid;
  let h = '<h3>📊 ' + esc(m.q) + '</h3>';
  m.opts.forEach((o, i) => h += '<button class="opt" data-i="' + i + '">' + esc(o) + '</button>');
  h += '<p class="muted" id="pn">' + t("pollNote") + '</p><div id="pr"></div><button class="p" id="pc" style="width:100%">' + t("ok") + '</button>';
  modal(h, b => {
  b.querySelectorAll(".opt").forEach(btn => btn.onclick = () => {
    b.querySelectorAll(".opt").forEach(x => x.classList.toggle("sel", x === btn));
    send({t:"vote", pid:pollId, i:+btn.dataset.i}); b.querySelector("#pn").textContent = t("voted");
  });
  b.querySelector("#pc").onclick = closeModal; }); beep();
}

// ------------------------------------------------------------- messages from the teacher
function onText(m){
  switch(m.t){
    case "welcome":
      welcomed = true; $("join").style.display = "none"; $("cls").style.display = "block"; $("dot").classList.add("ok");
      $("course").innerHTML = "📚 <b>" + esc(m.course || "") + "</b>"; $("err").textContent = "";
      send({t:"status", win:"📱 " + device() + " — " + (LANG === "ar" ? "متصفح" : "browser")});
      if(hand) send({t:"hand", up:true}); break;
    case "reject": want = false; $("err").textContent = t("badCode"); break;
    case "kick": want = false; welcomed = false; try{ ws.close(); }catch(e){} $("cls").style.display = "none"; $("join").style.display = "block"; $("err").textContent = t("kicked"); break;
    case "bye": toast(t("bye")); break;
    case "bstart": $("wait").style.display = $("screen").style.display === "block" ? "none" : "block"; break;
    case "bstop": $("screen").style.display = "none"; $("wait").style.display = "block"; if(document.fullscreenElement) document.exitFullscreen(); $("stage").classList.remove("full"); break;
    case "lock": lock(m.text); break;
    case "unlock": unlock(); break;
    case "msg": beep(); modal('<h3>📣 ' + t("msgH") + '</h3><p style="font-size:17px;white-space:pre-wrap">' + esc(m.text) + '</p><button class="p" style="width:100%" onclick="closeModal()">' + t("ok") + '</button>'); break;
    case "url": modal('<h3>🌐 ' + t("linkH") + '</h3><p style="word-break:break-all">' + esc(m.url) + '</p><div class="row"><button onclick="closeModal()">' + t("cancel") + '</button><a href="' + esc(m.url) + '" target="_blank" rel="noopener" style="flex:1"><button class="p" style="width:100%" onclick="closeModal()">' + t("open") + '</button></a></div>'); break;
    case "clip": modal('<h3>📋 ' + t("clipH") + '</h3><textarea id="ct" readonly>' + esc(m.text) + '</textarea><div style="height:10px"></div><div class="row"><button onclick="closeModal()">' + t("ok") + '</button><button class="p" id="cc">' + t("copy") + '</button></div>', b => {
      b.querySelector("#cc").onclick = () => { const ta = b.querySelector("#ct"); ta.select(); try{ (navigator.clipboard ? navigator.clipboard.writeText(ta.value) : Promise.reject()).catch(() => document.execCommand("copy")); }catch(e){ document.execCommand("copy"); } toast(t("copied")); }; }); break;
    case "poll": showPoll(m); break;
    case "poll_result": if(m.pid === pollId && $("pr")){ const tot = Math.max(1, m.counts.reduce((a, b) => a + b, 0)); let h = '<p><b>' + t("result") + '</b></p>';
      m.opts.forEach((o, i) => h += '<div>' + esc(o) + ': ' + m.counts[i] + '</div><div class="bar2"><i style="width:' + (100 * m.counts[i] / tot) + '%"></i></div>'); $("pr").innerHTML = h; } break;
    case "poll_end": if(m.pid === pollId && $("pn")){ $("pn").textContent = t("pollEnd"); document.querySelectorAll(".opt").forEach(x => x.disabled = true); } break;
    case "timer": startTimer(m.seconds, m.title); break;
    case "timer_stop": stopTimer(); break;
    case "pick": beep(); modal('<h3 style="text-align:center;font-size:24px">' + t("pick") + '</h3><button class="p" style="width:100%" onclick="closeModal()">' + t("ok") + '</button>'); break;
    case "collect": beep(); modal('<h3>📥 ' + t("collectH") + '</h3><p>' + t("collectP") + ' <b>' + esc(m.title) + '</b></p><div class="row"><button class="p" id="cf">' + t("chooseFile") + '</button><button class="w" id="cp">' + t("takePhoto") + '</button></div><div style="height:8px"></div><button style="width:100%" onclick="closeModal()">' + t("cancel") + '</button>', b => {
      b.querySelector("#cf").onclick = () => { closeModal(); $("fileIn").click(); }; b.querySelector("#cp").onclick = () => { closeModal(); $("camIn").click(); }; }); break;
    case "hand_down": hand = false; $("handBtn").classList.remove("on"); applyLang(); break;
    case "file_begin": recv[m.fid] = {name:m.name || "file", parts:[]}; toast("📁 " + (m.name || "")); break;
    case "file_end": fileDone(m.fid); break;
    case "up_ack": { const u = ups[m.fid]; if(u){ u.acked = Math.max(u.acked, m.n); pump(m.fid); } break; }
    case "up_ok": delete ups[m.fid]; toast(t("uploaded") + " " + (m.name || ""), 4000); break;
    case "up_reject": delete ups[m.fid]; toast(t("rejected")); break;
  }
}
applyLang();
if(params.get("c") && $("name").value) $("joinBtn").onclick();
</script></body></html>
"""

REMOTE_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0B3B5C">
<link rel="icon" href="/icon.png"><link rel="apple-touch-icon" href="/icon.png">
<title>Sabbora Remote</title>
<style>""" + _COMMON_CSS + r"""
body{padding-bottom:20px}
#preview{background:#0B1220;border-radius:14px;margin:12px;min-height:120px;display:flex;align-items:center;justify-content:center;overflow:hidden}
#preview img{max-width:100%;max-height:34vh;display:none}
#preview span{color:#9FB3AA;padding:24px;text-align:center}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 12px}
.grid button{padding:16px 8px;font-size:15px;font-weight:600;border-radius:14px}
.big{font-size:22px!important;padding:26px 8px!important}
.chips{display:flex;gap:8px;margin:10px 12px;flex-wrap:wrap}
.chips button{flex:1;min-width:60px}
h4{margin:16px 14px 6px;color:#0B3B5C}
#stat{margin:0 12px;font-size:14px;display:flex;gap:12px;flex-wrap:wrap}
#stat b{color:#0B3B5C}
#events{margin:6px 12px;background:#fff;border:1px solid var(--border);border-radius:12px;padding:6px 10px;font-size:14px;max-height:30vh;overflow:auto}
#events div{padding:6px 0;border-bottom:1px solid #EEF2F6}
</style></head><body>
<header><img src="/icon.png" alt=""><div><div class="t" data-i="title"></div><div class="s" id="sub"></div></div>
<div style="flex:1"></div><button class="hb" id="langBtn"></button></header>

<section id="login" class="card">
  <h3 style="margin-top:0;color:#0B3B5C" data-i="loginH"></h3>
  <p class="muted" data-i="loginP"></p>
  <input id="pin" inputmode="numeric" maxlength="8">
  <div style="height:12px"></div><button class="p" id="goBtn" style="width:100%"></button>
  <p class="err" id="err"></p>
</section>

<section id="ui" style="display:none">
  <div id="preview"><span data-i="noShare"></span><img id="pv" alt=""></div>
  <div id="stat"></div>
  <h4 data-i="slides"></h4>
  <div class="grid">
    <button class="big" data-c="prev">◀ <span data-i="prev"></span></button>
    <button class="big p" data-c="next"><span data-i="next"></span> ▶</button>
  </div>
  <h4 data-i="share"></h4>
  <div class="grid">
    <button class="p" data-c="share">▶ <span data-i="start"></span></button>
    <button class="d" data-c="stop">⏹ <span data-i="stop"></span></button>
    <button data-c="freeze">⏸ <span data-i="freeze"></span></button>
    <button data-c="black">⬛ <span data-i="black"></span></button>
    <button class="w" id="photoBtn" style="grid-column:span 2">📷 <span data-i="photo"></span></button>
  </div>
  <h4 data-i="class"></h4>
  <div class="grid">
    <button class="w" data-c="lock">🔒 <span data-i="lock"></span></button>
    <button data-c="unlock">🔓 <span data-i="unlock"></span></button>
    <button data-c="pick">🎲 <span data-i="pick"></span></button>
    <button data-c="hands_down">✋ <span data-i="handsDown"></span></button>
  </div>
  <h4 data-i="timer"></h4>
  <div class="chips">
    <button data-t="1">1</button><button data-t="3">3</button><button data-t="5">5</button><button data-t="10">10</button><button data-t="15">15</button>
    <button class="d" data-c="timer_stop">⏹</button>
  </div>
  <h4 data-i="events"></h4>
  <div id="events"></div>
</section>
<input type="file" id="camIn" accept="image/*" capture="environment" hidden>
<div class="toast" id="toast"></div>

<script>
const WS_PORT = %%WS_PORT%%, VERSION = "%%VERSION%%";
const TXT = {
 ar:{title:"سبّورة — جهاز التحكم",loginH:"تحكم المحاضر من الهاتف",loginP:"اكتب الرمز السري الظاهر في نافذة «الهواتف» على جهاز المحاضر.",
  go:"دخول",badPin:"الرمز السري غير صحيح.",slides:"الشرائح",prev:"السابق",next:"التالي",share:"البث",start:"بث الشاشة",stop:"إيقاف",
  freeze:"تجميد",black:"شاشة سوداء",photo:"صوّر واعرض على الصف",class:"الصف",lock:"قفل الشاشات",unlock:"فتح",pick:"طالب عشوائي",
  handsDown:"إنزال الأيدي",timer:"مؤقت (دقائق)",events:"الأيدي والأسئلة",noShare:"لا يوجد بث الآن",online:"متصل",hands:"أيدٍ مرفوعة",
  sharing:"البث يعمل",frozen:"مجمّد",photoOn:"تُعرض صورة",lost:"انقطع الاتصال — إعادة المحاولة…",sent:"تم",uploading:"جارٍ رفع الصورة",lang:"English"},
 en:{title:"Sabbora — Remote",loginH:"Teacher remote on your phone",loginP:"Type the secret PIN shown in the «Phones» window on the teacher PC.",
  go:"Enter",badPin:"Wrong PIN.",slides:"Slides",prev:"Previous",next:"Next",share:"Sharing",start:"Share screen",stop:"Stop",
  freeze:"Freeze",black:"Black screen",photo:"Take a photo and show it to the class",class:"Class",lock:"Lock screens",unlock:"Unlock",pick:"Random student",
  handsDown:"Lower hands",timer:"Timer (minutes)",events:"Hands and questions",noShare:"Nothing is being shared",online:"online",hands:"hands up",
  sharing:"sharing",frozen:"frozen",photoOn:"showing a photo",lost:"Connection lost — retrying…",sent:"Done",uploading:"Uploading photo",lang:"العربية"}};
const $ = id => document.getElementById(id);
function store(k, v){ try{ if(v===undefined) return localStorage.getItem(k); localStorage.setItem(k, v); }catch(e){ return null; } }
let LANG = store("sb_lang") || ((navigator.language||"").toLowerCase().startsWith("ar") ? "ar" : "%%LANG%%");
const t = k => { const d = TXT[LANG] || TXT.en; return (k in d) ? d[k] : k; };
function applyLang(){ document.documentElement.lang = LANG; document.documentElement.dir = LANG === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i]").forEach(e => e.textContent = t(e.dataset.i)); $("goBtn").textContent = t("go"); $("langBtn").textContent = "🌐 " + t("lang"); }
$("langBtn").onclick = () => { LANG = LANG === "ar" ? "en" : "ar"; store("sb_lang", LANG); applyLang(); render(); };
function toast(msg, ms){ const e = $("toast"); e.textContent = msg; e.style.display = "block"; clearTimeout(toast.h); toast.h = setTimeout(() => e.style.display = "none", ms || 2000); }
function esc(s){ return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

const hp = new URLSearchParams(location.hash.slice(1));
$("pin").value = hp.get("pin") || "";
let rid = store("sb_rid"); if(!rid){ rid = "r-" + Math.random().toString(36).slice(2, 10); store("sb_rid", rid); }
let ws = null, want = false, ok = false, state = {};
function send(o){ if(ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
$("goBtn").onclick = () => { if(!$("pin").value.trim()) return; want = true; connect(); };
function connect(){
  ws = new WebSocket("ws://" + location.hostname + ":" + WS_PORT + "/"); ws.binaryType = "arraybuffer";
  ws.onopen = () => send({t:"hello", role:"remote", pin:$("pin").value.trim(), id:rid, name:"remote", kind:"remote", ver:VERSION});
  ws.onmessage = e => {
    if(typeof e.data !== "string"){ const d = new Uint8Array(e.data); if(d[0] === 1) frame(d.subarray(1)); return; }
    let m; try{ m = JSON.parse(e.data); }catch(x){ return; }
    if(m.t === "welcome_remote"){ ok = true; $("login").style.display = "none"; $("ui").style.display = "block"; $("err").textContent = ""; }
    else if(m.t === "reject"){ want = false; $("err").textContent = t("badPin"); }
    else if(m.t === "state"){ state = m; render(); }
    else if(m.t === "up_ack"){ const u = ups[m.fid]; if(u){ u.acked = Math.max(u.acked, m.n); pump(m.fid); } }
    else if(m.t === "up_ok"){ delete ups[m.fid]; toast("📷 " + t("photoOn")); }
    else if(m.t === "bstop"){ $("pv").style.display = "none"; }
  };
  ws.onclose = () => { ok = false; if(want){ toast(t("lost")); setTimeout(() => want && connect(), 3000); } };
}
let lastUrl = null;
function frame(bytes){ const url = URL.createObjectURL(new Blob([bytes], {type:"image/jpeg"})); const img = $("pv");
  img.onload = () => { if(lastUrl) URL.revokeObjectURL(lastUrl); lastUrl = url; send({t:"ack_b"}); }; img.onerror = () => send({t:"ack_b"});
  img.src = url; img.style.display = "block"; }
function render(){
  $("sub").textContent = state.course || "";
  const s = [];
  s.push("👥 <b>" + (state.online || 0) + "</b> " + t("online")); s.push("✋ <b>" + (state.hands || []).length + "</b> " + t("hands"));
  if(state.sharing) s.push("📺 " + t("sharing") + (state.frozen ? " (" + t("frozen") + ")" : "")); if(state.photo) s.push("📷 " + t("photoOn"));
  if(state.timer_left > 0) s.push("⏱ " + String(Math.floor(state.timer_left / 60)).padStart(2, "0") + ":" + String(state.timer_left % 60).padStart(2, "0"));
  $("stat").innerHTML = s.join(" · ");
  const ev = (state.hands || []).map(n => "<div>✋ " + esc(n) + "</div>").concat((state.chat || []).map(c => "<div>💬 " + esc(c) + "</div>"));
  $("events").innerHTML = ev.join("") || '<div class="muted">—</div>';
  if(!state.sharing){ $("pv").style.display = "none"; }
}
document.querySelectorAll("[data-c]").forEach(b => b.onclick = () => { send({t:"cmd", c:b.dataset.c}); if(navigator.vibrate) navigator.vibrate(30); });
document.querySelectorAll("[data-t]").forEach(b => b.onclick = () => { send({t:"cmd", c:"timer", min:+b.dataset.t}); toast("⏱ " + b.dataset.t); });

let upId = 0; const ups = {};
$("photoBtn").onclick = () => $("camIn").click();
$("camIn").onchange = e => { const f = e.target.files[0]; e.target.value = ""; if(!f || !ok) return;
  const fid = ++upId, CH = 262144; ups[fid] = {file:f, chunks:Math.ceil(f.size / CH), next:0, acked:0, sending:false};
  send({t:"up_begin", fid:fid, name:f.name || "photo.jpg", size:f.size, chunks:ups[fid].chunks, purpose:"show"}); toast(t("uploading"), 4000); pump(fid); };
async function pump(fid){ const u = ups[fid]; if(!u || u.sending) return; u.sending = true; const CH = 262144;
  while(u.next < u.chunks && u.next - u.acked < 8){ const buf = new Uint8Array(await u.file.slice(u.next * CH, (u.next + 1) * CH).arrayBuffer());
    const msg = new Uint8Array(9 + buf.length), v = new DataView(msg.buffer); msg[0] = 0x12; v.setUint32(1, fid); v.setUint32(5, u.next); msg.set(buf, 9); ws.send(msg); u.next++; }
  u.sending = false; if(u.acked >= u.chunks) send({t:"up_end", fid:fid}); }
applyLang();
if($("pin").value) $("goBtn").onclick();
</script></body></html>
"""
