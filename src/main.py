"""
nanigashi 自動執筆システム メインエントリーポイント

GitHub Actions から10分ごとに呼ばれる。
nanigashi-auto プロジェクトの "Writing" カラムを監視し、
新規アイテムがあれば記事生成 → WordPress投稿 → カード移動を実行する。
"""

import json
import logging
import os
import sys
from pathlib import Path

# ローカル開発時のみ .env を読み込む
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import yaml

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
    get_writing_items,
    move_item_to_column,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_settings() -> dict:
    settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_completion_comment(article: dict, wp_result: dict) -> str:
    titles = article.get("titles", {})
    return f"""## ✅ 記事生成完了

**採用タイトル**
> {article['selected_title']}

**タイトル候補3案**
1. {titles.get('title1', '—')}
2. {titles.get('title2', '—')}
3. {titles.get('title3', '—')}

**メタディスクリプション**
> {article['meta_description']}

**WordPress 下書き編集URL**
{wp_result['draft_url']}

---
*nanigashi 自動執筆システムにより生成されました*"""


def process_item(item: dict, settings: dict) -> None:
    """Writingカラムの1アイテムを処理する"""
    item_node_id = item["item_node_id"]
    content_node_id = item["content_node_id"]
    project_node_id = item["project_node_id"]

    logger.info(f"処理開始: 「{item['title']}」 (item={item_node_id})")

    # イシューの本文を取得
    issue = get_issue_details(content_node_id)
    keyword = issue["title"].strip()
    additional_context = issue.get("body") or ""

    # キーワードをDBに保存
    keyword_id = save_keyword(keyword, item_node_id)

    # Claude APIで記事生成
    logger.info("Claude APIで記事を生成します...")
    article = generate_article(keyword, additional_context, settings)

    # WordPressに下書き投稿
    logger.info("WordPressに下書きを投稿します...")
    wp_result = create_draft_post(
        title=article["selected_title"],
        content=article["content"],
        meta_description=article["meta_description"],
        settings=settings,
    )

    # DBに記事情報を保存
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

    # カードをReadyに移動
    gh = settings["github"]
    field_id, option_id = get_option_id(
        project_node_id,
        gh["status_field_name"],
        gh["columns"]["ready"],
    )
    move_item_to_column(project_node_id, item_node_id, field_id, option_id)

    # イシューに完了コメントを追加
    comment = build_completion_comment(article, wp_result)
    add_issue_comment(content_node_id, comment)

    # キーワードのステータスを更新
    update_keyword_status(item_node_id, "ready")

    logger.info(f"処理完了: 「{article['selected_title']}」")
    logger.info(f"  WP下書きURL: {wp_result['draft_url']}")


def main() -> None:
    logger.info("=" * 60)
    logger.info("nanigashi 自動執筆システム 起動")
    logger.info("=" * 60)

    settings = load_settings()
    init_database()

    gh = settings["github"]

    # プロジェクトの "Writing" カラムにあるアイテムを取得
    logger.info(f"プロジェクト {gh['owner']}/projects/{gh['project_number']} を確認します...")
    writing_items = get_writing_items(
        owner=gh["owner"],
        project_number=gh["project_number"],
        status_field_name=gh["status_field_name"],
        writing_column=gh["columns"]["writing"],
    )

    if not writing_items:
        logger.info("Writingカラムに新規アイテムはありません。終了します。")
        return

    processed = 0
    for item in writing_items:
        # 二重処理防止
        if is_already_processed(item["item_node_id"]):
            logger.info(f"スキップ（処理済み）: 「{item['title']}」")
            continue

        try:
            process_item(item, settings)
            processed += 1
        except Exception as e:
            logger.error(f"エラーが発生しました: 「{item['title']}」 - {e}", exc_info=True)
            # エラーをイシューにコメント
            try:
                add_issue_comment(
                    item["content_node_id"],
                    f"## ❌ 記事生成エラー\n\nエラー内容: `{e}`\n\nGitHub Actionsのログを確認してください。",
                )
            except Exception:
                pass

    logger.info("=" * 60)
    logger.info(f"完了: {processed}件処理しました")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
