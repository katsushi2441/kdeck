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
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f7f9;color:#18252d;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.box{width:min(420px,calc(100vw - 28px));background:#fff;border:1px solid #d8e2e8;border-radius:8px;padding:18px;box-sizing:border-box}h1{font-size:22px;margin:0 0 8px}.lead{margin:0 0 16px;color:#64727c;font-size:14px;line-height:1.6}.btn{display:block;width:100%;box-sizing:border-box;border-radius:6px;background:#0b75a5;color:#fff;text-decoration:none;text-align:center;font-weight:800;padding:11px 12px}.error{margin:0 0 12px;padding:9px;border:1px solid #e0a0a0;background:#fff1f1;border-radius:6px;color:#8d2525}.muted{margin-top:12px;color:#64727c;font-size:12px}
</style></head><body><main class="box"><h1>Kurage Agent Deck</h1><?php if ($message): ?><p class="error"><?=h($message)?></p><?php endif; ?><p class="lead">kurage.exbridge.jp の共通Xログインで利用します。</p><a class="btn" href="<?=h($login_url)?>">Xでログイン</a><div class="muted">kdeck.php</div></main></body></html><?php
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

$config = kdeck_api('GET', '/api/config');
$roots = $config['allowed_roots'] ?? ['/home/kojima/work/url2ai'];
$codex_model = $config['codex_model'] ?? 'gpt-5.4-mini';
?><!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kurage Agent Deck</title>
<style>
	body{margin:0;background:#f4f7f9;color:#18252d;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}header{position:sticky;top:0;background:#fff;border-bottom:1px solid #d8e2e8;z-index:2}.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px}.brand{font-weight:900}.wrap{display:grid;grid-template-columns:310px 1fr;gap:14px;padding:14px}.panel{background:#fff;border:1px solid #d8e2e8;border-radius:8px;padding:12px}.muted{color:#64727c;font-size:12px}.logout{color:#0b75a5;font-weight:800;text-decoration:none}.row{display:grid;gap:8px;margin-bottom:8px}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;box-sizing:border-box;border:1px solid #c8d5dc;border-radius:6px;padding:8px}button{min-height:38px;border:0;border-radius:6px;background:#0b75a5;color:#fff;font-weight:800;padding:8px 12px}button.secondary{background:#e7eef2;color:#18252d}button.active{background:#b03a2e;color:#fff}button:disabled{cursor:not-allowed;opacity:.55}.chatlog{display:flex;flex-direction:column;gap:12px;min-height:64vh;max-height:70vh;overflow:auto;padding:4px}.bubble{max-width:92%;border-radius:8px;padding:10px 12px;white-space:pre-wrap;line-height:1.55}.user{align-self:flex-end;background:#dff0f7}.assistant{align-self:flex-start;background:#f0f4f7}.voicebar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}.voicebar label{display:flex;align-items:center;gap:6px}.voicebar input{width:auto}.composer{display:grid;grid-template-columns:1fr auto auto;gap:8px;margin-top:10px}@media(max-width:820px){.wrap{grid-template-columns:1fr}.chatlog{min-height:58vh}.composer{grid-template-columns:1fr 1fr}.composer textarea{grid-column:1/-1}.bar{align-items:flex-start;flex-direction:column}}
</style></head><body><header><div class="bar"><div class="brand">Kurage Agent Deck</div><div class="muted">@<?=h($session_user)?> · <a class="logout" href="<?=h($logout_url)?>">Logout</a></div></div></header>
<div class="wrap"><aside class="panel"><h2>Chat</h2>
<div class="row"><label class="muted">Folder</label><select id="chat-cwd"><?php foreach ($roots as $r): ?><option value="<?=h($r)?>"><?=h($r)?></option><?php endforeach; ?></select></div>
<div class="row"><label class="muted">Model</label><input id="chat-model" value="<?=h($codex_model)?>"></div>
<button type="button" id="new-chat">New Chat</button>
</aside>
	<main class="panel"><h2>Codex Chat</h2><div id="chatlog" class="chatlog"><div class="bubble assistant">フォルダを選んで、下の入力欄からCodexに指示できます。コマンド実行も会話の中で依頼してください。</div></div>
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
	  chatlog.innerHTML = '';
	  if(canSpeak) window.speechSynthesis.cancel();
	  addBubble('assistant', '新しいチャットを開始しました。');
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
	  const res = await fetch('?api=chat', {
	    method:'POST',
	    headers:{'Content-Type':'application/json'},
	    body:JSON.stringify({prompt, thread_id:chatThread, cwd:folderSelect.value, model:modelInput.value})
	  });
	  const data = await res.json();
	  if(data.thread_id) chatThread = data.thread_id;
	  if(!data.job_id){
	    pending.textContent = data.message || JSON.stringify(data, null, 2);
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
	    speakText(pending.textContent);
	  }
	  pollChat();
	});
</script></body></html>
