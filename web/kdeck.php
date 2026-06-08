<?php
require_once __DIR__ . '/auth_common.php';
date_default_timezone_set('Asia/Tokyo');

function kdeck_load_env_file($path) {
    if (!is_readable($path)) {
        return;
    }
    $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if (!is_array($lines)) {
        return;
    }
    foreach ($lines as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#' || strpos($line, '=') === false) {
            continue;
        }
        list($key, $value) = explode('=', $line, 2);
        $key = trim($key);
        $value = trim($value);
        if ($key === '' || !preg_match('/^[A-Z0-9_]+$/', $key)) {
            continue;
        }
        $first = substr($value, 0, 1);
        $last = substr($value, -1);
        if (($first === '"' && $last === '"') || ($first === "'" && $last === "'")) {
            $value = substr($value, 1, -1);
        }
        if (getenv($key) === false) {
            putenv($key . '=' . $value);
        }
        if (!isset($_ENV[$key])) {
            $_ENV[$key] = $value;
        }
    }
}

function kdeck_env($key, $default = '') {
    if (defined($key)) {
        $value = constant($key);
        if ($value !== '') {
            return $value;
        }
    }
    $value = getenv($key);
    if ($value !== false && $value !== '') {
        return $value;
    }
    return isset($_ENV[$key]) && $_ENV[$key] !== '' ? $_ENV[$key] : $default;
}

$KDECK_LOCAL_CONFIG = __DIR__ . '/kdeck_config.php';
if (is_readable($KDECK_LOCAL_CONFIG)) {
    require_once $KDECK_LOCAL_CONFIG;
}
kdeck_load_env_file(__DIR__ . '/kdeck.env');
kdeck_load_env_file(__DIR__ . '/.env');
kdeck_load_env_file(__DIR__ . '/../.env');

