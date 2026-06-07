# Kurage Agent Deck の技術解説

Kurage Agent Deck は、スマホやブラウザから Linux サーバ上の Codex CLI を操作するための小型 Web コンソールです。実装はシンプルで、主に `PHP UI + FastAPI + Codex CLI` の 3 層で構成されています。

## 全体構成

```text
スマホ / ブラウザ
  -> https://kurage.exbridge.jp/kdeck.php
  -> PHP: 認証 + API プロキシ + Web UI
  -> FastAPI: http://<server>:18301
  -> Codex CLI または SwarmClaw
  -> 選択されたローカル / OpenClaw 実行環境
```

Kurage Agent Deck 自体が LLM ではありません。ユーザー認証、ワークスペース選択、API 中継、ジョブ管理、音声 UI を担当し、実際の推論やコード作業は Codex CLI に委譲します。

マルチサーバ PoC では、`192.168.0.3` の kdeck と SwarmClaw を統合管理サーバにし、`192.168.0.2` を Hermes スケジューラ担当、`192.168.0.14` を AIxEC API server 担当、`192.168.0.11` を Hyperframes 動画生成担当として扱います。Web UI は `target_agent` を指定しますが、リモート実行は各サーバへ直接 HTTP gateway を置くのではなく、SwarmClaw が管理する OpenClaw gateway 経由に統一します。

## 主要コンポーネント

`web/kdeck.php` は、Web 画面と API プロキシを兼ねています。ブラウザは FastAPI に直接アクセスせず、PHP に対して `?api=chat` や `?api=chat_job` を呼び出します。PHP 側で `KDECK_TOKEN` を付けて FastAPI に中継するため、API トークンをブラウザへ露出しにくい構造です。

認証には Kurage 共通の X ログインを使います。ログイン済みで、かつ admin 権限を持つユーザーだけが操作できます。Kurage Agent Deck はローカルシェルや Codex を動かせるため、通常の管理画面より強い権限を持つ操作面として扱う必要があります。

`app/main.py` は FastAPI バックエンドです。`/api/chat` を受けると、指定された `cwd`、モデル、プロンプトを使って `codex exec --json` を起動します。実行されるコマンドは概念的には次の形です。

```text
codex exec --json -m <model> --cd <cwd> --sandbox workspace-write -
```

つまり、Kurage Agent Deck は Codex CLI を呼び出す制御面であり、ファイル調査、編集、テスト実行などの実作業は Codex が担当します。

## チャット処理の流れ

```text
1. ユーザーがブラウザで指示を送る
2. PHP が FastAPI の /api/chat に転送する
3. FastAPI が chat job を作成する
4. バックグラウンドスレッドで codex exec を実行する
5. Codex の JSON 出力から最終回答を抽出する
6. ブラウザが /api/chat/{job_id} をポーリングする
7. 結果をチャット画面に表示する
```

会話履歴は `KDECK_DATA_DIR/chat_threads` 配下の JSON ファイルに保存されます。Web UI は保存された履歴一覧から過去の会話を開き直せます。また、同じスレッドで送信した場合は、保存済み履歴の直近部分を Codex へのプロンプトに含めるため、後続ターンで過去の文脈を参照できます。

ジョブ状態と PTY セッションは `CHAT_JOBS` や `SESSIONS` などのプロセスメモリ上の辞書で管理されます。そのため、API プロセスを再起動すると実行中ジョブやアクティブな端末セッションは消えますが、保存済みチャット履歴は残ります。

## ワークスペース制御

Kurage Agent Deck では、Codex を任意のディレクトリで起動できないように `KDECK_ALLOWED_ROOTS` で許可ルートを制御しています。

FastAPI 側では `validate_cwd()` が選択された作業ディレクトリを検証します。指定された `cwd` が存在し、かつ許可されたルート配下にある場合だけ Codex の実行を許可します。これにより、誤ってサーバ上の無関係なディレクトリを操作するリスクを下げています。

## 実行モード

現在の UI は主に `/api/chat` を使うチャット型です。ユーザーが自然言語で指示を送り、Kurage Agent Deck が Codex CLI にジョブとして渡します。

一方で、バックエンドには PTY セッション機能も残っています。`Session` クラスは `pty.openpty()` で疑似端末を作り、任意のコマンドを対話的に動かせる設計です。WebSocket `/api/sessions/{id}/terminal` もあり、ブラウザからリアルタイム端末接続を行う拡張にも対応できる構造です。

## 音声 UI

フロントエンドには Web Speech API を使った音声入力と読み上げ機能があります。`SpeechRecognition` で日本語音声をテキスト化し、`speechSynthesis` で Codex の返答を読み上げます。

この音声処理はサーバ側ではなくブラウザ側で行われます。そのため、対応可否は利用するブラウザに依存します。

## セキュリティ上の要点

Kurage Agent Deck は、ローカルワークスペースで Codex CLI を動かすための操作面です。したがって、通常の Web UI よりも強い権限を持ちます。

重要な対策は次の通りです。

- FastAPI を外部へ直接公開しない
- PHP プロキシ側で `KDECK_TOKEN` を付与する
- ブラウザへ API トークンを渡さない
- Kurage 共通ログインと admin 判定で利用者を制限する
- `KDECK_ALLOWED_ROOTS` で操作可能なワークスペースを限定する
- モバイル操作から `sudo` や本番環境への破壊的操作を行わない

## まとめ

Kurage Agent Deck は、Kurage 共通ログインで保護されたスマホ対応 Web UI から、許可されたローカルワークスペース上で Codex CLI を実行するための軽量エージェント操作コンソールです。

特徴は、LLM 本体を自前実装していない点です。Kurage Agent Deck は認証、プロキシ、ジョブ管理、ワークスペース制御、音声 UI を担当し、実際の推論とコード作業は Codex CLI に委譲します。

この分離により、Kurage Agent Deck は小さな実装のまま、ローカル開発環境に接続された実用的な AI エージェント操作面として機能します。
