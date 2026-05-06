"""
Claude API を使った記事生成モジュール
SEO最適化タイトル3案・本文・メタディスクリプションを一括生成する
"""

import re
import json
import logging
import os
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


def _build_system_prompt(settings: dict) -> str:
    """システムプロンプトを構築する"""
    blog = settings["blog"]
    article = settings["article"]
    swell = settings["swell"]

    balloon_example = (
        swell["balloon_template"]
        .replace("{direction}", swell["balloon_direction"])
        .replace("{image_url}", swell.get("character_image_url", ""))
        .replace("{name}", swell["character_name"])
        .replace("{text}", "ここに吹き出しのテキストが入ります")
    )

    return f"""あなたはブログ「{blog['name']}」の専属ライターです。

## ブログ情報
- ブログ名: {blog['name']}
- テーマ: {blog['theme']}
- 読者層: {blog['target_audience']}
- 文体・トーン: {blog['tone']}

## 記事品質基準
- 本文文字数: {article['min_chars']}〜{article['max_chars']}文字
- SEOタイトル候補: {article['title_candidates']}案
- メタディスクリプション: {article['meta_desc_min']}〜{article['meta_desc_max']}文字
- 吹き出し数: {article['balloon_count']}箇所
- アフィリエイトリンク数: 合計{article['affiliate_link_count']}箇所

## SWELL吹き出しブロックの形式
記事中の吹き出しは必ず以下のマーカー形式で挿入してください：
[BALLOON:吹き出しに入れるテキスト（読者への自然な語りかけ）]

実際のHTMLへの変換は後処理で行います。

## アフィリエイトプレースホルダー
商品紹介箇所に以下の形式で挿入してください：
{{{{RAKUTEN_LINK:商品名}}}}
{{{{AMAZON_LINK:商品名}}}}

## 出力フォーマット
必ず以下のXMLタグで囲んで出力してください：

<titles>
<title1>SEO最適化タイトル案1</title1>
<title2>SEO最適化タイトル案2</title2>
<title3>SEO最適化タイトル案3</title3>
</titles>
<selected_title>3案の中で最も効果的なタイトル（完全一致でコピー）</selected_title>
<meta_description>メタディスクリプション（{article['meta_desc_min']}〜{article['meta_desc_max']}文字）</meta_description>
<content>
記事本文（WordPressブロックエディタ形式のHTML）
</content>

{settings['claude'].get('custom_instructions', '')}"""


def _build_user_prompt(keyword: str, additional_context: str, settings: dict) -> str:
    """ユーザープロンプトを構築する"""
    article = settings["article"]
    context_section = ""
    if additional_context and additional_context.strip():
        context_section = f"\n## 追加コンテキスト（イシュー本文）\n{additional_context.strip()}\n"

    return f"""キーワード「{keyword}」について記事を執筆してください。
{context_section}
## 執筆要件

### タイトル（3案）
- キーワードを含む
- 28〜32文字程度
- クリック率が高くなる表現（数字・疑問形・ベネフィット訴求など）
- 読者層（{settings['blog']['target_audience']}）に刺さる表現

### 本文構成
- 序論: 読者の悩みや背景に共感する導入（200〜300文字）
- H2見出し×3〜4個: それぞれ500〜700文字の内容
- 結論: まとめと行動喚起（200〜300文字）
- 合計: {article['min_chars']}〜{article['max_chars']}文字

### HTML形式の例
<h2>見出しテキスト</h2>
<p>本文テキスト</p>
[BALLOON:読者への語りかけテキスト]
<h3>サブ見出し</h3>
<p>本文テキスト。{{{{RAKUTEN_LINK:商品名}}}}も参考にどうぞ。</p>

### 吹き出し（{article['balloon_count']}箇所）
- 読者が「あるある」と感じる共感的な一言
- 商品・サービスへの軽い興味づけ
- まとめ前の感想・気づき
- [BALLOON:テキスト] 形式で挿入

### アフィリエイトリンク（合計{article['affiliate_link_count']}箇所）
- 記事のテーマに合った商品を自然な文脈で紹介
- {{{{RAKUTEN_LINK:商品名}}}} と {{{{AMAZON_LINK:商品名}}}} を使い分ける

### SEO要件
- キーワード「{keyword}」を本文中に自然な形で3〜5回含める
- 検索意図（情報収集・比較検討・購買）に応じた内容
- 読者に役立つ具体的な情報を提供する"""


