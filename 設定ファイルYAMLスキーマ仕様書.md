# 設定ファイル YAML スキーマ仕様書

## 概要

本ドキュメントは、PayPay→MoneyForward 自動登録ツールの設定ファイル（`config.yml`）の YAML スキーマ仕様を定義する。

## ファイル情報

- **ファイル名**：`config.yml`
- **配置場所**：ツールフォルダ直下（`<tool_folder>\config.yml`）
- **フォーマット**：YAML 1.2
- **文字コード**：UTF-8（BOM なし）

## バリデーション方針

- ツール起動時に `config.yml` の存在チェックおよびスキーマバリデーションを行う。
- 必須項目が欠落または型不正の場合は起動を中止し、ユーザーに具体的なエラーメッセージを表示する。
- 任意項目が未指定の場合は指定のデフォルト値を使用する。

## スキーマ定義

### ルートレベル

```yaml
# 型表記凡例
# string        : 文字��
# boolean       : true / false
# integer       : 整数
# list[T]       : T 型の要素を持つリスト
# object        : キーと値のマッピング
# null           : null（YAML の null キーワード）
# T | null      : T 型または null
```

### 1. chrome_user_data_dir

| 項目 | 内容 |
| ------ | ------ |
| 型 | string |
| 必須 | **必須**（未指定で起動エラー） |
| デフォルト | なし（必ず明示指定すること） |
| 参考値 | `C:\Users\yourname\AppData\Local\Google\Chrome\User Data` |

#### 説明

Chrome の User Data ディレクトリの絶対パス。起動時に以下を検証する。

- パスが存在すること。
- ツール実行ユーザーに読み取り権限があること。

#### バリデーションエラー例

```text
[ERROR] chrome_user_data_dir が設定されていません。config.yml に記載してください。
[ERROR] chrome_user_data_dir のパスが存在しません: C:\path\to\User Data
```

### 2. chrome_profile

| 項目 | 内容 |
| ------ | ------ |
| 型 | string |
| 必須 | **必須**（未指定で起動エラー） |
| デフォルト | なし（必ず明示指定すること） |
| 参考値 | `Default` / `Profile 1` |

#### 説明

使用する Chrome プロファイルのフォルダ名。起動時に以下を検証する。

- `chrome_user_data_dir/<chrome_profile>` が存在すること。

#### バリデーションエラー例

```text
[ERROR] chrome_profile が設定されていません。config.yml に記載してください。
[ERROR] chrome_profile のディレクトリが存在しません: C:\...\User Data\Profile 1
```

### 3. dry_run

| 項目 | 内容 |
| ------ | ------ |
| 型 | boolean |
| 必須 | **必須**（未指定で起動エラー） |
| デフォルト | なし（必ず明示指定すること） |
| 有効値 | `true` / `false` |

#### 説明

`true` の場合、MF への書き込みは行わないシミュレーションモードで動作する。`false` の場合、実際に MF に登録を行う（本番実行）。意図せず本番実行することを防ぐため、デフォルトを設けず必ず明示指定とする。

#### バリデーションエラー例

```text
[ERROR] dry_run が設定されていません。true または false を config.yml に記載してください。
```

### 4. mapping_rules

| 項目 | 内容 |
| ------ | ------ |
| 型 | list[object] |
| 必須 | 任意（省略時は全取引が「未分類」となる） |
| デフォルト | 空リスト `[]` |

#### 説明

取引先名からカテゴリを決定するためのルール一覧。priority が大きいルールを優先して適用する。

#### 各ルールオブジェクトのスキーマ

| フィールド | 型 | 必須 | デフォルト | 説明 |
| ----------- | --- | ------ | ----------- | ------ |
| keyword | string | 必須 | — | マッチングに使うキーワード |
| category | string | 必須 | — | MF に登録するカテゴリ名 |
| match_mode | string | 任意 | `"contains"` | `"contains"` / `"starts_with"` / `"regex"` |
| priority | integer | 任意 | `0` | 数値が大きいほど先に評価される |

#### バリデーション

- `keyword` または `category` が空文字の場合はエラー。
- `match_mode` が上記3値以外の場合はエラー。

#### 初期推奨ルール（サンプル）

| keyword | category |
| --------- | ---------- |
| セブン | コンビニ |
| ファミリーマート | コンビニ |
| イオンシネマ | 娯楽／映画 |
| Yahoo!ショッピング | ショッピング（EC） |
| Google - GOOGLE PLAY | サブスクリプション／アプリ課金 |
| モス | 外食 |
| キャンドゥ | 雑貨／日用品 |
| つきじ海賓 | 外食／飲食 |
| MYB | 雑費 |
| giftee | ポイント・ギフト |

### 5. exclude_prefixes

| 項目 | 内容 |
| ------ | ------ |
| 型 | list[string] |
| 必須 | 任意 |
| デフォルト | `["PPCD_A_"]` |

#### 説明

取引番号がこのリスト内のいずれかのプレフィックスで始まる場合、その行を処理対象外（除外）とする。

#### バリデーション

- 各要素が空文字でないこと。

### 6. duplicate_detection

| 項目 | 内容 |
| ------ | ------ |
| 型 | object |
| 必須 | 任意 |
| デフォルト | 下記参照 |

#### 子フィールドのスキーマ

