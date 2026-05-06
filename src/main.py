"""
nanigashi 自動執筆システム メインエントリーポイント

GitHub Actions から呼ばれる。
環境変数から GitHub Projects のイベント情報を受け取り、
記事生成 → WordPress投稿 → カード移動 を実行する。
"""

import json
import logging
import os
import sys
from pathlib import Path

# ローカル開発時のみ .env を読み込む（GitHub Actions では Secrets を使用）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import yaml

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from database import (
    init_database,
    is_already_processed,
    save_article,
    save_keyword,
    update_keyword_status,
)
from claude_writer import generate_article
from wordpress_client import create_draft_post
from github_projects import (
    add_issue_comment,
    get_issue_details,
    get_option_id,
    get_project_node_id,
    move_item_to_column,
)

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_settings() -> dict:
    """config/settings.yaml を読み込む"""
    settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_completion_comment(article: dict, wp_result: dict) -> str:
    """GitHubイシューに追加する完了コメントを構築する"""
    titles = article.get("titles", {})
    title1 = titles.get("title1", "—")
    title2 = titles.get("title2", "—")
    title3 = titles.get("title3", "—")

    return f"""## ✅ 記事生成完了

**採用タイトル**
> {article['selected_title']}

**タイトル候補3案**
1. {title1}
2. {title2}
3. {title3}

**メタディスクリプション**
> {article['meta_description']}

**WordPress 下書き編集URL**
{wp_result['draft_url']}

---
*nanigashi 自動執筆システムにより生成されました*"""


def main() -> None:
    logger.info("=" * 60)
    logger.info("nanigashi 自動執筆システム 開始")
    logger.info("=" * 60)

    # --- 設定の読み込み ---
    settings = load_settings()

    # --- GitHub Actions から渡される環境変数 ---
    item_node_id = os.environ.get("EVENT_ITEM_NODE_ID", "").strip()
    content_node_id = os.environ.get("EVENT_CONTENT_NODE_ID", "").strip()
    content_type = os.environ.get("EVENT_CONTENT_TYPE", "").strip()
    project_node_id = os.environ.get("EVENT_PROJECT_NODE_ID", "").strip()

    # 必須変数のチェック
    missing = [
        name for name, val in [
            ("EVENT_ITEM_NODE_ID", item_node_id),
            ("EVENT_CONTENT_NODE_ID", content_node_id),
            ("EVENT_PROJECT_NODE_ID", project_node_id),
        ] if not val
    ]
    if missing:
        logger.error(f"必須環境変数が設定されていません: {', '.join(missing)}")
        sys.exit(1)

    # イシュー以外（Draft、PR など）はスキップ
    if content_type != "Issue":
        logger.info(f"コンテンツタイプが Issue ではないためスキップします: {content_type}")
        sys.exit(0)

    # --- データベースの初期化 ---
    init_database()

    # --- 二重処理防止チェック ---
    if is_already_processed(item_node_id):
        logger.warning(f"このアイテムは既に処理済みです: {item_node_id}")
        sys.exit(0)

    # --- イシューからキーワードを取得 ---
    logger.info(f"イシューの詳細を取得します: {content_node_id}")
    issue = get_issue_details(content_node_id)
    keyword = issue["title"].strip()
    additional_context = issue.get("body") or ""

    logger.info(f"キーワード: 「{keyword}」")

    # --- キーワードを DB に保存 ---
    keyword_id = save_keyword(keyword, item_node_id)

    # --- Claude API で記事生成 ---
    logger.info("Claude API で記事を生成します...")
    article = generate_article(keyword, additional_context, settings)

    # --- WordPress に下書き投稿 ---
    logger.info("WordPress に下書きを投稿します...")
    wp_result = create_draft_post(
        title=article["selected_title"],
        content=article["content"],
        meta_description=article["meta_description"],
        settings=settings,
    )

    # --- DB に記事情報を保存 ---
    save_article(
        keyword_id=keyword_id,
        title=article["selected_title"],
        title_candidates=json.dumps(article["titles"], ensure_ascii=False),
        content=article["content"],
        meta_description=article["meta_description"],
        wp_post_id=wp_result["id"],
        wp_draft_url=wp_result["draft_url"],
        github_item_node_id=item_node_id,
    )

    # --- GitHub Projects カードを Ready に移動 ---
    logger.info("カードを Ready に移動します...")
    gh_settings = settings["github"]
    field_id, option_id = get_option_id(
        project_node_id,
        gh_settings["status_field_name"],
        gh_settings["columns"]["ready"],
    )
    move_item_to_column(project_node_id, item_node_id, field_id, option_id)

    # --- イシューに完了コメントを追加 ---
    logger.info("イシューに完了コメントを追加します...")
    comment = build_completion_comment(article, wp_result)
    add_issue_comment(content_node_id, comment)

    # --- キーワードのステータスを更新 ---
    update_keyword_status(item_node_id, "ready")

    logger.info("=" * 60)
    logger.info("処理完了")
    logger.info(f"  タイトル: {article['selected_title']}")
    logger.info(f"  WP下書きURL: {wp_result['draft_url']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
