# nanigashi 自動執筆システム セットアップガイド

## 全体の流れ

```
[1] GitHubリポジトリ作成
    ↓
[2] GitHub Secrets に APIキーを登録
    ↓
[3] GitHub Projects カンバンを作成
    ↓
[4] config/settings.yaml を編集
    ↓
[5] 初回DB初期化ワークフローを実行
    ↓
[6] 動作確認
```

---

## STEP 1: GitHubリポジトリを作成

1. GitHub (https://github.com) にログイン
2. 右上の「+」→「New repository」
3. Repository name: `nanigashi`
4. Public または Private（どちらでもOK）
5. 「Create repository」をクリック

---

## STEP 2: このフォルダをGitHubにプッシュ

Mac のターミナルで以下を実行：

```bash
cd ~/Desktop/nanigashi
git init
git add .
git commit -m "初期コミット"
git branch -M main
git remote add origin https://github.com/あなたのユーザー名/nanigashi.git
git push -u origin main
```

---

## STEP 3: GitHub Personal Access Token（PAT）を作成

1. https://github.com/settings/tokens にアクセス
2. 「Generate new token」→「Generate new token (classic)」
3. Note: `nanigashi-bot`
4. Expiration: `No expiration`（または任意の期間）
5. 以下のスコープにチェック：
   - ✅ `repo`（全項目）
   - ✅ `project`（全項目）
6. 「Generate token」→ 表示されたトークンをコピー（一度しか表示されません）

---

## STEP 4: GitHub Secrets に APIキーを登録

リポジトリの「Settings」→「Secrets and variables」→「Actions」→「New repository secret」

| Secret名 | 値 |
|---|---|
| `CLAUDE_API_KEY` | Anthropic コンソールで取得したAPIキー |
| `WP_URL` | `https://your-blog.com`（末尾スラッシュなし） |
| `WP_USER` | WordPressのログインユーザー名 |
| `WP_APP_PASSWORD` | WordPressアプリケーションパスワード（下記参照） |
| `GH_PAT` | STEP 3 で作成したトークン |

### WordPress アプリケーションパスワードの作成手順
1. WordPress管理画面にログイン
2. 「ユーザー」→「プロフィール」
3. 下にスクロールして「アプリケーションパスワード」を見つける
4. アプリケーション名: `nanigashi-bot`
5. 「新しいアプリケーションパスワードを追加」
6. 表示されたパスワードをコピー（スペース込みでOK）

---

## STEP 5: GitHub Projects カンバンを作成

1. GitHubの自分のプロフィールページ→「Projects」タブ→「New project」
2. 「Board」テンプレートを選択→「Create」
3. 既存の列を削除して以下の4列を作成：
   - **Stock**（未着手のキーワード）
   - **Writing**（執筆中）
   - **Ready**（下書き完成・確認待ち）
   - **Done**（公開完了）
4. プロジェクトのURLを確認：
   `https://github.com/users/あなたのユーザー名/projects/1`
   → 末尾の数字（例: `1`）が Project Number

---

## STEP 6: settings.yaml を編集

`config/settings.yaml` を開いて以下を変更：

```yaml
github:
  owner: "あなたのGitHubユーザー名"  # ← ここを変更
  repo: "nanigashi"
  project_number: 1  # ← Project URLの末尾の数字
```

SWELL吹き出しのキャラクター画像を設定する場合：
```yaml
swell:
  character_image_url: "https://your-blog.com/wp-content/uploads/キャラ画像.png"
```

使用するSEOプラグインに合わせてメタフィールド名を変更：
```yaml
wordpress:
  seo_meta_field: "_yoast_wpseo_metadesc"  # Yoast SEO の場合
  # seo_meta_field: "_seosp_description"   # SEO SIMPLE PACK の場合
```

変更後、GitHubにプッシュ：
```bash
git add config/settings.yaml
git commit -m "settings更新"
git push
```

---

## STEP 7: 初回データベース初期化

1. GitHubリポジトリの「Actions」タブを開く
2. 左メニューから「データベース初期化」を選択
3. 「Run workflow」→「Run workflow」をクリック
4. 完了したら `data/nanigashi.db` がリポジトリに追加される

---

## STEP 8: 動作確認（手動テスト）

1. GitHubリポジトリにイシューを作成
   - タイトル: キーワード（例: `Japandiスタイル おすすめ照明 2025`）
   - 本文: 追加コンテキスト（省略OK）
2. そのイシューをGitHub Projectsに追加（「+」→「Add existing item」）
3. 「Actions」タブ→「記事自動執筆」→「Run workflow」
4. 以下の値を入力（GraphQL Explorerなどで取得）：
   - `item_node_id`: ProjectアイテムのNode ID
   - `content_node_id`: イシューのNode ID
   - `project_node_id`: ProjectのNode ID

---

## 日常の使い方（iPhone から）

1. GitHubアプリでリポジトリを開く
2. 「Issues」→「New issue」でキーワードを入力して作成
3. GitHub Projects でそのイシューを「Stock」に追加
4. 準備ができたらカードを「Stock」→「Writing」にドラッグ
5. 数分後に「Writing」→「Ready」に自動移動
6. イシューのコメントにWordPress下書きURLが投稿される

---

## トラブルシューティング

### Actions が起動しない
- `projects_v2_item` イベントはイシューをリポジトリに作成してからProjectに追加する必要がある
- Projectsの列名が `settings.yaml` の設定と完全一致しているか確認

### WordPress投稿が失敗する
- `WP_URL` にスラッシュが含まれていないか確認
- アプリケーションパスワードが正しいか確認（`ユーザー名:パスワード` 形式）
- WordPress REST API が有効になっているか確認

### GitHub Projects の操作が失敗する
- `GH_PAT` に `project` スコープがあるか確認
- `settings.yaml` の列名がProjectと完全一致しているか確認
