"""MoneyForward ME への手動フォーム登録を Playwright で自動化するモジュール。

Chrome プロフィールを継承して起動し、MF 手動入力フォームへ自動入力する。
実証セレクターは TODO T01 としてプレースホルダーが入っている。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import Self

if TYPE_CHECKING:
    import logging
    from types import TracebackType

    from playwright.sync_api import Locator

    from src.models import AppConfig, Transaction

# NOTE: Playwright はオプション依存のため実行時にのみ import する
# playwright install chromium を事前に実行しておくこと

# 中項目名 → 大項目名 逆引きマップ（MF 実機 HTML ソースから抽出）
_MIDDLE_TO_LARGE: dict[str, str] = {
    # 収入
    "給与": "収入", "一時所得": "収入", "事業・副業": "収入", "年金": "収入",
    "配当所得": "収入", "不動産所得": "収入", "不明な入金": "収入",
    "その他入金": "収入",
    # 食費
    "食費": "食費", "食料品": "食費", "外食": "食費", "朝ご飯": "食費",
    "昼ご飯": "食費", "夜ご飯": "食費", "カフェ": "食費", "その他食費": "食費",
    # 日用品
    "日用品": "日用品", "子育て用品": "日用品", "ドラッグストア": "日用品",
    "おこづかい": "日用品", "ペット用品": "日用品", "タバコ": "日用品",
    "その他日用品": "日用品",
    # 趣味・娯楽
    "アウトドア": "趣味・娯楽", "ゴルフ": "趣味・娯楽", "スポーツ": "趣味・娯楽",
    "映画・音楽・ゲーム": "趣味・娯楽", "本": "趣味・娯楽", "旅行": "趣味・娯楽",
    "秘密の趣味": "趣味・娯楽", "その他趣味・娯楽": "趣味・娯楽",
    # 交際費
    "交際費": "交際費", "飲み会": "交際費", "プレゼント代": "交際費",
    "冠婚葬祭": "交際費", "その他交際費": "交際費",
    # 交通費
    "交通費": "交通費", "電車": "交通費", "バス": "交通費",
    "タクシー": "交通費", "飛行機": "交通費", "その他交通費": "交通費",
    # 衣服・美容
    "衣服": "衣服・美容", "クリーニング": "衣服・美容",
    "美容院・理髪": "衣服・美容",
    "化粧品": "衣服・美容", "アクセサリー": "衣服・美容",
    "その他衣服・美容": "衣服・美容",
    # 健康・医療
    "フィットネス": "健康・医療", "ボディケア": "健康・医療", "医療費": "健康・医療",
    "薬": "健康・医療", "その他健康・医療": "健康・医療",
    # 自動車
    "自動車ローン": "自動車", "道路料金": "自動車", "ガソリン": "自動車",
    "駐車場": "自動車", "車両": "自動車", "車検・整備": "自動車",
    "自動車保険": "自動車", "その他自動車": "自動車",
    # 教養・教育
    "書籍": "教養・教育", "新聞・雑誌": "教養・教育", "習いごと": "教養・教育",
    "学費": "教養・教育", "塾": "教養・教育", "その他教養・教育": "教養・教育",
    # 特別な支出
    "家具・家電": "特別な支出", "住宅・リフォーム": "特別な支出",
    "その他特別な支出": "特別な支出",
    # 現金・カード
    "ATM引き出し": "現金・カード", "カード引き落とし": "現金・カード",
    "電子マネー": "現金・カード", "使途不明金": "現金・カード",
    "その他現金・カード": "現金・カード",
    # 水道・光熱費
    "光熱費": "水道・光熱費", "電気代": "水道・光熱費", "ガス・灯油代": "水道・光熱費",
    "水道代": "水道・光熱費", "その他水道・光熱費": "水道・光熱費",
    # 通信費
    "携帯電話": "通信費", "固定電話": "通信費", "インターネット": "通信費",
    "放送視聴料": "通信費", "情報サービス": "通信費",
    "宅配便・運送": "通信費", "その他通信費": "通信費",
    # 住宅
    "住宅": "住宅", "家賃・地代": "住宅", "ローン返済": "住宅",
    "管理費・積立金": "住宅", "地震・火災保険": "住宅", "その他住宅": "住宅",
    # 税・社会保障
    "所得税・住民税": "税・社会保障", "年金保険料": "税・社会保障",
    "健康保険": "税・社会保障", "その他税・社会保障": "税・社会保障",
    # 保険
    "生命保険": "保険", "医療保険": "保険", "その他保険": "保険",
    # その他
    "仕送り": "その他", "事業経費": "その他", "事業原価": "その他",
    "事業投資": "その他", "寄付金": "その他", "雑費": "その他",
}


class MFRegistrar:
    """MF の手動入力フォームへの登録を管理するコンテキストマネージャー。

    ``with`` 文で使用し、Chrome 起動から登録完了までを管理する。
    登録常にブラウザを安全にクローズする。
    """
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        """MFRegistrar を初期化する。

        Args:
            config: アプリケーション設定。
            logger: ログ出力に使用する Logger インスタンス。
        """
        self._config = config
        self._logger = logger
        self._playwright = None
        self._context = None
        self._page = None

    def __enter__(self) -> Self:
        """Chrome を起動し、MF 手動入力フォームへ移動する。

        Returns:
            self

        Raises:
            NotImplementedError: TODO T01 が未実装の場合。
        """
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        self._playwright = sync_playwright().start()

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self._config.chrome_user_data_dir,
            channel="chrome",
            headless=False,
            args=[f"--profile-directory={self._config.chrome_profile}"],
        )
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )
        self._logger.info("Chrome を起動しました")

        self._navigate_to_manual_form()
        self._logger.info("MF ページへ遷移しました")

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """ブラウザを安全にクローズする。

        Args:
            exc_type: 例外の型。なければ None。
            exc_val: 例外の値。なければ None。
            exc_tb: トレースバック。なければ None。
        """
        self._close()

    def register(self, tx: Transaction) -> None:
        """1件の取引を MF 手動入力フォームへ登録する。

        Args:
            tx: 登録する Transaction。

        Raises:
            ValueError: 口座名が MF で見つからない場合。
            playwright.sync_api.TimeoutError: ページ操作がタイムアウトした場合。
        """
        try:
            # モーダルを開く
            self._page.click('button.modal-switch[href="#user_asset_act_new"]')
            modal = self._page.locator("#user_asset_act_new")
            modal.wait_for(state="visible", timeout=10_000)

            # 入出金切替（支出 / 収入）
            if tx.direction == "in":
                modal.locator("input.plus-payment").click()
            else:
                modal.locator("input.minus-payment").click()

            # 日付（yyyy/mm/dd 形式）
            date_input = modal.locator("#updated-at")
            date_input.fill(tx.date.strftime("%Y/%m/%d"))
            date_input.press("Escape")  # datepicker を閉じる

            # 金額
            modal.locator("#appendedPrependedInput").fill(str(tx.amount))

            # 口座
            self._select_account(modal)

            # カテゴリ
            if tx.category not in ("未分類", ""):
                self._select_category(modal, tx.category)

            # 内容（メモ）
            modal.locator("#js-content-field").fill(tx.memo)

            # 保存
            modal.locator("#submit-button").click()

            # 保存完了待ち（「閉じる」ボタンが表示されるまで）
            self._page.locator("#cancel-button").wait_for(
                state="visible", timeout=15_000,
            )
            self._page.locator("#cancel-button").click()

        except Exception:
            if self._config.advanced.screenshot_on_error:
                shot_path = self._take_screenshot(tx.merchant)
                self._logger.info(
                    "スクリーンショットを保存しました: %s", shot_path.name,
                )
            raise

    def _navigate_to_manual_form(self) -> None:
        """MF の入出金ページへ遷移し、手入力ボタンの表示を確認する。"""
        self._page.goto("https://moneyforward.com/cf")
        self._page.wait_for_selector(
            'button.modal-switch[href="#user_asset_act_new"]',
            timeout=30_000,
        )

    def _select_account(self, modal: Locator) -> None:
        """MF 手入力フォームの口座を設定する。

        config.mf_account と前方一致するオプションを選択する。

        Args:
            modal: モーダルの Playwright Locator。

        Raises:
            ValueError: 口座が MF で見つからない場合。
        """
        account_name = self._config.mf_account
        option_value: str | None = self._page.evaluate(
            """(name) => {
                const sel = document.querySelector(
                    '#user_asset_act_new #user_asset_act_sub_account_id_hash'
                );
                if (!sel) return null;
                for (const opt of sel.options) {
                    if (opt.text.trim().startsWith(name)) return opt.value;
                }
                return null;
            }""",
            account_name,
        )
        if option_value is None:
            msg = (
                f"口座 '{account_name}' が MF で見つかりません。"
                "config.yml の mf_account を確認してください。"
            )
            raise ValueError(msg)
        modal.locator("#user_asset_act_sub_account_id_hash").select_option(
            value=option_value,
        )

    def _select_category(self, modal: Locator, category: str) -> None:
        """MF 手入力フォームのカテゴリ（大項目・中項目）を設定する。

        大項目ドロップダウンを開き、大項目をホバーしてサブメニューを表示させ
        中項目をクリックする。カテゴリがマップに存在しない場合は未分類のまま
        登録し、WARNING ログを出力する。

        Args:
            modal: モーダルの Playwright Locator。
            category: 設定する中項目名。
        """
        large_name = _MIDDLE_TO_LARGE.get(category)
        if large_name is None:
            self._logger.warning(
                "カテゴリ '%s' がマップに存在しません。未分類で登録します。",
                category,
            )
            return

        # 大項目ドロップダウンを開く
        modal.locator(".btn_l_ctg .v_l_ctg").click()

        # 大項目をホバーしてサブメニューを展開
        self._page.locator(f"a.l_c_name:text-is('{large_name}')").first.hover()

        # 中項目をクリック
        self._page.locator(f"a.m_c_name:text-is('{category}')").first.click()

    def _take_screenshot(self, label: str) -> Path:
        """スクリーンショットを保存する。

        screenshot_on_error が True の場合のみ保存する。

        Args:
            label: スクリーンショットファイルの基名（拡張子なし）。

        Returns:
            保存したスクリーンショットファイルの Path。
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        logs_dir = (
            self._config.log_settings.logs_dir or Path(__file__).parent.parent / "logs"
        )
        logs_dir.mkdir(parents=True, exist_ok=True)
        safe_label = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in label
        )[:20]
        out_path = logs_dir / f"screenshot_{timestamp}_{safe_label}.png"
        if self._page is not None:
            self._page.screenshot(path=str(out_path))
        return out_path

    def _close(self) -> None:
        """Playwright のブラウザとコンテキストを終了する。"""
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