$KDECK_API_BASE = kdeck_env('KDECK_API_BASE', 'http://exbridge.ddns.net:18301');
$KDECK_TOKEN = kdeck_env('KDECK_TOKEN', 'change-this-token');
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
</style></head><body><main class="box"><div class="login-brand"><img src="/images/kurage-icon.png" alt="Kurage"><h1>Kurage Agent Deck</h1></div><?php if ($message): ?><p class="error"><?=h($message)?></p><?php endif; ?><p class="lead">kurage.exbridge.jp の共通Xログインで利用します。</p><a class="btn" href="<?=h($login_url)?>">Xでログイン</a><div class="muted">kdeck.php</div></main></body></html><?php
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
if (isset($_GET['api']) && $_GET['api'] === 'chat_cancel') {
    header('Content-Type: application/json; charset=UTF-8');
    $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
    echo json_encode(kdeck_api('POST', '/api/chat/' . rawurlencode($id) . '/cancel', []), JSON_UNESCAPED_UNICODE);
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
if (isset($_GET['api']) && $_GET['api'] === 'controller_status') {
    header('Content-Type: application/json; charset=UTF-8');
    echo json_encode(kdeck_api('GET', '/api/controller/status'), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'controller_tick') {
    header('Content-Type: application/json; charset=UTF-8');
    echo json_encode(kdeck_api('POST', '/api/controller/tick', []), JSON_UNESCAPED_UNICODE);
    exit;
}
if (isset($_GET['api']) && $_GET['api'] === 'controller_goal') {
    header('Content-Type: application/json; charset=UTF-8');
    $goal = preg_replace('/[^a-zA-Z0-9_.-]/', '', $_GET['goal'] ?? '');
    $action = $_GET['action'] === 'hold' ? 'hold' : 'resume';
    echo json_encode(kdeck_api('POST', '/api/controller/goals/' . rawurlencode($goal) . '/' . $action, []), JSON_UNESCAPED_UNICODE);
    exit;
}

$config = kdeck_api('GET', '/api/config');
$default_roots = [
    '/home/kojima/work/url2ai',
    '/home/kojima/work/vwork',
    '/home/kojima/work/kmail',
    '/home/kojima/work/rqdb4ai',
    '/home/kojima/work/aixec',
    '/home/kojima/work/horizon',
    '/home/kojima/work/buzblogger',
    '/home/kojima/work/swork',
    '/home/kojima/work/kdeck',
    '/home/kojima/work/kurage',
    '/home/kojima/work/airadio-scripted-mv',
    '/home/kojima/work/bittensorman.xyz',
];
$roots = !empty($config['allowed_roots']) && is_array($config['allowed_roots'])
    ? $config['allowed_roots']
    : $default_roots;
$codex_model = $config['codex_model'] ?? 'gpt-5.5';
$execution_modes = !empty($config['execution_modes']) && is_array($config['execution_modes'])
    ? $config['execution_modes']
    : [
        'chat-only' => ['label' => 'Chat only', 'sandbox' => 'read-only'],
        'research' => ['label' => 'Research', 'sandbox' => 'read-only'],
        'confirm' => ['label' => '確認して実行', 'sandbox' => 'workspace-write'],
        'full-access' => ['label' => 'Full access', 'sandbox' => 'danger-full-access'],
    ];
$default_execution_mode = $config['default_execution_mode'] ?? 'chat-only';
$agents = !empty($config['agents']) && is_array($config['agents'])
    ? $config['agents']
    : [
        ['id' => 'local', 'label' => 'local', 'role' => 'kdeck local Codex', 'host' => '192.168.0.3', 'configured' => true],
        ['id' => 'hermes-192-168-0-2', 'label' => 'Hermes scheduler', 'role' => 'Hermesジョブ、enqueue、スケジュール確認', 'host' => '192.168.0.2', 'configured' => false],
        ['id' => 'aixec-api-192-168-0-14', 'label' => 'AIxEC API server', 'role' => 'AIxEC API、登録API、dashboard report確認', 'host' => '192.168.0.14', 'configured' => false],
        ['id' => 'hyperframes-192-168-0-11', 'label' => 'Hyperframes video', 'role' => 'Hyperframes、Kurage Horizon動画生成、YouTube投稿確認', 'host' => '192.168.0.11', 'configured' => false],
    ];
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
	*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}header{position:sticky;top:0;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);z-index:2;backdrop-filter:blur(10px)}.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px}.brand{display:flex;align-items:center;gap:10px;font-weight:900;min-width:0}.brand-icon{width:42px;height:42px;border-radius:50%;object-fit:cover;box-shadow:0 2px 8px rgba(0,127,150,.18);flex:0 0 auto}.brand-title{display:grid;line-height:1.15;min-width:0}.brand-title b,.brand-title span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.brand-title span{font-size:12px;color:var(--muted);font-weight:700}.account{flex:0 0 auto;max-width:45vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right}.wrap{display:grid;grid-template-columns:320px minmax(0,1fr) 380px;gap:12px;padding:12px;height:calc(100vh - 64px)}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-height:0}.side{display:flex;flex-direction:column;overflow:hidden}.side-top{padding:12px;border-bottom:1px solid var(--line)}.main{display:flex;flex-direction:column;padding:0;overflow:hidden}.main-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-bottom:1px solid var(--line)}h2{font-size:16px;margin:0}.muted{color:var(--muted);font-size:12px}.logout{color:var(--brand);font-weight:800;text-decoration:none}.row{display:grid;gap:6px;margin-bottom:8px}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;border:1px solid #c8d5dc;border-radius:6px;padding:8px;background:#fff}button{min-height:36px;border:0;border-radius:6px;background:var(--brand);color:#fff;font-weight:800;padding:8px 12px;cursor:pointer}button.secondary{background:#e7eef2;color:var(--text)}button.active{background:var(--danger);color:#fff}button:disabled{cursor:not-allowed;opacity:.55}.history-select{margin-top:8px;min-height:38px}.history{overflow:auto;padding:8px;display:flex;flex-direction:column;gap:6px}.history-item{border:1px solid transparent;background:transparent;color:var(--text);text-align:left;font-weight:700;min-height:0;padding:9px;border-radius:6px}.history-item:hover,.history-item.active{background:var(--soft);border-color:#c5dde3}.history-title{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-meta{display:block;color:var(--muted);font-size:11px;font-weight:600;margin-top:3px}.chatlog{display:flex;flex-direction:column;gap:12px;flex:1;overflow:auto;padding:14px}.bubble{max-width:92%;border-radius:8px;padding:10px 12px;white-space:pre-wrap;line-height:1.55}.user{align-self:flex-end;background:#dff0f7}.assistant{align-self:flex-start;background:#f0f4f7}.runline{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}.runline button{min-height:28px;padding:5px 9px;font-size:12px}.voicebar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 14px;border-top:1px solid var(--line)}.voicebar label{display:flex;align-items:center;gap:6px}.voicebar input{width:auto}.composer{display:grid;grid-template-columns:1fr auto auto;gap:8px;padding:0 14px 14px}.composer textarea{resize:vertical;min-height:82px}.empty-history{padding:10px;color:var(--muted);font-size:12px}body{background:linear-gradient(180deg,#f7fcfd 0%,#edf7f9 46%,#f8fbfb 100%);color:#17242c}header{background:rgba(255,255,255,.88);border-bottom-color:#cfe0e6;box-shadow:0 8px 24px rgba(36,78,92,.08)}.bar{height:60px;padding:9px 16px}.brand-icon{width:40px;height:40px}.brand-title b{color:#17313a}.brand-title span,.muted{color:#647884}.logout{color:#087d9a}.wrap{gap:14px;padding:14px;height:calc(100vh - 60px)}.panel{border:1px solid #d5e5ea;border-radius:8px;box-shadow:0 12px 34px rgba(36,78,92,.09)}.side{background:linear-gradient(180deg,#ffffff 0%,#eef9fb 100%)}.side-top{border-bottom:1px solid #d6e8ed}.side h2{color:#17313a}.main{background:#ffffff;color:#18252d}.main-head{min-height:52px;background:#ffffff;border-bottom:1px solid #dce9ee}.row label{letter-spacing:.02em;text-transform:uppercase}input,select,textarea{border-color:#c7d8df;background:#ffffff;color:#17242c}input:focus,select:focus,textarea:focus{outline:2px solid rgba(8,125,154,.16);border-color:#0b8aa6}button{background:#087d9a;box-shadow:0 3px 10px rgba(8,125,154,.16)}button:hover{filter:brightness(1.04)}button.secondary{background:#edf5f7;color:#17313a;box-shadow:none}button.danger{background:#b03a2e;color:#fff}.history{padding:9px}.history-item{color:#17313a;border-color:transparent}.history-item:hover,.history-item.active{background:#e5f5f7;border-color:#bfe0e8}.history-meta{color:#718691}.chatlog{background:linear-gradient(180deg,#ffffff 0%,#f1f8fa 100%)}.bubble{box-shadow:0 2px 8px rgba(36,78,92,.07)}.assistant{background:#ffffff;border:1px solid #dce9ee}.user{background:#dff4f7;border:1px solid #bfe4ec}.voicebar{background:#ffffff;border-top:1px solid #dce9ee}.composer{background:#ffffff}.memo-panel{background:#ffffff;border-top:1px solid #dce9ee;padding:0 14px 14px}.memo-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:7px}.memo-actions{display:flex;gap:8px;flex-wrap:wrap}.memo-actions button{min-height:30px;padding:6px 10px}.memo-panel textarea{min-height:96px;resize:vertical;background:#fbfeff}.ops{display:flex;flex-direction:column;gap:10px;padding:12px;overflow:auto}.ops-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.ops-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.metric{background:#f5fbfc;border:1px solid #d8e9ee;border-radius:8px;padding:9px}.metric b{display:block;font-size:18px}.goal-card{border:1px solid #d8e9ee;border-radius:8px;background:#fff;padding:10px;display:grid;gap:8px}.goal-top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.pill{display:inline-flex;align-items:center;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:900;background:#edf5f7;color:#17313a}.pill.running{background:#fff1c7;color:#6c4b00}.pill.cooldown{background:#e8f1ff;color:#264f88}.pill.complete_today{background:#ddf7e6;color:#176139}.pill.hold{background:#ffe5e1;color:#8a2c1c}.progress{height:8px;background:#e8f0f3;border-radius:999px;overflow:hidden}.progress>span{display:block;height:100%;background:linear-gradient(90deg,#0b8aa6,#19a889);width:0}.goal-actions{display:flex;gap:6px;flex-wrap:wrap}.goal-actions button{min-height:28px;padding:5px 9px;font-size:12px}.event-list{display:grid;gap:5px;font-size:12px}.event-item{padding:7px;border-radius:6px;background:#f7fbfc;border:1px solid #e0edf1}@media(max-width:820px){body{overflow:auto}.bar{height:54px;padding:7px 10px;align-items:center;flex-direction:row}.brand{gap:7px;flex:1 1 auto}.brand-icon{width:34px;height:34px}.brand-title b{font-size:14px}.brand-title span{display:none}.account{max-width:42vw;font-size:11px}.wrap{display:flex;flex-direction:column;gap:8px;height:auto;min-height:calc(100dvh - 54px);padding:8px;overflow:visible}.side{flex:0 0 auto;max-height:none;overflow:visible}.side-top{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:7px;padding:8px}.side-top h2{display:none}.side-top .row{margin:0;gap:3px}.side-top .row:first-of-type{grid-column:1/-1}.side-top .row label{font-size:10px}.side-top>button{min-height:34px;padding:7px 8px}.history-select{grid-column:1/-1;margin:0;min-height:38px}.side-top>.muted{display:none}.history{display:none}.main{flex:0 0 auto;min-height:0;overflow:visible}.main-head{min-height:42px;padding:8px 10px}.chatlog{flex:none;min-height:52dvh;max-height:70dvh;overflow:auto;padding:10px}.voicebar{padding:8px 10px}.composer{grid-template-columns:1fr auto;gap:7px;padding:0 10px 10px}.composer textarea{grid-column:1/-1;min-height:70px}.composer button{min-height:34px}.memo-panel{padding:0 10px 10px}.memo-head{align-items:flex-start;flex-direction:column;gap:6px}.memo-panel textarea{min-height:76px}.ops{padding:10px}.ops-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.metric{padding:7px}.metric b{font-size:15px}.goal-top{align-items:flex-start}.goal-card{padding:9px}}
