<?php
require_once __DIR__ . '/auth_common.php';
date_default_timezone_set('Asia/Tokyo');

$KDECK_API_BASE = getenv('KDECK_API_BASE') ?: 'http://exbridge.ddns.net:18301';
$KDECK_TOKEN = getenv('KDECK_TOKEN') ?: 'change-this-token';
$KDECK_RETURN_URL = 'https://kurage.exbridge.jp/kdeck.php';
$auth = url2ai_auth_bootstrap();
$logged_in = !empty($auth['logged_in']);
$session_user = isset($auth['session_user']) ? $auth['session_user'] : '';
$is_admin = !empty($auth['is_admin']);
$login_url = url2ai_auth_login_url($KDECK_RETURN_URL);
$logout_url = url2ai_auth_logout_url($KDECK_RETURN_URL);

function kdeck_api($method, $path, $payload = null) {
    global $KDECK_API_BASE, $KDECK_TOKEN;
    $headers = "Authorization: Bearer {$KDECK_TOKEN}\r\nAccept: application/json\r\n";
    $body = '';
    if ($payload !== null) {
        $body = json_encode($payload, JSON_UNESCAPED_UNICODE);
        $headers .= "Content-Type: application/json; charset=utf-8\r\n";
    }
    $opts = ['http' => [
        'method' => $method,
        'header' => $headers,
        'content' => $body,
        'timeout' => 20,
        'ignore_errors' => true,
    ]];
    $raw = @file_get_contents(rtrim($KDECK_API_BASE, '/') . $path, false, stream_context_create($opts));
    $data = $raw ? json_decode($raw, true) : null;
    return is_array($data) ? $data : ['ok' => false, 'error' => $raw ?: 'request failed'];
}
function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }

function render_login($login_url, $message = '') {
?><!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kurage Agent Deck Login</title>
<meta name="description" content="Kurage Agent Deck is a mobile web console for Codex CLI sessions.">
<meta property="og:title" content="Kurage Agent Deck">
<meta property="og:description" content="スマホからCodex CLIを操作するKurageのAIエージェントデッキ">
<meta property="og:image" content="https://kurage.exbridge.jp/images/kdeck.png">
<meta property="og:image:width" content="1536">
<meta property="og:image:height" content="1024">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://kurage.exbridge.jp/images/kdeck.png">
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f7f9;color:#18252d;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.box{width:min(420px,calc(100vw - 28px));background:#fff;border:1px solid #d8e2e8;border-radius:8px;padding:18px;box-sizing:border-box}.login-brand{display:flex;align-items:center;gap:10px;margin-bottom:10px}.login-brand img{width:44px;height:44px;border-radius:50%;object-fit:cover;box-shadow:0 2px 8px rgba(0,127,150,.18)}h1{font-size:22px;margin:0}.lead{margin:0 0 16px;color:#64727c;font-size:14px;line-height:1.6}.btn{display:block;width:100%;box-sizing:border-box;border-radius:6px;background:#0b75a5;color:#fff;text-decoration:none;text-align:center;font-weight:800;padding:11px 12px}.error{margin:0 0 12px;padding:9px;border:1px solid #e0a0a0;background:#fff1f1;border-radius:6px;color:#8d2525}.muted{margin-top:12px;color:#64727c;font-size:12px}
</style></head><body><main class="box"><div class="login-brand"><img src="/images/kdeck.png" alt="Kurage"><h1>Kurage Agent Deck</h1></div><?php if ($message): ?><p class="error"><?=h($message)?></p><?php endif; ?><p class="lead">kurage.exbridge.jp の共通Xログインで利用します。</p><a class="btn" href="<?=h($login_url)?>">Xでログイン</a><div class="muted">kdeck.php</div></main></body></html><?php
}

if (!$logged_in) {
    render_login($login_url);
    exit;
}
if (!$is_admin) {
    render_login($login_url, '@' . $session_user . ' is not allowed');
    exit;
}

