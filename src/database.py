"""
データベース管理モジュール
SQLiteを使ってキーワード・記事・SNS投稿の状態を管理する
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# DBファイルのパス（リポジトリルートの data/ ディレクトリに保存）
DB_PATH = Path(__file__).parent.parent / "data" / "nanigashi.db"


def get_connection() -> sqlite3.Connection:
    """データベース接続を返す"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # 外部キー制約を有効化
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database() -> None:
    """データベースとテーブルを初期化する（存在しない場合のみ作成）"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        -- キーワード管理テーブル
        CREATE TABLE IF NOT EXISTS keywords (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword              TEXT    NOT NULL,
            difficulty           INTEGER,                         -- SEO難易度 (1〜100)
            status               TEXT    DEFAULT 'stock',         -- stock / writing / ready / done
            github_item_node_id  TEXT    UNIQUE,                  -- GitHub ProjectアイテムのNode ID
            created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- 記事管理テーブル
        CREATE TABLE IF NOT EXISTS articles (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_id           INTEGER,
            title                TEXT,                            -- 採用したタイトル
            title_candidates     TEXT,                            -- タイトル候補3案（JSON）
            content              TEXT,                            -- 記事本文（HTML）
            meta_description     TEXT,                            -- メタディスクリプション
            wp_post_id           INTEGER,                         -- WordPress投稿ID
            wp_draft_url         TEXT,                            -- WordPress下書き編集URL
            approved             INTEGER DEFAULT 0,               -- 承認フラグ (0=未承認 / 1=承認済み)
            github_item_node_id  TEXT,                            -- GitHub ProjectアイテムのNode ID
            created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (keyword_id) REFERENCES keywords(id)
        );

        -- SNS投稿管理テーブル（フェーズ2用・現時点は空）
        CREATE TABLE IF NOT EXISTS sns_posts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id   INTEGER,
            sns_type     TEXT,                                    -- twitter / instagram / など
            content      TEXT,                                    -- 投稿テキスト
            scheduled_at DATETIME,
            posted_at    DATETIME,
            status       TEXT DEFAULT 'pending',                  -- pending / posted / failed
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        );
    """)

    conn.commit()
    conn.close()
    logger.info(f"データベースを初期化しました: {DB_PATH}")


def save_keyword(keyword: str, github_item_node_id: str, difficulty: int = None) -> int:
    """キーワードを保存して id を返す（既存の場合はそのまま返す）"""
    conn = get_connection()
    cursor = conn.cursor()

    # 同じ GitHub アイテムが既に登録されていれば id を返す
    cursor.execute(
        "SELECT id FROM keywords WHERE github_item_node_id = ?",
        (github_item_node_id,),
    )
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing["id"]

    cursor.execute(
        """
        INSERT INTO keywords (keyword, difficulty, status, github_item_node_id)
        VALUES (?, ?, 'writing', ?)
        """,
        (keyword, difficulty, github_item_node_id),
    )
    keyword_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"キーワードを保存しました: '{keyword}' (id={keyword_id})")
    return keyword_id


def save_article(
    keyword_id: int,
    title: str,
    title_candidates: str,
    content: str,
    meta_description: str,
    wp_post_id: int,
    wp_draft_url: str,
    github_item_node_id: str,
) -> int:
    """記事を保存して id を返す"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO articles
            (keyword_id, title, title_candidates, content, meta_description,
             wp_post_id, wp_draft_url, github_item_node_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            keyword_id, title, title_candidates, content, meta_description,
            wp_post_id, wp_draft_url, github_item_node_id,
        ),
    )
    article_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"記事を保存しました: '{title}' (id={article_id}, wp_id={wp_post_id})")
    return article_id


def update_keyword_status(github_item_node_id: str, status: str) -> None:
    """キーワードのステータスを更新する"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE keywords
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE github_item_node_id = ?
        """,
        (status, github_item_node_id),
    )
    conn.commit()
    conn.close()
    logger.info(f"キーワードのステータスを更新しました: {github_item_node_id} → {status}")


def is_already_processed(github_item_node_id: str) -> bool:
    """指定のGitHubアイテムが既に処理済みかチェックする（二重処理防止）"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM articles WHERE github_item_node_id = ?",
        (github_item_node_id,),
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None
