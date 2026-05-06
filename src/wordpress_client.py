"""
WordPress REST API クライアント
記事の下書き投稿・更新を行う
"""

import base64
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _get_auth_header() -> str:
    """WordPress アプリケーションパスワードを使ったBasic認証ヘッダーを生成する"""
    user = os.environ["WP_USER"]
    password = os.environ["WP_APP_PASSWORD"]
    credentials = f"{user}:{password}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


def _get_api_base_url() -> str:
    """WordPress REST API のベースURLを返す"""
    wp_url = os.environ["WP_URL"].rstrip("/")
    return f"{wp_url}/wp-json/wp/v2"


def create_draft_post(
    title: str,
    content: str,
    meta_description: str,
    settings: dict,
) -> dict:
    """
    WordPress に下書き投稿を作成する

    Returns:
        {
            "id": 投稿ID,
            "draft_url": WordPress編集画面URL,
            "public_url": 公開予定URL,
        }
    """
    api_base = _get_api_base_url()
    wp_url = os.environ["WP_URL"].rstrip("/")
    seo_meta_field = settings["wordpress"].get("seo_meta_field", "_yoast_wpseo_metadesc")

    headers = {
        "Authorization": _get_auth_header(),
        "Content-Type": "application/json",
    }

    post_data = {
        "title": title,
        "content": content,
        "status": settings["wordpress"].get("post_status", "draft"),
        "type": settings["wordpress"].get("post_type", "post"),
        # メタディスクリプション（SEOプラグイン用・抜粋フィールドにも設定）
        "excerpt": meta_description,
        "meta": {
            seo_meta_field: meta_description,
        },
    }

    logger.info(f"WordPress に下書きを投稿します: 「{title}」")

    response = requests.post(
        f"{api_base}/posts",
        headers=headers,
        json=post_data,
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"WordPress API エラー (status={response.status_code}): {response.text[:300]}"
        )

    post = response.json()
    post_id = post["id"]
    draft_url = f"{wp_url}/wp-admin/post.php?post={post_id}&action=edit"

    logger.info(f"下書き投稿完了 (id={post_id})")
    logger.info(f"編集URL: {draft_url}")

    return {
        "id": post_id,
        "draft_url": draft_url,
        "public_url": post.get("link", ""),
    }


def verify_connection() -> bool:
    """WordPress REST API への接続を確認する"""
    try:
        wp_url = os.environ["WP_URL"].rstrip("/")
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            headers={"Authorization": _get_auth_header()},
            params={"per_page": 1},
            timeout=10,
        )
        return response.ok
    except Exception as e:
        logger.error(f"WordPress 接続確認エラー: {e}")
        return False