if (isset($_GET['api']) && $_GET['api'] === 'capture') {
    header('Content-Type: application/json; charset=UTF-8');
    $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
    echo json_encode(kdeck_api('GET', '/api/sessions/' . rawurlencode($id) . '/capture?lines=1200'), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'chat') {
    header('Content-Type: application/json; charset=UTF-8');
    $payload = json_decode(file_get_contents('php://input') ?: '{}', true);
    echo json_encode(kdeck_api('POST', '/api/chat', is_array($payload) ? $payload : []), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'chat_job') {
    header('Content-Type: application/json; charset=UTF-8');
    $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
    echo json_encode(kdeck_api('GET', '/api/chat/' . rawurlencode($id)), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'chat_threads') {
    header('Content-Type: application/json; charset=UTF-8');
    echo json_encode(kdeck_api('GET', '/api/chat_threads'), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'chat_thread') {
    header('Content-Type: application/json; charset=UTF-8');
    $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
    echo json_encode(kdeck_api('GET', '/api/chat_threads/' . rawurlencode($id)), JSON_UNESCAPED_UNICODE);
    exit;
}

$config = kdeck_api('GET', '/api/config');
$roots = $config['allowed_roots'] ?? ['/home/kojima/work/url2ai'];
$codex_model = $config['codex_model'] ?? 'gpt-5.4-mini';
?><!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kurage Agent Deck</title>
<meta name="description" content="Kurage Agent Deck is a mobile web console for Codex CLI sessions.">
<meta property="og:title" content="Kurage Agent Deck">
<meta property="og:description" content="スマホからCodex CLIを操作するKurageのAIエージェントデッキ">
<meta property="og:image" content="https://kurage.exbridge.jp/images/kdeck.png">
<meta property="og:image:width" content="1536">
<meta property="og:image:height" content="1024">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://kurage.exbridge.jp/images/kdeck.png">
<style>
	:root{--bg:#eef4f6;--panel:#ffffff;--line:#d5e1e6;--text:#17242c;--muted:#60717b;--brand:#087d9a;--brand2:#0f9b8e;--soft:#e9f5f6;--danger:#b03a2e}
	*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}header{position:sticky;top:0;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);z-index:2;backdrop-filter:blur(10px)}.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px}.brand{display:flex;align-items:center;gap:10px;font-weight:900}.brand-icon{width:42px;height:42px;border-radius:50%;object-fit:cover;box-shadow:0 2px 8px rgba(0,127,150,.18)}.brand-title{display:grid;line-height:1.15}.brand-title span{font-size:12px;color:var(--muted);font-weight:700}.wrap{display:grid;grid-template-columns:320px 1fr;gap:12px;padding:12px;height:calc(100vh - 64px)}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-height:0}.side{display:flex;flex-direction:column;overflow:hidden}.side-top{padding:12px;border-bottom:1px solid var(--line)}.main{display:flex;flex-direction:column;padding:0;overflow:hidden}.main-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-bottom:1px solid var(--line)}h2{font-size:16px;margin:0}.muted{color:var(--muted);font-size:12px}.logout{color:var(--brand);font-weight:800;text-decoration:none}.row{display:grid;gap:6px;margin-bottom:8px}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;border:1px solid #c8d5dc;border-radius:6px;padding:8px;background:#fff}button{min-height:36px;border:0;border-radius:6px;background:var(--brand);color:#fff;font-weight:800;padding:8px 12px;cursor:pointer}button.secondary{background:#e7eef2;color:var(--text)}button.active{background:var(--danger);color:#fff}button:disabled{cursor:not-allowed;opacity:.55}.history{overflow:auto;padding:8px;display:flex;flex-direction:column;gap:6px}.history-item{border:1px solid transparent;background:transparent;color:var(--text);text-align:left;font-weight:700;min-height:0;padding:9px;border-radius:6px}.history-item:hover,.history-item.active{background:var(--soft);border-color:#c5dde3}.history-title{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-meta{display:block;color:var(--muted);font-size:11px;font-weight:600;margin-top:3px}.chatlog{display:flex;flex-direction:column;gap:12px;flex:1;overflow:auto;padding:14px}.bubble{max-width:92%;border-radius:8px;padding:10px 12px;white-space:pre-wrap;line-height:1.55}.user{align-self:flex-end;background:#dff0f7}.assistant{align-self:flex-start;background:#f0f4f7}.voicebar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 14px;border-top:1px solid var(--line)}.voicebar label{display:flex;align-items:center;gap:6px}.voicebar input{width:auto}.composer{display:grid;grid-template-columns:1fr auto auto;gap:8px;padding:0 14px 14px}.composer textarea{resize:vertical;min-height:82px}.empty-history{padding:10px;color:var(--muted);font-size:12px}@media(max-width:820px){.wrap{grid-template-columns:1fr;height:auto}.side{max-height:38vh}.main{min-height:62vh}.composer{grid-template-columns:1fr 1fr}.composer textarea{grid-column:1/-1}.bar{align-items:flex-start;flex-direction:column}}