</style></head><body><header><div class="bar"><div class="brand"><img class="brand-icon" src="/images/kurage-icon.png" alt="Kurage"><span class="brand-title"><b>Kurage Agent Deck</b><span>Codex CLI web console</span></span></div><div class="muted account">@<?=h($session_user)?> · <a class="logout" href="<?=h($logout_url)?>">Logout</a></div></div></header>
<div class="wrap"><aside class="panel side"><div class="side-top"><h2>Chat</h2>
<div class="row"><label class="muted">Agent</label><select id="target-agent"><?php foreach ($agents as $agent): ?><option value="<?=h($agent['id'] ?? '')?>" data-role="<?=h($agent['role'] ?? '')?>" data-host="<?=h($agent['host'] ?? '')?>" data-configured="<?=!empty($agent['configured']) ? '1' : '0'?>"><?=h(($agent['label'] ?? $agent['id'] ?? 'agent') . ' / ' . ($agent['host'] ?? ''))?></option><?php endforeach; ?></select><span id="agent-role" class="muted"></span></div>
<div class="row"><label class="muted">Local Folder</label><select id="local-cwd"><?php foreach ($roots as $r): ?><option value="<?=h($r)?>"><?=h($r)?></option><?php endforeach; ?></select></div>
<div class="row" id="agent-folder-row"><label class="muted">Agent Folder</label><select id="chat-cwd"><?php foreach ($roots as $r): ?><option value="<?=h($r)?>"><?=h($r)?></option><?php endforeach; ?></select></div>
<div class="row"><label class="muted">Model</label><input id="chat-model" value="<?=h($codex_model)?>"></div>
<div class="row" id="remote-llm-row"><label class="muted">Remote LLM</label><select id="remote-llm-backend"></select><input id="remote-model" placeholder="model / optional"></div>
<div class="row"><label class="muted">Execution</label><select id="execution-mode"><?php foreach ($execution_modes as $key => $mode): ?><option value="<?=h($key)?>" data-sandbox="<?=h($mode['sandbox'] ?? '')?>"<?=$key === $default_execution_mode ? ' selected' : ''?>><?=h(($mode['label'] ?? $key) . ' / ' . ($mode['sandbox'] ?? ''))?></option><?php endforeach; ?></select></div>
	<button type="button" id="new-chat">New Chat</button>
	<select id="history-select" class="history-select"><option value="">履歴を読み込み中...</option></select>
	<div class="muted" style="margin-top:8px">履歴はサーバに保存されます。</div></div>
