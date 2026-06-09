from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("KDECK_DATA_DIR", ROOT / "storage")).expanduser()
DB_PATH = Path(os.environ.get("KDECK_CONTROLLER_DB", DATA_DIR / "controller.sqlite")).expanduser()
RQDB4AI_API_URL = os.environ.get("KDECK_RQDB4AI_API_URL", os.environ.get("RQDB4AI_API_URL", "http://127.0.0.1:18300")).rstrip("/")
RQDB4AI_API_TOKEN = os.environ.get("KDECK_RQDB4AI_API_TOKEN", os.environ.get("RQDB4AI_API_TOKEN", "")).strip()
WORKER_STATUS_URL = os.environ.get("KDECK_WORKER_STATUS_URL", "https://aixec.exbridge.jp/api.php?path=worker/status")
CONTROLLER_ENABLED = os.environ.get("KDECK_CONTROLLER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_COOLDOWN_SECONDS = int(os.environ.get("KDECK_CONTROLLER_COOLDOWN_SECONDS", "900"))


MARKET_TASKS = [
    {
        "label": "高単価AI PC・ゲーミング",
        "group": "ai_pc_gaming",
        "genre_id": "",
        "keywords": ["ゲーミングPC", "ミニPC", "GPU", "AI PC", "ワークステーション"],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "高単価でAmazon/Rakuten双方の購買につながりやすい商品を優先する",
        "reason": "kdeck goal queue default market-pipeline task",
    },
    {
        "label": "高単価ガジェット・家電",
        "group": "premium_gadget",
        "genre_id": "",
        "keywords": ["ロボット掃除機", "ポータブル電源", "4Kモニター", "NAS", "ドローン"],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "単価が高く、AI/効率化文脈で紹介しやすい商品を優先する",
        "reason": "kdeck goal queue retry market-pipeline task",
    },
    {
        "label": "ビジネス効率化・オフィス機器",
        "group": "office_productivity",
        "genre_id": "",
        "keywords": ["デスクチェア", "昇降デスク", "プロジェクター", "プリンター", "シュレッダー"],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "経営者・個人事業主が購入検討しやすい高単価商品を優先する",
        "reason": "kdeck goal queue retry market-pipeline task",
    },
    {
        "label": "防犯・見守りカメラ",
        "group": "security_cameras",
        "genre_id": "",
        "keywords": [
            "防犯カメラ 屋外", "防犯カメラ ワイヤレス", "防犯カメラ PoE", "防犯カメラ ソーラー",
            "監視カメラ 屋外 防水", "ネットワークカメラ 屋外", "見守りカメラ", "ペットカメラ",
            "ベビーモニター カメラ", "防犯カメラセット", "録画機 防犯カメラ", "ドアホン カメラ",
            "スマートロック カメラ", "人感センサー カメラ", "暗視カメラ 屋外", "4K 防犯カメラ",
            "防犯ライト カメラ", "屋外カメラ wifi", "防犯カメラ 工事不要", "AI検知 防犯カメラ",
        ],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "防犯・店舗管理・見守り用途で比較しやすい商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "成分美容・スキンケア",
        "group": "ingredient_skincare",
        "genre_id": "",
        "keywords": [
            "レチノール 美容液", "ナイアシンアミド 美容液", "ビタミンC 美容液", "セラミド 化粧水",
            "ヒアルロン酸 美容液", "CICA スキンケア", "アゼライン酸 美容液", "ペプチド 美容液",
            "グルタチオン 美容液", "敏感肌 スキンケア", "毛穴 美容液", "保湿クリーム セラミド",
            "日焼け止め 敏感肌", "クレンジングバーム", "フェイスパック 大容量", "導入美容液",
            "美容液 ランキング", "韓国コスメ 美容液", "エイジングケア クリーム", "シートマスク 大容量",
        ],
        "exclude_keywords": ["中古", "ジャンク", "サンプル", "お試し"],
        "target_count": 500,
        "description_policy": "成分比較・悩み別選び方の記事化に向いた美容商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "健康管理・サプリ",
        "group": "health_supplements",
        "genre_id": "",
        "keywords": [
            "プロテイン 1kg", "プロテイン 3kg", "ホエイプロテイン", "ソイプロテイン",
            "ビタミンD サプリ", "マルチビタミン", "亜鉛 サプリ", "鉄分 サプリ",
            "乳酸菌 サプリ", "オメガ3 サプリ", "DHA EPA サプリ", "NMN サプリ",
            "クレアチン", "EAA", "BCAA", "食物繊維 サプリ", "青汁", "睡眠 サプリ",
            "血圧計 オムロン", "体組成計 タニタ", "スマートウォッチ 健康管理",
        ],
        "exclude_keywords": ["中古", "ジャンク", "お試し"],
        "target_count": 500,
        "description_policy": "健康管理・継続購入・比較需要がある商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "キッチン・時短家電",
        "group": "kitchen_tools",
        "genre_id": "",
        "keywords": [
            "電気圧力鍋", "ノンフライヤー", "ホットクック", "低温調理器", "炊飯器 5合",
            "コーヒーメーカー 全自動", "エスプレッソマシン", "食洗機 工事不要", "浄水器 カートリッジ",
            "ブレンダー", "フードプロセッサー", "ホットプレート", "トースター 高級",
            "フライパン IH", "鍋 セット", "包丁 三徳", "まな板 抗菌", "保存容器 耐熱",
            "真空保存容器", "キッチンスケール",
        ],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "時短・家事効率化・比較記事に向いたキッチン商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "ペット用品・自動化",
        "group": "pet_supplies",
        "genre_id": "",
        "keywords": [
            "ペットシーツ まとめ買い", "猫砂 まとめ買い", "ドッグフード 大容量", "キャットフード 大容量",
            "自動給餌器", "ペットカメラ", "自動給水器 ペット", "猫 自動トイレ",
            "犬 ハーネス", "猫 爪とぎ", "ペット 消臭", "ペット ブラシ",
            "ペット キャリー", "犬 おやつ", "猫 おやつ", "ペット トイレ",
            "ペット ドライヤー", "ペット バリカン", "ペット 暑さ対策", "ペット 見守り",
        ],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "定期購入・自動化・見守り需要があるペット用品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "アウトドア・防災用品",
        "group": "outdoor_disaster",
        "genre_id": "",
        "keywords": [
            "ポータブル電源", "ソーラーパネル ポータブル電源", "防災セット", "非常食 セット",
            "保存水", "キャンプ テント", "キャンプ チェア", "アウトドア テーブル",
            "寝袋", "クーラーボックス", "LED ランタン", "焚き火台", "タープ",
            "アウトドア ワゴン", "防災 ラジオ", "簡易トイレ 防災", "モバイルバッテリー 大容量",
            "空調服", "冷感 ベスト", "熱中症対策 グッズ",
        ],
        "exclude_keywords": ["中古", "ジャンク", "ふるさと納税"],
        "target_count": 500,
        "description_policy": "季節需要・防災需要・高単価商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "日用品・消耗品まとめ買い",
        "group": "daily_consumables",
        "genre_id": "",
        "keywords": [
            "洗濯洗剤 詰め替え 大容量", "柔軟剤 詰め替え 大容量", "食器用洗剤 詰め替え 大容量",
            "キッチンペーパー まとめ買い", "トイレットペーパー まとめ買い", "ティッシュペーパー まとめ買い",
            "除菌シート まとめ買い", "マスク まとめ買い", "歯ブラシ まとめ買い", "歯磨き粉 まとめ買い",
            "ゴミ袋 45L まとめ買い", "紙おむつ まとめ買い", "ペットボトル 水 まとめ買い",
            "炭酸水 まとめ買い", "コーヒー ドリップ まとめ買い", "レトルト食品 まとめ買い",
        ],
        "exclude_keywords": ["中古", "ジャンク", "ふるさと納税"],
        "target_count": 500,
        "description_policy": "Amazon送客にもつながりやすい日用品・消耗品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "スマートホーム・IoT",
        "group": "smart_home_iot",
        "genre_id": "",
        "keywords": [
            "スマートロック", "スマートリモコン", "スマートプラグ", "スマート電球",
            "SwitchBot", "Nature Remo", "Alexa 対応", "Google Home 対応",
            "ロボット掃除機", "スマートカーテン", "温湿度計 スマート", "CO2センサー",
            "見守りセンサー", "人感センサー", "スマートスピーカー", "スマートホーム セット",
        ],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "スマートホーム化・省力化の文脈で紹介しやすい商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "カー用品・車載ガジェット",
        "group": "car_gadgets",
        "genre_id": "",
        "keywords": [
            "ドライブレコーダー 前後", "ドライブレコーダー ミラー型", "車載 冷蔵庫", "ポータブルナビ",
            "ジャンプスターター", "車載充電器 USB-C", "タイヤ 空気圧センサー", "カーナビ",
            "ETC2.0 車載器", "車載ホルダー magsafe", "洗車 高圧洗浄機", "コーティング剤 車",
            "レーダー探知機", "バックカメラ", "車中泊 マット", "車中泊 ポータブル電源",
        ],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "車載ガジェット・安全・車中泊需要に向く商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "学習・資格・教育ガジェット",
        "group": "learning_tools",
        "genre_id": "",
        "keywords": [
            "電子辞書", "語学 学習 タブレット", "ペンタブレット", "液タブ", "デジタルノート",
            "電子メモパッド", "英語教材", "プログラミング 学習 キット", "ロボット プログラミング",
            "知育 タブレット", "タイピング キーボード", "オンライン授業 マイク", "Webカメラ 4K",
            "ノイズキャンセリング ヘッドホン", "学習机 昇降", "デスクライト 目に優しい",
        ],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "学習効率化・資格・教育DXの切り口で紹介しやすい商品を優先する",
        "reason": "expanded market-pipeline discovery task",
    },
    {
        "label": "トレカ・ホビー高回転",
        "group": "trading_cards_hobby",
        "genre_id": "207659",
        "keywords": [
            "ポケモンカード BOX", "ポケモンカード シングル", "ポケモンカード SAR",
            "ポケモンカード UR", "ポケモンカード リザードン", "遊戯王 シングルカード",
            "遊戯王 BOX", "ワンピースカード BOX", "ワンピースカード シングル",
            "デュエルマスターズ BOX", "マジックザギャザリング", "トレーディングカード 高額",
        ],
        "exclude_keywords": ["中古", "ジャンク", "オリパ"],
        "target_count": 500,
        "description_policy": "回転が早いランキング商品を優先し、相場・人気カード文脈で紹介する",
        "reason": "expanded market-pipeline discovery task",
    },
]


DEFAULT_GOALS = [
    {
        "goal_name": "aixec-market-pipeline",
        "worker_name": "aixec-market-pipeline-enqueue",
        "description": "AIxEC market-pipeline 新規4000件/日を達成するまで継続",
        "function_name": "aixec_market_jobs.market_pipeline_job",
        "queue": "auto",
        "resource": "ollama:192.168.0.14:gemma4:e4b",
        "daily_target": 4000,
        "per_run_target": 500,
        "max_runs_per_day": 999,
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "priority": 10,
        "enabled": 1,
        "payload": {
            "kwargs": {
                "dry_run": False,
                "source": "worker_auto",
                "resource": "ollama",
                "ollama_host": "192.168.0.14",
                "ollama_model": "gemma4:e4b",
                "limit": 500,
                "hits": 20,
                "pages": 3,
                "max_candidates": 800,
                "score_mode": "heuristic",
                "skip_sns": False,
            },
            "meta": {
                "project": "aixec",
                "app": "market_pipeline",
                "source": "worker_auto",
                "resource": "ollama",
                "ollama_host": "192.168.0.14",
                "ollama_model": "gemma4:e4b",
                "worker_name": "aixec-market-pipeline-enqueue",
            },
            "timeout": 3600,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "aixec-growth-agent",
        "worker_name": "aixec-growth-agent-enqueue",
        "description": "AIxEC growth-agent を目標達成型で実行",
        "function_name": "aixec_market_jobs.growth_agent_job",
        "queue": "auto",
        "resource": "aixec-api",
        "daily_target": 1,
        "per_run_target": 1,
        "max_runs_per_day": 2,
        "cooldown_seconds": 1800,
        "priority": 20,
        "enabled": 1,
        "payload": {
            "kwargs": {
                "dry_run": False,
                "source": "worker_auto",
                "market_limit": 20,
                "skip_claude": False,
            },
            "meta": {
                "project": "aixec",
                "app": "growth_agent",
                "source": "worker_auto",
                "worker_name": "aixec-growth-agent-enqueue",
            },
            "timeout": 1800,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "aixec-register-market-worker",
        "worker_name": "aixec-register-market-worker-enqueue",
        "description": "既存ジャンルの楽天ランキング巡回・未登録商品登録",
        "function_name": "aixec_market_jobs.register_market_worker_job",
        "queue": "auto",
        "resource": "aixec-api",
        "daily_target": 1,
        "per_run_target": 0,
        "max_runs_per_day": 1,
        "cooldown_seconds": 1800,
        "priority": 30,
        "enabled": 1,
        "payload": {
            "kwargs": {"dry_run": False, "source": "worker_auto"},
            "meta": {"project": "aixec", "app": "register_market", "source": "worker_auto", "worker_name": "aixec-register-market-worker-enqueue"},
            "timeout": 3600,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "horizon-worker",
        "worker_name": "horizon-worker-enqueue",
        "description": "Horizonの記事・動画・はてな/Bloggerメール投稿・AIxSNS告知を6時間ごとに1日4回実行",
        "function_name": "horizon_jobs.worker_auto_cycle_job",
        "queue": "auto",
        "resource": "ollama:192.168.0.14:gemma4:e4b",
        "daily_target": 4,
        "per_run_target": 1,
        "max_runs_per_day": 4,
        "cooldown_seconds": 21600,
        "priority": 40,
        "enabled": 1,
        "payload": {
            "kwargs": {"dry_run": False, "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b"},
            "meta": {"project": "horizon", "app": "horizon", "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b", "worker_name": "horizon-worker-enqueue"},
            "timeout": 3600,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "url2ai-oss",
        "worker_name": "url2ai-oss-enqueue",
        "description": "URL2AI OSS登録 1回3件目標",
        "function_name": "oss_jobs.worker_auto_cycle_job",
        "queue": "auto",
        "resource": "ollama:192.168.0.14:gemma4:e4b",
        "daily_target": 12,
        "per_run_target": 3,
        "max_runs_per_day": 4,
        "cooldown_seconds": 900,
        "priority": 50,
        "enabled": 1,
        "payload": {
            "kwargs": {"period": "daily", "top_n": 3, "dry_run": False, "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b"},
            "meta": {"project": "url2ai", "app": "oss", "kind": "ollama", "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b", "worker_name": "url2ai-oss-enqueue"},
            "timeout": 1800,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "url2ai-polymarket",
        "worker_name": "url2ai-polymarket-enqueue",
        "description": "URL2AI Polymarket登録",
        "function_name": "polymarket_jobs.worker_auto_cycle_job",
        "queue": "auto",
        "resource": "ollama:192.168.0.14:gemma4:e4b",
        "daily_target": 4,
        "per_run_target": 1,
        "max_runs_per_day": 4,
        "cooldown_seconds": 900,
        "priority": 60,
        "enabled": 1,
        "payload": {
            "kwargs": {"dry_run": False, "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b"},
            "meta": {"project": "url2ai", "app": "polymarket", "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b", "worker_name": "url2ai-polymarket-enqueue"},
            "timeout": 1800,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "url2ai-finreport",
        "worker_name": "url2ai-finreport-enqueue",
        "description": "URL2AI FinReport登録",
        "function_name": "finreport_jobs.worker_auto_cycle_job",
        "queue": "auto",
        "resource": "ollama:192.168.0.14:gemma4:e4b",
        "daily_target": 2,
        "per_run_target": 1,
        "max_runs_per_day": 2,
        "cooldown_seconds": 1800,
        "priority": 70,
        "enabled": 1,
        "payload": {
            "kwargs": {"dry_run": False, "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b"},
            "meta": {"project": "url2ai", "app": "finreport", "kind": "ollama", "source": "worker_auto", "resource": "ollama", "ollama_host": "192.168.0.14", "ollama_model": "gemma4:e4b", "worker_name": "url2ai-finreport-enqueue"},
            "timeout": 1800,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "buzblogger",
        "worker_name": "buzblogger-enqueue",
        "description": "buzblogger記事生成・投稿を4時間ごとに1日6回実行",
        "function_name": "buzblogger_jobs.worker_auto_cycle_job",
        "queue": "auto",
        "resource": "claude",
        "daily_target": 6,
        "per_run_target": 1,
        "max_runs_per_day": 6,
        "cooldown_seconds": 14400,
        "priority": 80,
        "enabled": 1,
        "payload": {
            "kwargs": {"dry_run": False, "source": "worker_auto"},
            "meta": {"project": "buzblogger", "app": "buzblogger", "source": "worker_auto", "worker_name": "buzblogger-enqueue"},
            "timeout": 900,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def today_key() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_name TEXT NOT NULL UNIQUE,
                worker_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                function_name TEXT NOT NULL,
                queue TEXT NOT NULL DEFAULT 'auto',
                resource TEXT NOT NULL DEFAULT '',
                daily_target INTEGER NOT NULL DEFAULT 1,
                per_run_target INTEGER NOT NULL DEFAULT 1,
                max_runs_per_day INTEGER NOT NULL DEFAULT 1,
                cooldown_seconds INTEGER NOT NULL DEFAULT 900,
                priority INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'waiting',
                current_job_id TEXT NOT NULL DEFAULT '',
                last_result TEXT NOT NULL DEFAULT '{}',
                last_note TEXT NOT NULL DEFAULT '',
                cooldown_until TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goal_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                job_id TEXT NOT NULL DEFAULT '',
                rq_status TEXT NOT NULL DEFAULT '',
                business_status TEXT NOT NULL DEFAULT '',
                items INTEGER NOT NULL DEFAULT 0,
                ok INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS controller_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        now = utc_now()
        for goal in DEFAULT_GOALS:
            conn.execute(
                """
                INSERT INTO goals (
                    goal_name, worker_name, description, function_name, queue, resource,
                    daily_target, per_run_target, max_runs_per_day, cooldown_seconds,
                    priority, enabled, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(goal_name) DO UPDATE SET
                    worker_name = excluded.worker_name,
                    description = excluded.description,
                    function_name = excluded.function_name,
                    queue = excluded.queue,
                    resource = excluded.resource,
                    daily_target = excluded.daily_target,
                    per_run_target = excluded.per_run_target,
                    max_runs_per_day = excluded.max_runs_per_day,
                    cooldown_seconds = excluded.cooldown_seconds,
                    priority = excluded.priority,
                    enabled = excluded.enabled,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    goal["goal_name"],
                    goal["worker_name"],
                    goal["description"],
                    goal["function_name"],
                    goal["queue"],
                    goal["resource"],
                    goal["daily_target"],
                    goal["per_run_target"],
                    goal["max_runs_per_day"],
                    goal["cooldown_seconds"],
                    goal["priority"],
                    goal["enabled"],
                    json.dumps(goal["payload"], ensure_ascii=False),
                    now,
                    now,
                ),
            )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    for key in ("payload", "last_result", "result", "data"):
        if key in data:
            try:
                data[key] = json.loads(data[key] or "{}")
            except json.JSONDecodeError:
                data[key] = {}
    return data


def event(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    with connect() as conn:
        insert_event(conn, level, message, data)


def insert_event(conn: sqlite3.Connection, level: str, message: str, data: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO controller_events(level, message, data, created_at) VALUES (?, ?, ?, ?)",
        (level, message, json.dumps(data or {}, ensure_ascii=False), utc_now()),
    )


def api_request(method: str, base: str, path: str, payload: dict[str, Any] | None = None, token: str = "", timeout: int = 20) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json", "User-Agent": "kdeck-hermes-commander/0.1"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", errors="replace")
            status_code = getattr(res, "status", 0)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "error": raw[:1000]}
    except OSError as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {"raw": raw}
    if isinstance(data, dict):
        data.setdefault("status_code", status_code)
        return data
    return {"ok": True, "status_code": status_code, "data": data}


def rq_get(path: str, timeout: int = 20) -> dict[str, Any]:
    return api_request("GET", RQDB4AI_API_URL, path, token=RQDB4AI_API_TOKEN, timeout=timeout)


def rq_post(path: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    return api_request("POST", RQDB4AI_API_URL, path, payload, token=RQDB4AI_API_TOKEN, timeout=timeout)


def worker_status() -> dict[str, Any]:
    url = urllib.parse.urlparse(WORKER_STATUS_URL)
    base = f"{url.scheme}://{url.netloc}"
    path = url.path + (("?" + url.query) if url.query else "")
    return api_request("GET", base, path, timeout=12)


def daily_totals(conn: sqlite3.Connection, goal_id: int, day: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS runs, COALESCE(SUM(items), 0) AS items
        FROM goal_runs
        WHERE goal_id = ? AND day = ? AND finished_at != ''
        """,
        (goal_id, day),
    ).fetchone()
    return {"runs": int(row["runs"] or 0), "items": int(row["items"] or 0)}


def extract_result(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result")
    if isinstance(result, dict):
        return result
    preview = job.get("preview") or {}
    output = preview.get("output_preview")
    if isinstance(output, str) and output.startswith("{"):
        try:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _int_value(value: Any) -> int | None:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return None


def _nested_dict(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = source
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def job_items(job: dict[str, Any], result: dict[str, Any], goal: dict[str, Any] | None = None) -> int:
    if goal and goal.get("goal_name") == "aixec-market-pipeline":
        # market-pipeline's goal is new product creation. Registered/selected
        # includes updates, so counting it makes "new 500" look complete when
        # nothing new was created.
        sources = (
            result.get("metrics") if isinstance(result.get("metrics"), dict) else {},
            _nested_dict(result, "submit", "response", "result"),
            result,
        )
        for source in sources:
            value = _int_value(source.get("created") if isinstance(source, dict) else None)
            if value is not None:
                return value
        return 0
    for source in (result, result.get("metrics") if isinstance(result.get("metrics"), dict) else {}, job.get("lifecycle") or {}):
        if not isinstance(source, dict):
            continue
        for key in ("items", "created", "registered", "selected"):
            value = _int_value(source.get(key))
            if value is not None:
                return value
    return 0


def evaluate_job(job: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    rq_status = str(job.get("status") or "")
    lifecycle = job.get("lifecycle") if isinstance(job.get("lifecycle"), dict) else {}
    result = extract_result(job)
    result_status = str(result.get("status") or lifecycle.get("state") or rq_status).lower()
    items = job_items(job, result, goal)
    terminal = bool(lifecycle.get("terminal", rq_status in {"finished", "failed", "stopped", "canceled"}))
    note = str(result.get("note") or lifecycle.get("note") or "")
    if rq_status in {"queued", "started", "deferred", "scheduled"} or not terminal:
        return {"terminal": False, "ok": False, "status": rq_status or "running", "items": items, "note": note, "result": result}
    if rq_status in {"failed", "stopped", "canceled"} or result_status in {"failed", "error", "down"}:
        return {"terminal": True, "ok": False, "status": result_status or rq_status, "items": items, "note": note, "result": result}
    per_target = int(goal.get("per_run_target") or 1)
    if items >= per_target:
        return {"terminal": True, "ok": True, "status": "ok", "items": items, "note": note, "result": result}
    return {
        "terminal": True,
        "ok": False,
        "status": "under_target",
        "items": items,
        "note": note or f"items {items} < target {per_target}",
        "result": result,
    }


def _market_group_from_run_result(raw: str) -> str:
    try:
        detail = json.loads(raw or "{}")
    except Exception:
        detail = {}
    candidates: list[Any] = [
        _nested_dict(detail, "job", "kwargs", "task").get("group"),
        _nested_dict(detail, "job", "result", "task").get("group"),
        _nested_dict(detail, "job", "result", "submit", "response", "result").get("group"),
    ]
    description = str(_nested_dict(detail, "job").get("description") or "")
    match = re.search(r"'group': '([^']+)'", description)
    if match:
        candidates.append(match.group(1))
    for value in candidates:
        if value:
            return str(value)
    return ""


def _market_group_stats(conn: sqlite3.Connection, goal_id: int) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        """
        SELECT result, items, business_status, finished_at
        FROM goal_runs
        WHERE goal_id = ? AND day = ?
        ORDER BY id
        """,
        (goal_id, today_key()),
    ).fetchall()
    for row in rows:
        group = _market_group_from_run_result(str(row["result"] or ""))
        if not group:
            continue
        entry = stats.setdefault(group, {"runs": 0, "created": 0, "failures": 0, "latest_created": 0, "latest_status": ""})
        created = int(row["items"] or 0)
        entry["runs"] += 1
        entry["created"] += created
        entry["latest_created"] = created
        entry["latest_status"] = str(row["business_status"] or "")
        if str(row["business_status"] or "") == "failed":
            entry["failures"] += 1
    return stats


def market_task_for_attempt(conn: sqlite3.Connection, goal_id: int, attempt: int) -> dict[str, Any]:
    stats = _market_group_stats(conn, goal_id)
    best_score = -10**9
    selected_index = attempt % len(MARKET_TASKS)
    for index, task in enumerate(MARKET_TASKS):
        group = str(task.get("group") or "")
        entry = stats.get(group, {})
        runs = int(entry.get("runs") or 0)
        created = int(entry.get("created") or 0)
        latest_created = int(entry.get("latest_created") or 0)
        failures = int(entry.get("failures") or 0)
        score = 1000 - runs * 180 - failures * 260
        if runs == 0:
            score += 800
        if latest_created >= 100:
            score += 550
        elif runs >= 2 and created < 30:
            score -= 1200
        elif runs >= 1 and latest_created < 10:
            score -= 350
        score += min(created, 300)
        # Keep deterministic variety among equal-ish choices.
        score -= abs((attempt % len(MARKET_TASKS)) - index) * 2
        if score > best_score:
            best_score = score
            selected_index = index

    task = dict(MARKET_TASKS[selected_index])
    group = str(task.get("group") or "")
    entry = stats.get(group, {})
    task["target_count"] = 500
    task["reason"] = (
        f"{task.get('reason', '')}; attempt={attempt + 1}; "
        f"adaptive_stats group={group} runs={int(entry.get('runs') or 0)} "
        f"created={int(entry.get('created') or 0)} latest_created={int(entry.get('latest_created') or 0)}; "
        "low-created groups are skipped and high-created groups are deepened"
    )
    return task


def enqueue_goal(conn: sqlite3.Connection, goal: dict[str, Any]) -> dict[str, Any]:
    payload = dict(goal.get("payload") or {})
    kwargs = dict(payload.get("kwargs") or {})
    meta = dict(payload.get("meta") or {})
    today = today_key()
    run_count = conn.execute(
        "SELECT COUNT(*) AS c FROM goal_runs WHERE goal_id = ? AND day = ?",
        (goal["id"], today),
    ).fetchone()["c"]
    if goal["goal_name"] == "aixec-market-pipeline":
        kwargs["task"] = market_task_for_attempt(conn, int(goal["id"]), int(run_count or 0))
        kwargs["target_count"] = int(goal.get("per_run_target") or 500)
        kwargs["limit"] = int(goal.get("per_run_target") or 500)
    request = {
        "queue": goal.get("queue") or "auto",
        "function": goal["function_name"],
        "kwargs": kwargs,
        "meta": meta,
        "timeout": int(payload.get("timeout") or 1800),
        "result_ttl": int(payload.get("result_ttl") or 86400),
        "failure_ttl": int(payload.get("failure_ttl") or 604800),
    }
    response = rq_post("/api/enqueue", request, timeout=30)
    if not response.get("ok"):
        raise RuntimeError(f"RQDB4AI enqueue failed: {response}")
    job = response.get("job") if isinstance(response.get("job"), dict) else {}
    job_id = str(job.get("id") or "")
    now = utc_now()
    conn.execute(
        "INSERT INTO goal_runs(goal_id, day, job_id, rq_status, business_status, started_at, result) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (goal["id"], today, job_id, str(job.get("status") or "queued"), "running", now, json.dumps(response, ensure_ascii=False)),
    )
    conn.execute(
        "UPDATE goals SET status = 'running', current_job_id = ?, last_note = ?, updated_at = ? WHERE id = ?",
        (job_id, "RQDB4AIへ投入しました", now, goal["id"]),
    )
    insert_event(conn, "info", f"enqueued {goal['goal_name']}", {"job_id": job_id, "request": request, "response": response})
    return response


def refresh_running_goal(conn: sqlite3.Connection, goal: dict[str, Any]) -> bool:
    job_id = str(goal.get("current_job_id") or "")
    if not job_id:
        conn.execute("UPDATE goals SET status = 'waiting', updated_at = ? WHERE id = ?", (utc_now(), goal["id"]))
        return True
    detail = rq_get("/api/jobs/" + urllib.parse.quote(job_id), timeout=20)
    if not detail.get("ok"):
        conn.execute(
            "UPDATE goals SET status = 'hold', last_note = ?, updated_at = ? WHERE id = ?",
            (f"RQDB4AI job detail unavailable: {detail.get('error') or detail}", utc_now(), goal["id"]),
        )
        return True
    job = detail.get("job") if isinstance(detail.get("job"), dict) else {}
    evaluation = evaluate_job(job, goal)
    if not evaluation["terminal"]:
        conn.execute(
            "UPDATE goals SET last_result = ?, last_note = ?, updated_at = ? WHERE id = ?",
            (json.dumps(detail, ensure_ascii=False), evaluation["note"], utc_now(), goal["id"]),
        )
        return False
    now = utc_now()
    conn.execute(
        """
        UPDATE goal_runs
        SET rq_status = ?, business_status = ?, items = ?, ok = ?, note = ?, result = ?, finished_at = ?
        WHERE job_id = ?
        """,
        (
            str(job.get("status") or ""),
            str(evaluation["status"]),
            int(evaluation["items"] or 0),
            1 if evaluation["ok"] else 0,
            str(evaluation["note"] or ""),
            json.dumps(detail, ensure_ascii=False),
            now,
            job_id,
        ),
    )
    totals = daily_totals(conn, int(goal["id"]), today_key())
    if totals["items"] >= int(goal.get("daily_target") or 1):
        status = "complete_today"
        note = f"daily target complete: {totals['items']}/{goal['daily_target']}"
        cooldown_until = ""
    elif totals["runs"] >= int(goal.get("max_runs_per_day") or 1):
        status = "complete_today"
        note = f"max runs reached: runs={totals['runs']} items={totals['items']}/{goal['daily_target']}"
        cooldown_until = ""
    elif evaluation["ok"]:
        status = "cooldown"
        cooldown_until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=int(goal.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS))).isoformat()
        note = f"run ok: +{evaluation['items']} items, today {totals['items']}/{goal['daily_target']}"
    else:
        status = "cooldown"
        cooldown_until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(600, int(goal.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS)))).isoformat()
        note = f"under target or failed: +{evaluation['items']} items, retry after cooldown"
    conn.execute(
        """
        UPDATE goals
        SET status = ?, current_job_id = '', last_result = ?, last_note = ?, cooldown_until = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, json.dumps(detail, ensure_ascii=False), note, cooldown_until, now, goal["id"]),
    )
    insert_event(conn, "info" if evaluation["ok"] else "warn", f"finished {goal['goal_name']}", {"job_id": job_id, "evaluation": evaluation, "totals": totals})
    return True


def cooldown_ready(goal: dict[str, Any]) -> bool:
    value = str(goal.get("cooldown_until") or "")
    if not value:
        return True
    try:
        until = dt.datetime.fromisoformat(value)
    except ValueError:
        return True
    return dt.datetime.now(dt.timezone.utc) >= until


def status() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        day = today_key()
        goals = []
        for row in conn.execute("SELECT * FROM goals ORDER BY priority, id").fetchall():
            goal = row_dict(row)
            goal["today"] = daily_totals(conn, int(goal["id"]), day)
            goals.append(goal)
        events = [row_dict(row) for row in conn.execute("SELECT * FROM controller_events ORDER BY id DESC LIMIT 30").fetchall()]
    rq_summary = rq_get("/api/summary", timeout=12) if RQDB4AI_API_TOKEN else {"ok": False, "error": "RQDB4AI token is not configured"}
    workers = worker_status()
    return {
        "ok": True,
        "enabled": CONTROLLER_ENABLED,
        "today": day,
        "rqdb4ai_api_url": RQDB4AI_API_URL,
        "goals": goals,
        "events": events,
        "rqdb4ai": rq_summary,
        "worker_status": workers,
    }


def set_goal_status(goal_name: str, status_value: str) -> dict[str, Any]:
    init_db()
    if status_value not in {"waiting", "hold", "cooldown", "complete_today"}:
        raise ValueError("invalid goal status")
    with connect() as conn:
        conn.execute(
            "UPDATE goals SET status = ?, current_job_id = '', updated_at = ? WHERE goal_name = ?",
            (status_value, utc_now(), goal_name),
        )
        if conn.total_changes < 1:
            raise KeyError(goal_name)
    event("info", f"goal {goal_name} set to {status_value}", {})
    return {"ok": True, "goal_name": goal_name, "status": status_value}