</style></head><body><header><div class="bar"><div class="brand"><img class="brand-icon" src="/images/kdeck.png" alt="Kurage"><span class="brand-title"><b>Kurage Agent Deck</b><span>Codex CLI web console</span></span></div><div class="muted">@<?=h($session_user)?> · <a class="logout" href="<?=h($logout_url)?>">Logout</a></div></div></header>
<div class="wrap"><aside class="panel side"><div class="side-top"><h2>Chat</h2>
<div class="row"><label class="muted">Folder</label><select id="chat-cwd"><?php foreach ($roots as $r): ?><option value="<?=h($r)?>"><?=h($r)?></option><?php endforeach; ?></select></div>
<div class="row"><label class="muted">Model</label><input id="chat-model" value="<?=h($codex_model)?>"></div>
<button type="button" id="new-chat">New Chat</button>
<div class="muted" style="margin-top:8px">履歴はサーバに保存されます。</div></div>
<div id="history" class="history"><div class="empty-history">履歴を読み込み中...</div></div>
</aside>
	<main class="panel main"><div class="main-head"><h2 id="chat-title">Codex Chat</h2><span class="muted" id="chat-state">ready</span></div><div id="chatlog" class="chatlog"><div class="bubble assistant">フォルダを選んで、下の入力欄からCodexに指示できます。コマンド実行も会話の中で依頼してください。</div></div>
	<div class="voicebar">
	  <button type="button" id="voice-input" class="secondary">🎙 Speak</button>
	  <button type="button" id="voice-stop" class="secondary">読み上げ停止</button>
	  <label class="muted"><input type="checkbox" id="voice-output"> 返答を読み上げ</label>
	  <span id="voice-status" class="muted"></span>
	</div>
	<form id="chat-form" class="composer"><textarea id="chat-input" rows="4" placeholder="Codexへ送る指示"></textarea><button type="submit">Send</button><button type="button" id="send-voice" class="secondary">音声送信</button></form>