<div id="history" class="history"><div class="empty-history">履歴を選択するとここに情報を表示します。</div></div>
</aside>
	<main class="panel main"><div class="main-head"><h2 id="chat-title">Conversation</h2><span class="muted" id="chat-state">ready</span></div><div id="chatlog" class="chatlog"><div class="bubble assistant">フォルダを選んで、下の入力欄からCodexに指示できます。コマンド実行も会話の中で依頼してください。</div></div>
	<div class="voicebar">
	  <button type="button" id="voice-input" class="secondary">🎙 Speak</button>
	  <button type="button" id="voice-stop" class="secondary">読み上げ停止</button>
	  <label class="muted"><input type="checkbox" id="voice-output"> 返答を読み上げ</label>
	  <span id="voice-status" class="muted"></span>
	</div>
	<form id="chat-form" class="composer"><textarea id="chat-input" rows="4" placeholder="Codexへ送る指示"></textarea><button type="submit">Send</button><button type="button" id="send-voice" class="secondary">音声送信</button></form>
	<section class="memo-panel">
	  <div class="memo-head"><span class="muted">Voice Memo</span><div class="memo-actions"><button type="button" id="memo-copy" class="secondary">送信欄へコピー</button><button type="button" id="memo-clear" class="secondary">クリア</button></div></div>
	  <textarea id="voice-memo" rows="5" placeholder="音声入力の下書きや長文プロンプトをここに残せます。内容はこのブラウザに保存されます。"></textarea>
	</section>
</main>
<section class="panel ops">
  <div class="ops-head"><div><h2>Goal Queue</h2><div class="muted" id="controller-status-line">読み込み中...</div></div><button type="button" id="controller-tick" class="secondary">Hermes Tick</button></div>
  <div class="ops-grid">
    <div class="metric"><span class="muted">実行中</span><b id="metric-running">0</b></div>
    <div class="metric"><span class="muted">RQ待機</span><b id="metric-queued">0</b></div>
    <div class="metric"><span class="muted">今日</span><b id="metric-today">-</b></div>
  </div>
  <div id="goal-list" class="event-list"><div class="event-item">Goalを読み込み中...</div></div>
  <div><h2>Decision Log</h2><div id="controller-events" class="event-list"><div class="event-item">まだありません。</div></div></div>
