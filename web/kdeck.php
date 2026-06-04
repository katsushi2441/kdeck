<?php
$KDECK_API_BASE = getenv('KDECK_API_BASE') ?: 'http://exbridge.ddns.net:18301';
$KDECK_TOKEN = getenv('KDECK_TOKEN') ?: 'change-this-token';

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

if (isset($_GET['api']) && $_GET['api'] === 'capture') {
    header('Content-Type: application/json; charset=UTF-8');
    $id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
    echo json_encode(kdeck_api('GET', '/api/sessions/' . rawurlencode($id) . '/capture?lines=1200'), JSON_UNESCAPED_UNICODE);
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
    }
}
$sessions = kdeck_api('GET', '/api/sessions');
$config = kdeck_api('GET', '/api/config');
$roots = $config['allowed_roots'] ?? ['/home/kojima/work/url2ai'];
$active = $_GET['id'] ?? (($sessions['sessions'][0]['id'] ?? '') ?: '');
?><!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kurage Agent Deck</title>
<style>
body{margin:0;background:#f4f7f9;color:#18252d;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}header{position:sticky;top:0;background:#fff;border-bottom:1px solid #d8e2e8;z-index:2}.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px}.brand{font-weight:900}.wrap{display:grid;grid-template-columns:310px 1fr;gap:14px;padding:14px}.panel{background:#fff;border:1px solid #d8e2e8;border-radius:8px;padding:12px}.session{display:block;padding:10px;border-bottom:1px solid #e3ebef;color:inherit;text-decoration:none}.session.active{background:#e8f6fb}.muted{color:#64727c;font-size:12px}.msg{margin:0 14px;padding:10px;background:#fff7df;border:1px solid #ecd28b;border-radius:6px}.row{display:grid;gap:8px;margin-bottom:8px}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;box-sizing:border-box;border:1px solid #c8d5dc;border-radius:6px;padding:8px}button{min-height:38px;border:0;border-radius:6px;background:#0b75a5;color:#fff;font-weight:800;padding:8px 12px}.danger{background:#bb3e3e}.console{white-space:pre-wrap;overflow:auto;background:#08151d;color:#d8f3ff;border-radius:8px;padding:12px;min-height:58vh;max-height:68vh;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;line-height:1.45}.sendbox{display:grid;grid-template-columns:1fr auto auto;gap:8px;margin-top:10px}@media(max-width:820px){.wrap{grid-template-columns:1fr}.console{min-height:50vh}.sendbox{grid-template-columns:1fr}.bar{align-items:flex-start;flex-direction:column}}
</style></head><body><header><div class="bar"><div class="brand">Kurage Agent Deck</div><div class="muted">kdeck.php</div></div></header>
<?php if ($message): ?><div class="msg"><?=h($message)?></div><?php endif; ?>
<div class="wrap"><aside class="panel"><h2>Sessions</h2>
<?php foreach (($sessions['sessions'] ?? []) as $s): ?><a class="session <?=($active===$s['id']?'active':'')?>" href="?id=<?=h($s['id'])?>"><b><?=h($s['name'])?></b><div class="muted"><?=h($s['id'])?></div></a><?php endforeach; ?>
<h2>New</h2><form method="post"><input type="hidden" name="action" value="create"><div class="row"><input name="name" value="codex" placeholder="session name"></div><div class="row"><select name="cwd"><?php foreach ($roots as $r): ?><option value="<?=h($r)?>"><?=h($r)?></option><?php endforeach; ?></select></div><div class="row"><input name="command" value="codex" placeholder="command"></div><button type="submit">Start</button></form></aside>
<main class="panel"><h2><?=h($active ?: 'No session')?></h2><div id="console" class="console">loading...</div>
<?php if ($active): ?><form class="sendbox" method="post"><input type="hidden" name="action" value="send"><input type="hidden" name="id" value="<?=h($active)?>"><textarea name="text" rows="3" placeholder="Codexへ送る指示"></textarea><button type="submit">Send</button><button class="danger" type="submit" name="action" value="interrupt">Ctrl+C</button></form><?php endif; ?></main></div>
<script>
const active = <?=json_encode($active)?>;
async function refresh(){
  if(!active) return;
  const res = await fetch('?api=capture&id=' + encodeURIComponent(active), {cache:'no-store'});
  const data = await res.json();
  const el = document.getElementById('console');
  el.textContent = data.text || JSON.stringify(data, null, 2);
  el.scrollTop = el.scrollHeight;
}
refresh(); setInterval(refresh, 2500);
</script></body></html>