def _parse_claude_response(response_text: str) -> dict[str, Any]:
    """Claudeのレスポンスをパースしてdict形式で返す"""

    def extract_tag(tag: str) -> str | None:
        match = re.search(rf"<{tag}>(.*?)</{tag}>", response_text, re.DOTALL)
        return match.group(1).strip() if match else None

    titles = {}
    for i in range(1, 4):
        title = extract_tag(f"title{i}")
        if title:
            titles[f"title{i}"] = title

    selected_title = extract_tag("selected_title")
    meta_description = extract_tag("meta_description")
    content = extract_tag("content")

    if not selected_title or not content:
        raise ValueError("Claudeのレスポンスに必須タグが見つかりません。レスポンス:\n" + response_text[:500])

    return {
        "titles": titles,
        "selected_title": selected_title,
        "meta_description": meta_description or "",
        "content": content,
    }


def _replace_balloon_markers(content: str, settings: dict) -> str:
    """[BALLOON:テキスト] マーカーをSWELLブロック形式に置換する"""
    swell = settings["swell"]
    template = swell["balloon_template"]

    def replace_match(match: re.Match) -> str:
        text = match.group(1).strip()
        return (
            template
            .replace("{direction}", swell["balloon_direction"])
            .replace("{image_url}", swell.get("character_image_url", ""))
            .replace("{name}", swell["character_name"])
            .replace("{text}", text)
        )

    replaced = re.sub(r"\[BALLOON:(.*?)\]", replace_match, content, flags=re.DOTALL)
    balloon_count = len(re.findall(r"\[BALLOON:", content))
    logger.info(f"吹き出しブロックを {balloon_count} 箇所置換しました")
    return replaced


def generate_article(keyword: str, additional_context: str, settings: dict) -> dict[str, Any]:
    """
    Claude API を使って記事を生成する

    Returns:
        {
            "titles": {"title1": "...", "title2": "...", "title3": "..."},
            "selected_title": "...",
            "meta_description": "...",
            "content": "...",  # SWELL吹き出しブロック挿入済みのHTML
        }
    """
    client = anthropic.Anthropic(api_key=os.environ["CLAUDE_API_KEY"])
    model = settings["claude"]["model"]
    max_tokens = settings["claude"]["max_tokens"]

    system_prompt = _build_system_prompt(settings)
    user_prompt = _build_user_prompt(keyword, additional_context, settings)

    logger.info(f"Claude API に記事生成をリクエストします (model={model})")

    # システムプロンプトはキャッシュ対象（コスト削減）
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    )

    response_text = message.content[0].text
    logger.info(
        f"Claude APIレスポンス受信 "
        f"(入力トークン={message.usage.input_tokens}, "
        f"出力トークン={message.usage.output_tokens})"
    )

    article = _parse_claude_response(response_text)

    # [BALLOON:...] マーカーをSWELLブロックに変換
    article["content"] = _replace_balloon_markers(article["content"], settings)

    # タイトル文字数の簡易チェック
    title_len = len(article["selected_title"])
    logger.info(f"選択タイトル: 「{article['selected_title']}」（{title_len}文字）")

    # メタディスクリプション文字数チェック
    meta_len = len(article["meta_description"])
    meta_min = settings["article"]["meta_desc_min"]
    meta_max = settings["article"]["meta_desc_max"]
    if not (meta_min <= meta_len <= meta_max):
        logger.warning(
            f"メタディスクリプションの文字数が基準外です: {meta_len}文字 "
            f"(基準: {meta_min}〜{meta_max}文字)"
        )

    # 本文文字数チェック（タグを除いた概算）
    content_text = re.sub(r"<[^>]+>|<!--.*?-->", "", article["content"], flags=re.DOTALL)
    content_len = len(content_text)
    logger.info(f"本文文字数（概算）: {content_len}文字")

    return article