</section></div>
<script>
		let chatThread = '';
		let historyThreads = [];
		const localRoots = <?=json_encode(array_values($roots), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)?>;
		const agents = <?=json_encode(array_values($agents), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)?>;
		const agentMap = Object.fromEntries(agents.map(agent => [agent.id || '', agent]));
		const chatlog = document.getElementById('chatlog');
		const historyList = document.getElementById('history');
		const chatTitle = document.getElementById('chat-title');
		const chatState = document.getElementById('chat-state');
		const targetAgentSelect = document.getElementById('target-agent');
		const agentRole = document.getElementById('agent-role');
		const localFolderSelect = document.getElementById('local-cwd');
		const agentFolderRow = document.getElementById('agent-folder-row');
		const folderSelect = document.getElementById('chat-cwd');
		const modelInput = document.getElementById('chat-model');
		const remoteLlmRow = document.getElementById('remote-llm-row');
		const remoteLlmBackendSelect = document.getElementById('remote-llm-backend');
		const remoteModelInput = document.getElementById('remote-model');
		const executionModeSelect = document.getElementById('execution-mode');
		const historySelect = document.getElementById('history-select');
		const chatInput = document.getElementById('chat-input');
	const voiceMemo = document.getElementById('voice-memo');
	const memoCopyButton = document.getElementById('memo-copy');
	const memoClearButton = document.getElementById('memo-clear');
	const controllerStatusLine = document.getElementById('controller-status-line');
	const controllerTickButton = document.getElementById('controller-tick');
	const goalList = document.getElementById('goal-list');
	const controllerEvents = document.getElementById('controller-events');
	const metricRunning = document.getElementById('metric-running');
	const metricQueued = document.getElementById('metric-queued');
	const metricToday = document.getElementById('metric-today');
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
	const savedLocalFolder = localStorage.getItem('kdeck.localFolder');
	const savedFolder = localStorage.getItem('kdeck.folder');
	const savedModel = localStorage.getItem('kdeck.model');
	const savedRemoteLlmBackend = localStorage.getItem('kdeck.remoteLlmBackend');
	const savedRemoteModel = localStorage.getItem('kdeck.remoteModel');
		const savedTargetAgent = localStorage.getItem('kdeck.targetAgent');
		const savedExecutionMode = localStorage.getItem('kdeck.executionMode');
		const executionModeDefaultVersion = 'chat-only-20260608';
		const shouldResetExecutionMode = localStorage.getItem('kdeck.executionModeDefaultVersion') !== executionModeDefaultVersion;
		const savedThread = localStorage.getItem('kdeck.thread');
		const savedMemo = localStorage.getItem('kdeck.voiceMemo');
	if(savedLocalFolder && [...localFolderSelect.options].some(option => option.value === savedLocalFolder)){
	  localFolderSelect.value = savedLocalFolder;
	}
	if(savedModel){
	  modelInput.value = savedModel;
	}
	if(savedRemoteModel){
	  remoteModelInput.value = savedRemoteModel;
	}
	if(savedTargetAgent && [...targetAgentSelect.options].some(option => option.value === savedTargetAgent)){
	  targetAgentSelect.value = savedTargetAgent;
	}
	if(shouldResetExecutionMode && [...executionModeSelect.options].some(option => option.value === 'chat-only')){
	  executionModeSelect.value = 'chat-only';
	  localStorage.setItem('kdeck.executionMode', 'chat-only');
	  localStorage.setItem('kdeck.executionModeDefaultVersion', executionModeDefaultVersion);
	} else if(savedExecutionMode && [...executionModeSelect.options].some(option => option.value === savedExecutionMode)){
	  executionModeSelect.value = savedExecutionMode;
	}
	if(savedMemo){
	  voiceMemo.value = savedMemo;
	}
	updateAgentRole();
	populateAgentFolders(localStorage.getItem('kdeck.folder.' + (targetAgentSelect.value || 'local')) || savedFolder || localFolderSelect.value);
	populateRemoteLlm(savedRemoteLlmBackend || '');
	localFolderSelect.addEventListener('change', () => {
	  localStorage.setItem('kdeck.localFolder', localFolderSelect.value);
	  if((targetAgentSelect.value || 'local') === 'local'){
	    populateAgentFolders(localFolderSelect.value);
	  }
	});
	folderSelect.addEventListener('change', () => {
	  const targetAgent = targetAgentSelect.value || 'local';
	  localStorage.setItem('kdeck.folder', folderSelect.value);
	  localStorage.setItem('kdeck.folder.' + targetAgent, folderSelect.value);
	});
	modelInput.addEventListener('change', () => localStorage.setItem('kdeck.model', modelInput.value));
	remoteLlmBackendSelect.addEventListener('change', () => {
	  localStorage.setItem('kdeck.remoteLlmBackend', remoteLlmBackendSelect.value);
	  const agent = agentMap[targetAgentSelect.value || 'local'] || {};
	  const defaults = agent.backend_default_models || {};
	  remoteModelInput.value = defaults[remoteLlmBackendSelect.value] || agent.default_model || modelInput.value || '';
	  localStorage.setItem('kdeck.remoteModel', remoteModelInput.value);
	});
	remoteModelInput.addEventListener('change', () => localStorage.setItem('kdeck.remoteModel', remoteModelInput.value));
		targetAgentSelect.addEventListener('change', () => {
		  localStorage.setItem('kdeck.targetAgent', targetAgentSelect.value);
		  updateAgentRole();
		  populateAgentFolders(localStorage.getItem('kdeck.folder.' + targetAgentSelect.value) || '');
		  populateRemoteLlm(localStorage.getItem('kdeck.remoteLlmBackend') || '');
		});
		executionModeSelect.addEventListener('change', () => localStorage.setItem('kdeck.executionMode', executionModeSelect.value));
		historySelect.addEventListener('change', () => {
		  if(historySelect.value) {
		    openThread(historySelect.value);
		  } else {
		    chatThread = '';
		    localStorage.removeItem('kdeck.thread');
		    chatTitle.textContent = 'Conversation';
		    chatlog.innerHTML = '';
		    addBubble('assistant', '会話履歴を選択すると本文を表示します。');
		    renderHistory();
		  }
		});
		voiceMemo.addEventListener('input', () => localStorage.setItem('kdeck.voiceMemo', voiceMemo.value));
	memoCopyButton.addEventListener('click', () => {
	  const memo = voiceMemo.value.trim();
	  if(!memo) return;
	  chatInput.value = chatInput.value.trim() ? chatInput.value.trim() + "\n\n" + memo : memo;
	  chatInput.focus();
	});
	memoClearButton.addEventListener('click', () => {
	  voiceMemo.value = '';
	  localStorage.removeItem('kdeck.voiceMemo');
	  voiceMemo.focus();
	});

	function fmtTime(ts){
	  if(!ts) return '';
	  const d = new Date(ts * 1000);
	  return d.toLocaleString('ja-JP', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
	}
	function setChatState(text){ chatState.textContent = text || 'ready'; }
	function agentRoots(agentId){
	  const agent = agentMap[agentId] || {};
	  const roots = Array.isArray(agent.project_folders) && agent.project_folders.length
	    ? agent.project_folders
	    : (Array.isArray(agent.allowed_roots) && agent.allowed_roots.length ? agent.allowed_roots : localRoots);
	  return roots.filter(Boolean);
	}
	function populateAgentFolders(preferred = ''){
	  const targetAgent = targetAgentSelect.value || 'local';
	  const roots = targetAgent === 'local' ? localRoots : agentRoots(targetAgent);
	  const fallback = targetAgent === 'local' ? localFolderSelect.value : roots[0] || localFolderSelect.value;
	  const selected = preferred && roots.includes(preferred) ? preferred : fallback;
	  folderSelect.innerHTML = '';
	  roots.forEach(root => {
	    const option = document.createElement('option');
	    option.value = root;
	    option.textContent = root;
	    folderSelect.appendChild(option);
	  });
	  if(selected && roots.includes(selected)){
	    folderSelect.value = selected;
	  }
	  agentFolderRow.style.display = targetAgent === 'local' ? 'none' : '';
	  localStorage.setItem('kdeck.folder.' + targetAgent, folderSelect.value);
	}
	function populateRemoteLlm(preferred = ''){
	  const targetAgent = targetAgentSelect.value || 'local';
	  const agent = agentMap[targetAgent] || {};
	  const isRemote = targetAgent !== 'local';
	  const backends = Array.isArray(agent.llm_backends) && agent.llm_backends.length ? agent.llm_backends : ['codex-cli'];
	  const selected = preferred && backends.includes(preferred)
	    ? preferred
	    : (agent.default_llm_backend || backends[0] || 'codex-cli');
	  remoteLlmBackendSelect.innerHTML = '';
	  backends.forEach(backend => {
	    const option = document.createElement('option');
	    option.value = backend;
	    option.textContent = backend;
	    remoteLlmBackendSelect.appendChild(option);
	  });
	  remoteLlmBackendSelect.value = selected;
	  const defaults = agent.backend_default_models || {};
	  const savedModel = localStorage.getItem('kdeck.remoteModel') || '';
	  const defaultModel = defaults[selected] || agent.default_model || modelInput.value || '';
	  if(!isRemote){
	    remoteModelInput.value = '';
	  } else if(!remoteModelInput.value || !savedModel || preferred !== selected) {
	    remoteModelInput.value = defaultModel;
	  }
	  remoteLlmRow.style.display = isRemote ? '' : 'none';
	}
	function updateAgentRole(){
	  const selected = targetAgentSelect.selectedOptions[0];
	  const role = selected?.dataset?.role || '';
	  const configured = selected?.dataset?.configured === '1';
	  agentRole.textContent = role ? role + (configured ? '' : ' / API未設定') : (configured ? '' : 'API未設定');
	}
	function setActiveHistory(){
	  if(historySelect) historySelect.value = chatThread || '';
	  historyList.querySelectorAll('.history-item').forEach(btn => {
	    const isActive = btn.dataset.thread === chatThread;
	    btn.classList.toggle('active', isActive);
	    btn.setAttribute('aria-current', isActive ? 'true' : 'false');
	  });
	}
		function renderHistory(){
		  const threads = historyThreads;
		  historySelect.innerHTML = '';
		  const placeholder = document.createElement('option');
		  placeholder.value = '';
		  placeholder.textContent = threads.length ? '会話履歴を選択' : '保存された履歴はありません';
		  historySelect.appendChild(placeholder);
		  threads.forEach(thread => {
		    const option = document.createElement('option');
		    option.value = thread.id;
		    option.textContent = [thread.title || 'Untitled chat', fmtTime(thread.updated)].filter(Boolean).join(' / ');
		    historySelect.appendChild(option);
		  });
		  historyList.innerHTML = '';
		  if(!threads.length){
		    historyList.innerHTML = '<div class="empty-history">まだ保存されたチャットはありません。</div>';
		    return;
		  }
		  historyList.innerHTML = chatThread ? '' : '<div class="empty-history">上のリストボックスから履歴を選ぶと、右側に本文を表示します。</div>';
		  setActiveHistory();
		}
		async function loadHistory(options = {}){
		  try{
		    const res = await fetch('?api=chat_threads', {cache:'no-store'});
		    const data = await res.json();
		    historyThreads = data.threads || [];
		    renderHistory();
	    if(options.restore && !chatThread && historyThreads.length){
	      const restoreThread = savedThread && historyThreads.some(thread => thread.id === savedThread)
	        ? savedThread
	        : historyThreads[0].id;
	      await openThread(restoreThread);
	    }
		  }catch(e){
		    historyList.innerHTML = '<div class="empty-history">履歴を読み込めませんでした。</div>';
		  }
		}
			async function openThread(id){
			  setChatState('loading');
			  try{
			    const res = await fetch('?api=chat_thread&id=' + encodeURIComponent(id), {cache:'no-store'});
			    const data = await res.json();
			    if(!data.ok || !data.thread){
			      setChatState('failed');
			      chatlog.innerHTML = '';
			      addBubble('assistant', data.detail || data.error || '履歴を開けませんでした。');
			      return;
			    }
			    const thread = data.thread;
			    chatThread = thread.id;
			    localStorage.setItem('kdeck.thread', chatThread);
		    chatTitle.textContent = 'Conversation';
		  if(thread.local_cwd && [...localFolderSelect.options].some(option => option.value === thread.local_cwd)){
		    localFolderSelect.value = thread.local_cwd;
		    localStorage.setItem('kdeck.localFolder', thread.local_cwd);
		  }
	  if(thread.model){
	    modelInput.value = thread.model;
	    localStorage.setItem('kdeck.model', thread.model);
	  }
	  if(thread.remote_model){
	    remoteModelInput.value = thread.remote_model;
	    localStorage.setItem('kdeck.remoteModel', thread.remote_model);
	  }
		  if(thread.execution_mode && [...executionModeSelect.options].some(option => option.value === thread.execution_mode)){
		    executionModeSelect.value = thread.execution_mode;
		    localStorage.setItem('kdeck.executionMode', thread.execution_mode);
		  }
		  if(thread.target_agent && [...targetAgentSelect.options].some(option => option.value === thread.target_agent)){
		    targetAgentSelect.value = thread.target_agent;
		    localStorage.setItem('kdeck.targetAgent', thread.target_agent);
		    updateAgentRole();
		  }
		  populateAgentFolders(thread.cwd || localStorage.getItem('kdeck.folder.' + (targetAgentSelect.value || 'local')) || '');
		  populateRemoteLlm(thread.remote_llm_backend || localStorage.getItem('kdeck.remoteLlmBackend') || '');
	  if(thread.cwd && [...folderSelect.options].some(option => option.value === thread.cwd)){
	    folderSelect.value = thread.cwd;
	    localStorage.setItem('kdeck.folder', thread.cwd);
	    localStorage.setItem('kdeck.folder.' + (targetAgentSelect.value || 'local'), thread.cwd);
	  }
	  chatlog.innerHTML = '';
	  (thread.messages || []).forEach(message => addBubble(message.role === 'user' ? 'user' : 'assistant', message.content || ''));
		  if(!(thread.messages || []).length) addBubble('assistant', '履歴は空です。');
		  renderHistory();
		  setChatState('loaded');
		  if(window.matchMedia('(max-width: 820px)').matches){
		    chatlog.scrollIntoView({block:'start', behavior:'smooth'});
		  }
			  }catch(e){
			    setChatState('failed');
			    chatlog.innerHTML = '';
			    addBubble('assistant', '履歴を開けませんでした。画面を再読み込みしてもう一度試してください。');
			  }
		}

	function setVoiceStatus(text){
	  voiceStatus.textContent = text || '';
	}
	function escapeHtml(text){
	  return String(text ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));
	}
	function statusLabel(status){
	  const labels = {waiting:'待機', running:'実行中', cooldown:'冷却中', complete_today:'本日完了', hold:'保留'};
	  return labels[status] || status || '-';
	}
	function renderController(data){
	  if(!data || !data.ok){
	    controllerStatusLine.textContent = data?.error || 'controller状態を取得できません';
	    return;
	  }
	  controllerStatusLine.textContent = data.enabled ? 'Hermes commander ready' : 'Hermes commander disabled';
	  metricToday.textContent = data.today || '-';
	  const live = data.rqdb4ai?.totals?.live || {};
	  metricQueued.textContent = String(Number(live.queued || 0) + Number(live.started || 0));
	  const goals = Array.isArray(data.goals) ? data.goals : [];
	  metricRunning.textContent = String(goals.filter(goal => goal.status === 'running').length);
	  goalList.innerHTML = goals.map(goal => {
	    const today = goal.today || {};
	    const items = Number(today.items || 0);
	    const target = Number(goal.daily_target || 1);
	    const percent = Math.max(0, Math.min(100, Math.round(items / Math.max(1, target) * 100)));
	    const runs = `${today.runs || 0}/${goal.max_runs_per_day || 0}`;
	    const actions = goal.status === 'hold'
	      ? `<button type="button" class="secondary goal-action" data-goal="${escapeHtml(goal.goal_name)}" data-action="resume">再開</button>`
	      : `<button type="button" class="secondary goal-action" data-goal="${escapeHtml(goal.goal_name)}" data-action="hold">保留</button>`;
	    return `<article class="goal-card">
	      <div class="goal-top"><div><b>${escapeHtml(goal.goal_name)}</b><div class="muted">${escapeHtml(goal.description || goal.worker_name || '')}</div></div><span class="pill ${escapeHtml(goal.status)}">${escapeHtml(statusLabel(goal.status))}</span></div>
	      <div class="progress" title="${items}/${target}"><span style="width:${percent}%"></span></div>
	      <div class="muted">今日 ${items}/${target}件 / run ${escapeHtml(runs)} / 1回目標 ${escapeHtml(goal.per_run_target || 0)}件</div>
	      <div class="muted">${escapeHtml(goal.last_note || '')}</div>
	      <div class="goal-actions">${actions}</div>
	    </article>`;
	  }).join('') || '<div class="event-item">Goalがありません。</div>';
	  goalList.querySelectorAll('.goal-action').forEach(button => {
	    button.addEventListener('click', async () => {
	      button.disabled = true;
	      await fetch(`?api=controller_goal&goal=${encodeURIComponent(button.dataset.goal)}&action=${encodeURIComponent(button.dataset.action)}`, {method:'POST', cache:'no-store'});
	      loadController();
	    });
	  });
	  const events = Array.isArray(data.events) ? data.events : [];
	  controllerEvents.innerHTML = events.slice(0, 8).map(item => `<div class="event-item"><b>${escapeHtml(item.level || '')}</b> ${escapeHtml(item.message || '')}<div class="muted">${escapeHtml(item.created_at || '')}</div></div>`).join('') || '<div class="event-item">まだありません。</div>';
	}
	async function loadController(){
	  try{
	    const res = await fetch('?api=controller_status', {cache:'no-store'});
	    renderController(await res.json());
	  }catch(e){
	    controllerStatusLine.textContent = 'controller状態取得に失敗';
	  }
	}
	controllerTickButton.addEventListener('click', async () => {
	  controllerTickButton.disabled = true;
	  try{
	    await fetch('?api=controller_tick', {method:'POST', cache:'no-store'});
	    await loadController();
	  }finally{
	    controllerTickButton.disabled = false;
	  }
	});
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
	function attachRunControls(bubble, jobId){
	  const line = document.createElement('div');
	  line.className = 'runline';
	  const status = document.createElement('span');
	  status.className = 'muted';
	  status.textContent = '開始中...';
	  const cancel = document.createElement('button');
	  cancel.type = 'button';
	  cancel.className = 'danger';
	  cancel.textContent = '停止';
	  cancel.addEventListener('click', async () => {
	    cancel.disabled = true;
	    status.textContent = '停止中...';
	    try{
	      await fetch('?api=chat_cancel&id=' + encodeURIComponent(jobId), {method:'POST', cache:'no-store'});
	    }catch(e){
	      status.textContent = '停止リクエストに失敗';
	    }
	  });
	  line.appendChild(status);
	  line.appendChild(cancel);
	  bubble.appendChild(line);
	  return {line, status, cancel};
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
		  localStorage.removeItem('kdeck.thread');
		  chatTitle.textContent = 'Conversation';
	  chatlog.innerHTML = '';
	  if(canSpeak) window.speechSynthesis.cancel();
		  addBubble('assistant', '新しいチャットを開始しました。');
		  setChatState('ready');
		  renderHistory();
	});
	document.getElementById('chat-form').addEventListener('submit', async ev => {
	  ev.preventDefault();
	  const input = document.getElementById('chat-input');
	  const prompt = input.value.trim();
	  if(!prompt) return;
	  const executionMode = executionModeSelect.value || 'chat-only';
	  const sandbox = executionModeSelect.selectedOptions[0]?.dataset?.sandbox || '';
	  const targetAgent = targetAgentSelect.value || 'local';
	  const remoteLlmText = targetAgent === 'local'
	    ? ''
	    : `\nRemote LLM: ${remoteLlmBackendSelect.value || 'codex-cli'} / ${remoteModelInput.value || modelInput.value || ''}`;
	  if(executionMode === 'confirm'){
	    const ok = window.confirm(`この指示を実行しますか？\n\nAgent: ${targetAgent}\nMode: 確認して実行\nSandbox: ${sandbox || 'workspace-write'}\nLocal Folder: ${localFolderSelect.value}\nAgent Folder: ${folderSelect.value}${remoteLlmText}`);
	    if(!ok) return;
	  }
	  input.value = '';
	  addBubble('user', prompt);
	  let pending;
	  if(executionMode === 'chat-only'){
	    pending = addBubble('assistant', '考えています...');
	  } else {
	    addBubble('assistant', executionMode === 'full-access' ? '了解しました。これから実行します。' : (executionMode === 'research' ? '了解しました。調査します。' : '了解しました。確認しながら進めます。'));
	    pending = addBubble('assistant', executionMode === 'research' ? '調査中...' : '実行中...');
	  }
	  localStorage.setItem('kdeck.folder', folderSelect.value);
	  localStorage.setItem('kdeck.localFolder', localFolderSelect.value);
	  localStorage.setItem('kdeck.folder.' + targetAgent, folderSelect.value);
	  localStorage.setItem('kdeck.model', modelInput.value);
	  localStorage.setItem('kdeck.remoteLlmBackend', remoteLlmBackendSelect.value);
	  localStorage.setItem('kdeck.remoteModel', remoteModelInput.value);
	  localStorage.setItem('kdeck.targetAgent', targetAgent);
	  localStorage.setItem('kdeck.executionMode', executionMode);
	  setChatState('running');
	  const res = await fetch('?api=chat', {
	    method:'POST',
	    headers:{'Content-Type':'application/json'},
	    body:JSON.stringify({prompt, thread_id:chatThread, cwd:folderSelect.value, local_cwd:localFolderSelect.value, model:modelInput.value, remote_llm_backend:remoteLlmBackendSelect.value, remote_model:remoteModelInput.value, execution_mode:executionMode, target_agent:targetAgent})
	  });
	  let data;
	  try{
	    data = await res.json();
	  }catch(e){
	    pending.textContent = 'チャット開始に失敗しました。';
	    setChatState('failed');
	    return;
	  }
		  if(data.thread_id) chatThread = data.thread_id;
		  if(chatThread) localStorage.setItem('kdeck.thread', chatThread);
		  setActiveHistory();
	  if(!data.job_id){
	    pending.textContent = data.message || JSON.stringify(data, null, 2);
	    setChatState('failed');
	    speakText(pending.textContent);
	    return;
	  }
	  const runControls = attachRunControls(pending, data.job_id);
	  let pollCount = 0;
	  async function pollChat(){
	    pollCount += 1;
	    let job;
	    try{
	      const jobRes = await fetch('?api=chat_job&id=' + encodeURIComponent(data.job_id), {cache:'no-store'});
	      job = await jobRes.json();
	    }catch(e){
	      pending.firstChild.textContent = '状態取得に失敗しました。画面を再読み込みしてください。';
	      runControls.status.textContent = 'poll failed';
	      runControls.cancel.disabled = true;
	      setChatState('failed');
	      return;
	    }
	    if(job.status === 'running'){
	      const elapsed = Number(job.elapsed || 0);
	      pending.firstChild.textContent = job.execution_mode === 'chat-only' ? '考えています...' : (job.execution_mode === 'research' ? '調査中...' : '実行中...');
	      const modeLabel = job.execution_mode === 'chat-only' ? 'Chat only' : (job.execution_mode === 'research' ? 'Research' : (job.execution_mode === 'full-access' ? 'Full access' : '確認'));
	      runControls.status.textContent = `${modeLabel} / ${job.sandbox || sandbox || ''} / ${elapsed ? `経過 ${elapsed}秒` : `確認中 ${pollCount}`}`;
	      setTimeout(pollChat, 1500);
	      return;
	    }
		    if(job.thread_id) chatThread = job.thread_id;
		    if(chatThread) localStorage.setItem('kdeck.thread', chatThread);
	    pending.textContent = job.message || job.error || job.detail || JSON.stringify(job, null, 2);
	    chatlog.scrollTop = chatlog.scrollHeight;
	    chatTitle.textContent = prompt.length > 52 ? prompt.slice(0, 52) + '...' : prompt;
	    setChatState(job.status || 'finished');
	    loadHistory();
	    speakText(pending.textContent);
	  }
	  pollChat();
	});
		loadHistory({restore:true});
		loadController();
		setInterval(loadController, 15000);
		updateAgentRole();
	</script></body></html>
