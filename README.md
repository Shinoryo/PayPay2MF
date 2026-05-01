# PayPay2MF

PayPay の利用明細 CSV を Money Forward ME へ登録する
Windows 向けローカル CLI ツールです。

## ドキュメント

- [docs/基本設計書.md](docs/基本設計書.md): 全体構成、処理フロー、責務分担
- [docs/設定ファイル仕様書.md](docs/設定ファイル仕様書.md): 設定項目の型、必須条件、パス仕様
- [docs/テスト仕様書.md](docs/テスト仕様書.md): テストケース、受入手順、確認観点

## 概要

- PayPay CSV を読込み、除外、カテゴリ付与、重複検知を行ったうえで
  Money Forward ME の手入力フォームへ登録する
- dry_run ではブラウザを起動せず、CSV 変換結果と件数サマリーだけを確認できる
- 本番実行では Selenium が Chrome を起動し、手動ログイン後に登録を続行する
- 重複検知は local JSON と Firestore backend の両方に対応する
- Firestore 既存データの `date_bucket` 補完は、本体とは別の
  `paypay2mf-firestore-backfill` CLI で行う

## 動作環境

| 項目 | 内容 |
| ---- | ---- |
| OS | Windows 11 |
| Python | 3.11 以上 |
| ブラウザ | Google Chrome（最新版） |
| 主要依存 | selenium / PyYAML / google-cloud-firestore（任意） |

## セットアップ

通常利用:

```bash
pip install -e .
```

開発用依存を含める場合:

```bash
pip install -e ".[dev]"
```

CI相当のテスト依存のみを導入する場合:

```bash
pip install -e ".[ci]"
```

## クイックスタート

### 1. 最小設定

必須項目は `dry_run`、`input_csv`、`mf_account` の 3 つです。

```yaml
dry_run: true
input_csv: "C:\\Users\\yourname\\Downloads\\paypay_history.csv"
mf_account: "PayPay"
```

設定詳細は [docs/設定ファイル仕様書.md](docs/設定ファイル仕様書.md) を参照してください。

### 2. dry_run で確認

```bash
paypay2mf
```

- ブラウザは起動しません
- CSV 読込、変換、除外、重複判定までを実行します
- 重複履歴は更新しません

### 3. 本番実行

```yaml
dry_run: false
```

```bash
paypay2mf
```

- Selenium が Chrome を起動します
- Money Forward ME に手動ログインして Enter を押すと続行します
- 家計簿タブ経由で `/cf` に遷移し、手入力フォームへ1件ずつ登録します

> ⚠️ 手動ログイン待機には対話コンソール（PowerShell・コマンドプロンプト等）が必要です。
> ダブルクリック起動や stdin リダイレクト実行では stdin が利用できず即時エラーになります。

登録自体が成功しても重複履歴の更新に失敗した場合は、その場で処理を中断します。
同じ CSV をそのまま再実行すると重複登録につながる可能性があるため、
`logs_dir` 配下のログを確認してから再開してください。

## 実行時の注意

### パス解決

- `config.yml` は `--config` > `PAYPAY2MF_CONFIG` >
  カレントディレクトリ > モジュール同居の順で探索します
- 相対パスは実行時カレントディレクトリではなく
  `config.yml` の配置ディレクトリ基準で解決します

### 保存物と機微情報

- `logs_dir` 配下には app ログ、解析エラー CSV、登録失敗 CSV、
  必要時のスクリーンショット、local backend 用 `processed.json` が作成されます
- app ログは件数サマリー中心ですが、CSV、スクリーンショット、
  `processed.json`、認証情報 JSON は機微情報を含む可能性があります
- 共有フォルダやクラウド同期先ではなく、ローカル保管を前提にしてください

### 重複検知

- `duplicate_detection.backend: "local"` は単一インスタンス運用を前提とします
- `dry_run: true` では local / gcloud いずれの履歴も更新しません
- 重複判定は行単位指紋（sha256）で行います
- 指紋入力項目は `取引日（CSV文字列）`、`取引内容`、`取引先`、
  `出金金額（正規化）`、`入金金額（正規化）`、`取引方法`、`支払い区分`、`利用者`
