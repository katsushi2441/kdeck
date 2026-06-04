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
if (isset($_GET['api']) && $_GET['api'] === 'ticket') {
    header('Content-Type: application/json; charset=UTF-8');
    $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
    echo json_encode(kdeck_api('POST', '/api/sessions/' . rawurlencode($id) . '/ticket'), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'raw') {
    header('Content-Type: application/json; charset=UTF-8');
    $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
    $payload = json_decode(file_get_contents('php://input') ?: '{}', true);
    $text = is_array($payload) && isset($payload['text']) ? (string)$payload['text'] : '';
    echo json_encode(kdeck_api('POST', '/api/sessions/' . rawurlencode($id) . '/send', ['text' => $text, 'enter' => false]), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'chat') {
    header('Content-Type: application/json; charset=UTF-8');
    $payload = json_decode(file_get_contents('php://input') ?: '{}', true);
    echo json_encode(kdeck_api('POST', '/api/chat', is_array($payload) ? $payload : []), JSON_UNESCAPED_UNICODE);
    exit;
}

$message = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';
    if ($action === 'create') {
        $res = kdeck_api('POST', '/api/sessions', [
            'name' => $_POST['name'] ?? 'codex',
            'cwd' => $_POST['cwd'] ?? '/home/kojima/work/url2ai',
            'command' => $_POST['command'] ?? '',
        ]);
        $message = !empty($res['ok']) ? 'session created: ' . ($res['id'] ?? '') : 'error: ' . json_encode($res, JSON_UNESCAPED_UNICODE);
    } elseif ($action === 'send') {
        $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_POST['id'] ?? '');
        $res = kdeck_api('POST', '/api/sessions/' . rawurlencode($id) . '/send', ['text' => $_POST['text'] ?? '', 'enter' => true]);
        $message = !empty($res['ok']) ? 'sent' : 'error: ' . json_encode($res, JSON_UNESCAPED_UNICODE);
    } elseif ($action === 'interrupt') {
        $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_POST['id'] ?? '');
        $res = kdeck_api('POST', '/api/sessions/' . rawurlencode($id) . '/interrupt');
        $message = !empty($res['ok']) ? 'interrupt sent' : 'error: ' . json_encode($res, JSON_UNESCAPED_UNICODE);
    } elseif ($action === 'terminate') {
        $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_POST['id'] ?? '');
        $res = kdeck_api('POST', '/api/sessions/' . rawurlencode($id) . '/terminate');
        $message = !empty($res['ok']) ? 'terminated' : 'error: ' . json_encode($res, JSON_UNESCAPED_UNICODE);
    }
}
$sessions = kdeck_api('GET', '/api/sessions');
$config = kdeck_api('GET', '/api/config');
$roots = $config['allowed_roots'] ?? ['/home/kojima/work/url2ai'];
$codex_cmd = $config['codex_cmd'] ?? 'codex';
$codex_model = $config['codex_model'] ?? 'gpt-5.4-mini';
$active = $_GET['id'] ?? (($sessions['sessions'][0]['id'] ?? '') ?: '');
?><!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kurage Agent Deck</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css">
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js"></script>
<style>
body{margin:0;background:#f4f7f9;color:#18252d;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}header{position:sticky;top:0;background:#fff;border-bottom:1px solid #d8e2e8;z-index:2}.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px}.brand{font-weight:900}.wrap{display:grid;grid-template-columns:310px 1fr;gap:14px;padding:14px}.panel{background:#fff;border:1px solid #d8e2e8;border-radius:8px;padding:12px}.session{display:block;padding:10px;border-bottom:1px solid #e3ebef;color:inherit;text-decoration:none}.session.active{background:#e8f6fb}.muted{color:#64727c;font-size:12px}.logout{color:#0b75a5;font-weight:800;text-decoration:none}.msg{margin:0 14px;padding:10px;background:#fff7df;border:1px solid #ecd28b;border-radius:6px}.row{display:grid;gap:8px;margin-bottom:8px}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;box-sizing:border-box;border:1px solid #c8d5dc;border-radius:6px;padding:8px}button{min-height:38px;border:0;border-radius:6px;background:#0b75a5;color:#fff;font-weight:800;padding:8px 12px}.danger{background:#bb3e3e}.chatlog{display:flex;flex-direction:column;gap:12px;min-height:58vh;max-height:64vh;overflow:auto;padding:4px}.bubble{max-width:92%;border-radius:8px;padding:10px 12px;white-space:pre-wrap;line-height:1.55}.user{align-self:flex-end;background:#dff0f7}.assistant{align-self:flex-start;background:#f0f4f7}.composer{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:10px}.console{background:#08151d;border-radius:8px;height:42vh;overflow:hidden;padding:6px}.sendbox{display:grid;grid-template-columns:1fr auto auto auto;gap:8px;margin-top:10px}.xterm{height:42vh}.xterm-viewport{border-radius:6px}.fallback{white-space:pre-wrap;color:#d8f3ff;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;line-height:1.45}.terminal-block{margin-top:14px}.terminal-block summary{cursor:pointer;font-weight:800;color:#0b75a5}@media(max-width:820px){.wrap{grid-template-columns:1fr}.chatlog{min-height:52vh}.composer{grid-template-columns:1fr}.sendbox{grid-template-columns:1fr}.bar{align-items:flex-start;flex-direction:column}}
</style></head><body><header><div class="bar"><div class="brand">Kurage Agent Deck</div><div class="muted">@<?=h($session_user)?> · <a class="logout" href="<?=h($logout_url)?>">Logout</a></div></div></header>
<?php if ($message): ?><div class="msg"><?=h($message)?></div><?php endif; ?>
<div class="wrap"><aside class="panel"><h2>Chat</h2>
<div class="row"><label class="muted">Folder</label><select id="chat-cwd"><?php foreach ($roots as $r): ?><option value="<?=h($r)?>"><?=h($r)?></option><?php endforeach; ?></select></div>
<div class="row"><label class="muted">Model</label><input id="chat-model" value="<?=h($codex_model)?>"></div>
<button type="button" id="new-chat">New Chat</button>
<h2>Terminal</h2>
<?php foreach (($sessions['sessions'] ?? []) as $s): ?><a class="session <?=($active===$s['id']?'active':'')?>" href="?id=<?=h($s['id'])?>"><b><?=h($s['name'])?></b><div class="muted"><?=h($s['id'])?></div></a><?php endforeach; ?>
<h2>New</h2><form method="post"><input type="hidden" name="action" value="create"><input type="hidden" name="name" value="codex"><div class="row"><label class="muted">Folder</label><select name="cwd"><?php foreach ($roots as $r): ?><option value="<?=h($r)?>"><?=h($r)?></option><?php endforeach; ?></select></div><div class="row"><label class="muted">Command</label><input name="command" value="<?=h($codex_cmd)?>" placeholder="command"></div><button type="submit">Start</button></form></aside>
<main class="panel"><h2>Codex Chat</h2><div id="chatlog" class="chatlog"><div class="bubble assistant">フォルダを選んで、下の入力欄からCodexに指示できます。</div></div>
<form id="chat-form" class="composer"><textarea id="chat-input" rows="4" placeholder="Codexへ送る指示"></textarea><button type="submit">Send</button></form>
<details class="terminal-block" <?= $active ? 'open' : '' ?>><summary>Terminal <?=h($active ?: '')?></summary><div id="console" class="console"><div id="terminal"></div><pre id="fallback" class="fallback">loading...</pre></div>
<?php if ($active): ?><form class="sendbox" method="post"><input type="hidden" name="action" value="send"><input type="hidden" name="id" value="<?=h($active)?>"><textarea name="text" rows="3" placeholder="Codex CLI terminalへ送る入力"></textarea><button type="submit">Send</button><button class="danger" type="submit" name="action" value="interrupt">Ctrl+C</button><button class="danger" type="submit" name="action" value="terminate">Stop</button></form><?php endif; ?></details></main></div>
<script>
const active = <?=json_encode($active)?>;
let renderedLength = 0;
let chatThread = '';
const chatlog = document.getElementById('chatlog');
function addBubble(role, text){
  const div = document.createElement('div');
  div.className = 'bubble ' + role;
  div.textContent = text;
  chatlog.appendChild(div);
  chatlog.scrollTop = chatlog.scrollHeight;
  return div;
}
document.getElementById('new-chat').addEventListener('click', () => {
  chatThread = '';
  chatlog.innerHTML = '';
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
  const res = await fetch('?api=chat', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({prompt, thread_id:chatThread, cwd:document.getElementById('chat-cwd').value, model:document.getElementById('chat-model').value})
  });
  const data = await res.json();
  if(data.thread_id) chatThread = data.thread_id;
  pending.textContent = data.message || JSON.stringify(data, null, 2);
  chatlog.scrollTop = chatlog.scrollHeight;
});
async function connectTerminal(){
  if(!active) return;
  const fallback = document.getElementById('fallback');
  if(!window.Terminal){
    fallback.textContent = 'xterm.js failed to load';
    return;
  }
  fallback.style.display = 'none';
  const term = new Terminal({cursorBlink:true,convertEol:false,fontSize:13,theme:{background:'#08151d',foreground:'#d8f3ff'}});
  term.open(document.getElementById('terminal'));
  term.focus();
  term.onData(data => {
    fetch('?api=raw&id=' + encodeURIComponent(active), {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:data})
    }).catch(()=>{});
  });
  async function poll(){
    const res = await fetch('?api=capture&id=' + encodeURIComponent(active), {cache:'no-store'});
    const data = await res.json();
    const text = data.text || '';
    if(text.length < renderedLength){
      term.reset();
      renderedLength = 0;
    }
    if(text.length > renderedLength){
      term.write(text.slice(renderedLength));
      renderedLength = text.length;
    }
    if(data.alive !== false) setTimeout(poll, 250);
  }
  poll();
}
connectTerminal();
</script></body></html>