</main></div>
<script>
	let chatThread = '';
	const chatlog = document.getElementById('chatlog');
	const historyList = document.getElementById('history');
	const chatTitle = document.getElementById('chat-title');
	const chatState = document.getElementById('chat-state');
	const folderSelect = document.getElementById('chat-cwd');
	const modelInput = document.getElementById('chat-model');
	const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
	const canSpeak = 'speechSynthesis' in window;
	const voiceInputButton = document.getElementById('voice-input');
	const voiceStopButton = document.getElementById('voice-stop');
	const sendVoiceButton = document.getElementById('send-voice');
	const voiceOutput = document.getElementById('voice-output');
	const voiceStatus = document.getElementById('voice-status');
	let recognition = null;
	let recognizing = false;
	let submitAfterVoice = false;
	const savedFolder = localStorage.getItem('kdeck.folder');
	const savedModel = localStorage.getItem('kdeck.model');
	if(savedFolder && [...folderSelect.options].some(option => option.value === savedFolder)){
	  folderSelect.value = savedFolder;
	}
	if(savedModel){
	  modelInput.value = savedModel;
	}
	folderSelect.addEventListener('change', () => localStorage.setItem('kdeck.folder', folderSelect.value));
	modelInput.addEventListener('change', () => localStorage.setItem('kdeck.model', modelInput.value));

	function fmtTime(ts){
	  if(!ts) return '';
	  const d = new Date(ts * 1000);
	  return d.toLocaleString('ja-JP', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
	}
	function setChatState(text){ chatState.textContent = text || 'ready'; }
	function setActiveHistory(){
	  historyList.querySelectorAll('.history-item').forEach(btn => {
	    btn.classList.toggle('active', btn.dataset.thread === chatThread);
	  });
	}
	async function loadHistory(){
	  try{
	    const res = await fetch('?api=chat_threads', {cache:'no-store'});
	    const data = await res.json();
	    const threads = data.threads || [];
	    historyList.innerHTML = '';
	    if(!threads.length){
	      historyList.innerHTML = '<div class="empty-history">まだ保存されたチャットはありません。</div>';
	      return;
	    }
	    threads.forEach(thread => {
	      const btn = document.createElement('button');
	      btn.type = 'button';
	      btn.className = 'history-item';
	      btn.dataset.thread = thread.id;
	      const title = document.createElement('span');
	      title.className = 'history-title';
	      title.textContent = thread.title || 'Untitled chat';
	      const meta = document.createElement('span');
	      meta.className = 'history-meta';
	      meta.textContent = [fmtTime(thread.updated), thread.cwd || '', thread.model || ''].filter(Boolean).join(' · ');
	      btn.appendChild(title);
	      btn.appendChild(meta);
	      btn.addEventListener('click', () => openThread(thread.id));
	      historyList.appendChild(btn);
	    });
	    setActiveHistory();
	  }catch(e){
	    historyList.innerHTML = '<div class="empty-history">履歴を読み込めませんでした。</div>';
	  }
	}
	async function openThread(id){
	  const res = await fetch('?api=chat_thread&id=' + encodeURIComponent(id), {cache:'no-store'});
	  const data = await res.json();
	  if(!data.ok || !data.thread) return;
	  const thread = data.thread;
	  chatThread = thread.id;
	  chatTitle.textContent = thread.title || 'Codex Chat';
	  if(thread.cwd && [...folderSelect.options].some(option => option.value === thread.cwd)){
	    folderSelect.value = thread.cwd;
	    localStorage.setItem('kdeck.folder', thread.cwd);
	  }
	  if(thread.model){
	    modelInput.value = thread.model;
	    localStorage.setItem('kdeck.model', thread.model);
	  }
	  chatlog.innerHTML = '';
	  (thread.messages || []).forEach(message => addBubble(message.role === 'user' ? 'user' : 'assistant', message.content || ''));
	  if(!(thread.messages || []).length) addBubble('assistant', '履歴は空です。');
	  setActiveHistory();
	  setChatState('loaded');
	}

	function setVoiceStatus(text){
	  voiceStatus.textContent = text || '';
	}
	function speakText(text){
	  if(!canSpeak || !voiceOutput.checked || !text) return;
	  window.speechSynthesis.cancel();
	  const utterance = new SpeechSynthesisUtterance(text);
	  utterance.lang = 'ja-JP';
	  utterance.rate = 1;
	  window.speechSynthesis.speak(utterance);
	}
	function submitChat(){
	  document.getElementById('chat-form').requestSubmit();
	}
	function addBubble(role, text){
	  const div = document.createElement('div');
	  div.className = 'bubble ' + role;
	  div.textContent = text;
	  chatlog.appendChild(div);
	  chatlog.scrollTop = chatlog.scrollHeight;
	  return div;
	}
	if(!SpeechRecognition){
	  voiceInputButton.disabled = true;
	  sendVoiceButton.disabled = true;
	  setVoiceStatus('このブラウザは音声入力に対応していません。');
	} else {
	  recognition = new SpeechRecognition();
	  recognition.lang = 'ja-JP';
	  recognition.interimResults = true;
	  recognition.continuous = false;
	  recognition.addEventListener('start', () => {
	    recognizing = true;
	    voiceInputButton.classList.add('active');
	    voiceInputButton.textContent = '聴取中...';
	    setVoiceStatus('話してください。');
	  });
	  recognition.addEventListener('end', () => {
	    recognizing = false;
	    voiceInputButton.classList.remove('active');
	    voiceInputButton.textContent = '🎙 Speak';
	    if(submitAfterVoice){
	      submitAfterVoice = false;
	      submitChat();
	    }
	  });
	  recognition.addEventListener('error', ev => {
	    submitAfterVoice = false;
	    setVoiceStatus(ev.error === 'not-allowed' ? 'マイクの使用が許可されていません。' : '音声入力でエラーが発生しました。');
	  });
	  recognition.addEventListener('result', ev => {
	    let interim = '';
	    let finalText = '';
	    for(let i = ev.resultIndex; i < ev.results.length; i++){
	      const transcript = ev.results[i][0].transcript;
	      if(ev.results[i].isFinal) finalText += transcript;
	      else interim += transcript;
	    }
	    const input = document.getElementById('chat-input');
	    if(finalText){
	      input.value = (input.value + finalText).trim();
	      setVoiceStatus('音声入力しました。');
	    } else if(interim) {
	      setVoiceStatus(interim);
	    }
	  });
	  voiceInputButton.addEventListener('click', () => {
	    if(recognizing) recognition.stop();
	    else recognition.start();
	  });
	  sendVoiceButton.addEventListener('click', () => {
	    const input = document.getElementById('chat-input');
	    if(input.value.trim()){
	      submitChat();
	      return;
	    }
	    submitAfterVoice = true;
	    if(recognizing) recognition.stop();
	    else recognition.start();
	  });
	}
	if(!canSpeak){
	  voiceOutput.disabled = true;
	  voiceStopButton.disabled = true;
	  if(!voiceStatus.textContent) setVoiceStatus('このブラウザは読み上げに対応していません。');
	}
	voiceStopButton.addEventListener('click', () => {
	  if(canSpeak) window.speechSynthesis.cancel();
	});
	document.getElementById('new-chat').addEventListener('click', () => {
	  chatThread = '';
	  chatTitle.textContent = 'Codex Chat';
	  chatlog.innerHTML = '';
	  if(canSpeak) window.speechSynthesis.cancel();
	  addBubble('assistant', '新しいチャットを開始しました。');
	  setChatState('ready');
	  setActiveHistory();
	});
	document.getElementById('chat-form').addEventListener('submit', async ev => {
	  ev.preventDefault();
	  const input = document.getElementById('chat-input');
	  const prompt = input.value.trim();
	  if(!prompt) return;
	  input.value = '';
	  addBubble('user', prompt);
	  const pending = addBubble('assistant', '実行中...');
	  localStorage.setItem('kdeck.folder', folderSelect.value);
	  localStorage.setItem('kdeck.model', modelInput.value);
	  setChatState('running');
	  const res = await fetch('?api=chat', {
	    method:'POST',
	    headers:{'Content-Type':'application/json'},
	    body:JSON.stringify({prompt, thread_id:chatThread, cwd:folderSelect.value, model:modelInput.value})
	  });
	  const data = await res.json();
	  if(data.thread_id) chatThread = data.thread_id;
	  setActiveHistory();
	  if(!data.job_id){
	    pending.textContent = data.message || JSON.stringify(data, null, 2);
	    setChatState('failed');
	    speakText(pending.textContent);
	    return;
	  }
	  async function pollChat(){
	    const jobRes = await fetch('?api=chat_job&id=' + encodeURIComponent(data.job_id), {cache:'no-store'});
	    const job = await jobRes.json();
	    if(job.status === 'running'){
	      pending.textContent = '実行中...';
	      setTimeout(pollChat, 1500);
	      return;
	    }
	    if(job.thread_id) chatThread = job.thread_id;
	    pending.textContent = job.message || job.error || JSON.stringify(job, null, 2);
	    chatlog.scrollTop = chatlog.scrollHeight;
	    chatTitle.textContent = prompt.length > 52 ? prompt.slice(0, 52) + '...' : prompt;
	    setChatState(job.status || 'finished');
	    loadHistory();
	    speakText(pending.textContent);
	  }
	  pollChat();
	});
	loadHistory();
</script></body></html>
