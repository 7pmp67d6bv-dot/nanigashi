"""
Claude API を使った記事生成モジュール
ユーザーの一次情報・体験談を軸に、SEO最適化された記事を執筆する
"""

import re
import logging
import os
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# Issueテンプレートの各セクション見出しとパース用キー
_TEMPLATE_SECTIONS = {
    "experience":    "実体験・一次情報",
    "products":      "紹介する商品・サービス",
    "good_points":   "推しポイント（実際に良かったこと）",
    "caveats":       "気になった点・正直な感想",
    "target_reader": "想定読者・解決したい悩み",
    "style_notes":   "文体・トーンの補足（任意）",
}


def parse_issue_body(body: str) -> dict[str, str]:
    """
    GitHub Issue テンプレートの本文をパースして各セクションの内容を返す。
    テンプレート未使用（自由記述）の場合は experience にまとめて格納する。
    """
    if not body or not body.strip():
        return {}

    result: dict[str, str] = {}

    # セクション見出し（### で始まる行）でスプリット
    parts = re.split(r"^###\s+", body, flags=re.MULTILINE)

    if len(parts) <= 1:
        # テンプレート未使用 → 自由記述として experience に格納
        result["experience"] = body.strip()
        return result

    for part in parts[1:]:
        lines = part.strip().split("\n")
        heading = lines[0].strip()
        content = "\n".join(lines[1:]).strip()
        # HTMLコメント（<!-- ... -->）を除去
        content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL).strip()

        for key, label in _TEMPLATE_SECTIONS.items():
            if heading == label and content:
                result[key] = content
                break

    return result


def _build_system_prompt(settings: dict) -> str:
    """システムプロンプトを構築する"""
    blog = settings["blog"]
    article = settings["article"]

    # 文体サンプルがあれば追加
    style_sample = blog.get("writing_style_sample", "").strip()
    author_profile = blog.get("author_profile", "").strip()

    style_section = ""
    if style_sample and "ここに過去記事の文章を貼り付けてください" not in style_sample:
        style_section = f"""
## 文体・語り口の参考（過去記事より）
以下の文体・テンポ・語り口を忠実に再現してください。
単語の選び方、句読点の打ち方、文の長さ、一人称の使い方を特に参考にすること。

---
{style_sample}
---"""

    author_section = ""
    if author_profile:
        author_section = f"\n## ブログ運営者プロフィール\n{author_profile}"

    return f"""あなたはブログ「{blog['name']}」の専属ライターです。
ユーザー（ブログ運営者）が実際に体験・使用したことをもとに記事を執筆します。

## 最重要ルール
1. **一次情報を最優先にする**: ユーザーが提供した体験談・感想・発見を記事の核として使う
2. **AIによる推測・一般論は補足のみ**: 一次情報がない箇所の補完に限定し、憶測で事実を作らない
3. **ユーザーの言葉を活かす**: 提供された表現・語り口をできるだけ自然に記事に組み込む
4. **体験した「人」として書く**: 第三者の解説ではなく、実際に使った人の視点で書く

## ブログ情報
- ブログ名: {blog['name']}
- テーマ: {blog['theme']}
- 読者層: {blog['target_audience']}
- 基本トーン: {blog['tone']}
{author_section}{style_section}

## 記事品質基準
- 本文文字数: {article['min_chars']}〜{article['max_chars']}文字
- SEOタイトル候補: {article['title_candidates']}案
- メタディスクリプション: {article['meta_desc_min']}〜{article['meta_desc_max']}文字
- 吹き出し数: {article['balloon_count']}箇所
- アフィリエイトリンク数: 合計{article['affiliate_link_count']}箇所

## 吹き出しマーカー
記事中の吹き出しは以下の形式で挿入（後処理でSWELLブロックに変換されます）：
[BALLOON:吹き出しに入れるテキスト]

## アフィリエイトプレースホルダー
{{{{RAKUTEN_LINK:商品名}}}}
{{{{AMAZON_LINK:商品名}}}}

## 出力フォーマット（必ず守ること）
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


def _build_user_prompt(keyword: str, parsed_sections: dict[str, str], settings: dict) -> str:
    """ユーザープロンプトを構築する（一次情報を中心に据えた構成）"""
    article = settings["article"]
    blog = settings["blog"]

    # 一次情報セクションを組み立て
    primary_info_parts = []

    if parsed_sections.get("experience"):
        primary_info_parts.append(
            f"### 実体験・一次情報（最重要）\n{parsed_sections['experience']}"
        )
    if parsed_sections.get("products"):
        primary_info_parts.append(
            f"### 紹介する商品・サービス\n{parsed_sections['products']}"
        )
    if parsed_sections.get("good_points"):
        primary_info_parts.append(
            f"### 推しポイント（実際に良かったこと）\n{parsed_sections['good_points']}"
        )
    if parsed_sections.get("caveats"):
        primary_info_parts.append(
            f"### 気になった点・正直な感想\n{parsed_sections['caveats']}"
        )
    if parsed_sections.get("target_reader"):
        primary_info_parts.append(
            f"### 想定読者・解決したい悩み\n{parsed_sections['target_reader']}"
        )

    style_override = parsed_sections.get("style_notes", "")

    if primary_info_parts:
        primary_info_block = (
            "## ユーザーからの一次情報\n"
            "以下の情報を記事の軸として使用してください。\n"
            "特に「実体験・一次情報」は記事全体の根拠として随所に組み込んでください。\n\n"
            + "\n\n".join(primary_info_parts)
        )
    else:
        primary_info_block = (
            "※ 一次情報の入力がありません。\n"
            "一般的な情報として執筆しますが、推測・憶測での断言は避け、\n"
            "「〜と言われています」「〜とされています」など適切な表現を使ってください。"
        )

    style_section = ""
    if style_override:
        style_section = f"\n## 今回の文体指示\n{style_override}\n"

    return f"""キーワード「{keyword}」で記事を執筆してください。