| フィールド | 型 | 必須 | デフォルト | 説明 |
| ----------- | --- | ------ | ----------- | ------ |
| keys | list[string] | 任意 | `["transaction_id", "datetime", "amount", "merchant"]` | 重複検出に使用するフィールドの優先順 |
| tolerance_seconds | integer | 任意 | `60` | 日時比較の許容幅（秒） |

#### 動作仕様

- `keys` の先頭フィールドから順に評価し、値が存在すればそのフィールドで重複判定を行う。
- `transaction_id` が存在する行は `transaction_id` のみで判定する。
- `transaction_id` が空または欠損の場合は `datetime + amount + merchant` の組み合わせで判定する。

### 7. parser

| 項目 | 内容 |
| ------ | ------ |
| 型 | object |
| 必須 | 任意 |
| デフォルト | 下記参照 |

#### 子フィールドのスキーマ

| フィールド | 型 | 必須 | デフォルト | 説明 |
| ----------- | --- | ------ | ----------- | ------ |
| encoding_priority | list[string] | 任意 | `["utf-8", "shift_jis"]` | CSV読み込み時に試す文字コード順 |
| date_formats | list[string] | 任意 | `["%Y/%m/%d %H:%M:%S"]` | 日付解析フォーマットの候補（先頭から順に試す） |

### 8. log_settings

| 項目 | 内容 |
| ------ | ------ |
| 型 | object |
| 必須 | 任意 |
| デフォルト | 下記参照 |

#### 子フィールドのスキーマ

| フィールド | 型 | 必須 | デフォルト | 説明 |
| ----------- | --- | ------ | ----------- | ------ |
| logs_dir | string \| null | 任意 | `".\\logs"`（`<tool_folder>\logs`） | ログ／スクリーンショット／エラーCSVの保存先。null または未指定でデフォルトを使用 |
| keep_logs | boolean | 任意 | `true` | false の場合、実行後にログを削除する |
| max_log_count | integer \| null | 任意 | `null`（無制限） | 保持するログファイル数の上限。超過した場合は古いものから削除 |
| max_total_log_size_mb | integer \| null | 任意 | `null`（無制限） | ログの合計サイズ上限（MB）。超過した場合は古いものから削除 |
| encrypt_logs | boolean | 任意 | `false` | true の場合、ログを暗号化して保存する（将来対応オプション） |

#### logs_dir のバリデーション

- 指定がある場合、書き込み権限を確認する。
- ディレクトリが存在しない場合は起動時に自動作成を試みる（失敗した場合はエラー）。

### 9. advanced

| 項目 | 内容 |
| ------ | ------ |
| 型 | object |
| 必須 | 任意 |
| デフォルト | 下記参照 |

#### 子フィールドのスキーマ

| フィールド | 型 | 必須 | デフォルト | 説明 |
| ----------- | --- | ------ | ----------- | ------ |
| playwright_browser_download | boolean | 任意 | `true` | 初回起動時に Playwright 用ブラウザを自動ダウンロードするか |
| screenshot_on_error | boolean | 任意 | `true` | エラー発生時にスクリーンショットを保存するか |

## サンプル config.yml（全項目）

```yaml
# ============================================================
# config.yml — PayPay→MoneyForward 自動登録ツール 設定ファイル
# ============================================================

# ------ 必須設定（3項目。未記載で起動エラー） ------

chrome_user_data_dir: "C:\\Users\\yourname\\AppData\\Local\\Google\\Chrome\\User Data"
chrome_profile: "Default"
dry_run: true   # true: ドライラン（書き込みなし） / false: 本番実行

# ------ 任意設定 ------

mapping_rules:
  - keyword: "セブン"
    category: "コンビニ"
    match_mode: "contains"
    priority: 100
  - keyword: "ファミリーマート"
    category: "コンビニ"
    match_mode: "contains"
    priority: 100
  - keyword: "イオンシネマ"
    category: "娯楽／映画"
    match_mode: "contains"
    priority: 100
  - keyword: "Yahoo!ショッピング"
    category: "ショッピング（EC）"
    match_mode: "contains"
    priority: 100
  - keyword: "Google - GOOGLE PLAY"
    category: "サブスクリプション／アプリ課金"
    match_mode: "contains"
    priority: 100
  - keyword: "モス"
    category: "外食"
    match_mode: "contains"
    priority: 100
  - keyword: "キャンドゥ"
    category: "雑貨／日用品"
    match_mode: "contains"
    priority: 100
  - keyword: "つきじ海賓"
    category: "外食／飲食"
    match_mode: "contains"
    priority: 100
  - keyword: "MYB"
    category: "雑費"
    match_mode: "contains"
    priority: 100
  - keyword: "giftee"
    category: "ポイント・ギフト"
    match_mode: "contains"
    priority: 100

exclude_prefixes:
  - "PPCD_A_"

duplicate_detection:
  keys:
    - "transaction_id"
    - "datetime"
    - "amount"
    - "merchant"
  tolerance_seconds: 60

parser:
  encoding_priority:
    - "utf-8"
    - "shift_jis"
  date_formats:
    - "%Y/%m/%d %H:%M:%S"

log_settings:
  logs_dir: null            # null → デフォルト <tool_folder>\logs を使用
  keep_logs: true
  max_log_count: null       # null = 無制限
  max_total_log_size_mb: null  # null = 無制限
  encrypt_logs: false

advanced:
  playwright_browser_download: true
  screenshot_on_error: true
```

## 改訂履歴

| 版 | 日付 | 変更概要 |
| ---- | ------ | --------- |
| 0.1 | 2026-03-27 | 初版作成 |
