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

    from src.models import AppConfig, Transaction

# NOTE: Playwright はオプション依存のため実行時にのみ import する
# playwright install chromium を事前に実行しておくこと


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
            NotImplementedError: TODO T01/T02 が未実装の場合。
        """
        # TODO T01: MF 手入力フォームの各セレクターを実機確認後に実装する
        # TODO T01: 日付・金額・内容・カテゴリ・口座・入出金切替の各セレクターを特定すること
        # TODO T02: tx.category が MF の選択肢と完全一致するか実機確認後に検証すること
        try:
            raise NotImplementedError(
                "MF 手入力フォームのセレクターが未実装です。"
                "TODO T01: 実機ブラウザで確認し、各セレクターを実装してください。",
            )
        except Exception:
            if self._config.advanced.screenshot_on_error:
                label = tx.merchant
                shot_path = self._take_screenshot(label)
                self._logger.info(
                    "スクリーンショットを保存しました: %s", shot_path.name,
                )
            raise

    def _navigate_to_manual_form(self) -> None:
        """MF の手動入力フォームへ遷移する。

        Raises:
            NotImplementedError: TODO T01 が未実装の場合。
        """
        # TODO T01: Money Forward ME の「手動で追加」フォームへの遷移を実装する
        # 例: self._page.goto("https://moneyforward.com/...")
        #     self._page.click("selector_for_manual_add_button")
        raise NotImplementedError(
            "MF 手入力フォームへの遷移が未実装です。TODO T01 を参照してください。",
        )

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