{primary_info_block}
{style_section}
## 執筆要件

### タイトル3案
- キーワード「{keyword}」を含む
- 28〜32文字程度
- 体験談・一次情報の強みが伝わる表現（「実際に使ってみた」「本音レビュー」「〇ヶ月使った感想」など）
- 読者層（{blog['target_audience']}）に刺さる表現

### 本文構成
- 序論: 読者の悩みへの共感 → ブログ運営者の体験の紹介（200〜300文字）
- H2見出し×3〜4個: 一次情報に基づいた具体的な内容（各500〜700文字）
- 結論: 体験をふまえた正直なまとめと行動喚起（200〜300文字）
- 合計: {article['min_chars']}〜{article['max_chars']}文字

### HTML形式の例
<h2>見出しテキスト</h2>
<p>本文テキスト</p>
[BALLOON:読者への語りかけ]
<h3>サブ見出し</h3>
<p>実際に使ってみて感じたのが{{{{RAKUTEN_LINK:商品名}}}}の〇〇です。</p>

### 吹き出し（{article['balloon_count']}箇所）
- 読者が「わかる！」と思う共感フレーズ
- 一次情報の印象的なポイントへの語りかけ
- まとめ前の体験をふり返るひとこと

### アフィリエイトリンク（合計{article['affiliate_link_count']}箇所）
- 紹介する商品・サービス欄の商品を優先して使用
- 自然な文脈に組み込む

### SEO要件
- キーワード「{keyword}」を本文中に自然な形で3〜5回含める
- 一次情報に基づく具体性・信頼性を重視"""


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


def generate_article(keyword: str, issue_body: str, settings: dict) -> dict[str, Any]:
    """
    Claude API を使って記事を生成する。
    issue_body はGitHub Issueテンプレートの本文（一次情報）。

    Returns:
        {
            "titles": {"title1": "...", "title2": "...", "title3": "..."},
            "selected_title": "...",
            "meta_description": "...",
            "content": "...",
        }
    """
    client = anthropic.Anthropic(api_key=os.environ["CLAUDE_API_KEY"])
    model = settings["claude"]["model"]
    max_tokens = settings["claude"]["max_tokens"]

    # Issue本文をテンプレートセクションごとにパース
    parsed_sections = parse_issue_body(issue_body)
    has_primary_info = bool(parsed_sections.get("experience"))
    logger.info(f"一次情報の入力: {'あり' if has_primary_info else 'なし（テンプレート未使用）'}")

    system_prompt = _build_system_prompt(settings)
    user_prompt = _build_user_prompt(keyword, parsed_sections, settings)

    logger.info(f"Claude API に記事生成をリクエストします (model={model})")

    # システムプロンプトをキャッシュして繰り返し実行時のコストを削減
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
    article["content"] = _replace_balloon_markers(article["content"], settings)

    title_len = len(article["selected_title"])
    logger.info(f"選択タイトル: 「{article['selected_title']}」（{title_len}文字）")

    meta_len = len(article["meta_description"])
    meta_min = settings["article"]["meta_desc_min"]
    meta_max = settings["article"]["meta_desc_max"]
    if not (meta_min <= meta_len <= meta_max):
        logger.warning(
            f"メタディスクリプションの文字数が基準外です: {meta_len}文字 "
            f"(基準: {meta_min}〜{meta_max}文字)"
        )

    content_text = re.sub(r"<[^>]+>|<!--.*?-->", "", article["content"], flags=re.DOTALL)
    logger.info(f"本文文字数（概算）: {len(content_text)}文字")

    return article