- 同一 `transaction_id` でも、指紋が異なる行は別取引として処理します

## Smoke Test

UI 契約の一次確認用に smoke test を用意しています。

```powershell
$env:PAYPAY2MF_RUN_SMOKE_TEST = "1"
$env:PAYPAY2MF_SMOKE_MF_ACCOUNT = "<MF Account Name>"
# 任意
$env:PAYPAY2MF_SMOKE_LOGS_DIR = "<Optional Smoke Logs Dir>"
python -m pytest -q -m smoke_test tests/test_mf_smoke.py
```

- Selenium が一時プロファイルで Chrome を起動します
- 手動ログイン後、手入力モーダルが開けることだけを確認します
- 実データの送信や保存は行いません

詳細は [docs/テスト仕様書.md](docs/テスト仕様書.md) を参照してください。

## Firestore backend（任意）

Firestore を使う場合は、gcloud extra を導入し、
`duplicate_detection.backend: "gcloud"` と
`gcloud_credentials_path` を設定してください。

```bash
pip install "paypay2mf[gcloud]"
```

```yaml
duplicate_detection:
  backend: "gcloud"
  tolerance_seconds: 60
  database_id: "paypay2mf"  # 未指定時は "(default)"

gcloud_credentials_path: "./secrets/paypay2mf-credentials.json"
```

- 本体アプリの `dry_run` は通常実行だけに適用されます
- backfill CLI の dry-run は `--dry-run` 引数で個別に制御します

backfill の最小設定は次の 2 点です。

- `duplicate_detection.backend: "gcloud"`
- `gcloud_credentials_path`

`duplicate_detection.database_id` は任意です。複数データベース運用時は
対象 DB ID（例: `paypay2mf`）を明示指定してください。

最初の確認は dry-run を推奨します。

```bash
paypay2mf-firestore-backfill --config .\config.yml --dry-run
paypay2mf-firestore-backfill --config .\config.yml
```

`--limit` や backfill の詳細な前提条件は
[docs/基本設計書.md](docs/基本設計書.md) と
[docs/設定ファイル仕様書.md](docs/設定ファイル仕様書.md) を参照してください。

設計上の背景は [docs/基本設計書.md](docs/基本設計書.md) を参照してください。

## 開発

品質ゲートの再現例:

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
markdownlint-cli2 README.md docs/**/*.md
python -m pip_audit --skip-editable --ignore-vuln CVE-2026-4539
```

`pip-audit` は現時点で監査ツール側依存の
`CVE-2026-4539` を一時的に除外して実行します。

## ライセンス

- ソースコードは MIT ライセンスです
- 詳細は LICENSE を参照してください

## リリース履歴

| 版 | 日付 | 変更概要 |
| ---- | ------ | --------- |
| 1.1.5 | 2026-04-30 | Firestore gcloud backend の DB 指定処理を修正し、Client 初期化時の引数名不一致による起動失敗を解消 |
| 1.1.4 | 2026-04-30 | gcloud backend 利用時に Firestore の database_id を明示指定できるように修正 |
| 1.1.3 | 2026-04-30 | import を明示的なモジュールパスに変更し、起動時に Selenium のモジュール解決に失敗する問題を修正 |
| 1.1.2 | 2026-04-30 | ビルドアーティファクトにドキュメントを追加 |
| 1.1.1 | 2026-04-30 | Release Buildの依存最適化とpipキャッシュ導入により、配布フローを軽量化 |
| 1.1.0 | 2026-04-30 | 自動操作基盤を Selenium ベースに見直し<br>ドキュメントを再編<br>Money Forward への遷移先をトップページからサインインページへ修正<br>取引メモ生成ロジックを変更し、メモの主情報を「取引内容」起点から「取引先」起点へ変更 |
| 1.0.0 | 2026-03-31 | 初版作成 |
