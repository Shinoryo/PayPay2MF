"""MoneyForward ME への手動フォーム登録を Playwright で自動化するモジュール。

Chrome プロフィールを継承して起動し、MF 手動入力フォームへ自動入力する。
実証セレクターは TODO T01 としてプレースホルダーが入っている。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import Self

from src.constants import AppConstants
from src.mf_category_map import load_mf_category_map
from src.mf_page import MFManualFormPage

if TYPE_CHECKING:
    import logging
    from types import TracebackType

    from playwright.sync_api import Locator

    from src.models import AppConfig, Transaction

# NOTE: Playwright はオプション依存のため実行時にのみ import する
# playwright install chromium を事前に実行しておくこと

# ブラウザ起動やスクリーンショット保存に使う定数。
_LOG_MSG_CHROME_STARTED = "Chrome を起動しました"
_LOG_MSG_MF_PAGE_OPENED = "MF ページへ遷移しました"
_LOG_MSG_SCREENSHOT_SAVED = "スクリーンショットを保存しました: %s"
_LOG_MSG_SCREENSHOT_SENSITIVE = (
    "スクリーンショットは機微情報を含む可能性があります。共有しないでください。"
)
_MSG_PAGE_NOT_INITIALIZED = "Playwright page が初期化されていません。"
_SCREENSHOT_FILE_PREFIX = "screenshot_"


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
        self._manual_form_page = None

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
            channel=AppConstants.CHROME_CHANNEL,
            headless=False,
            args=[
                AppConstants.CHROME_PROFILE_DIRECTORY_ARG.format(
                    self._config.chrome_profile,
                ),
            ],
        )
        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        self._logger.info(_LOG_MSG_CHROME_STARTED)

        self._manual_form_page = self._build_manual_form_page()
        self._manual_form_page.open()
        self._logger.info(_LOG_MSG_MF_PAGE_OPENED)

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
            self._ensure_manual_form_page().register_transaction(tx)

        except Exception:
            if self._config.advanced.screenshot_on_error:
                shot_path = self._take_screenshot()
                self._logger.warning(_LOG_MSG_SCREENSHOT_SAVED, shot_path.name)
                self._logger.warning(_LOG_MSG_SCREENSHOT_SENSITIVE)
            raise

    def open_manual_form(self) -> Locator:
        """スモークテスト用に手入力モーダルを開く。"""
        return self._ensure_manual_form_page().open_manual_form()

    def _build_manual_form_page(self) -> MFManualFormPage:
        if self._page is None:
            raise RuntimeError(_MSG_PAGE_NOT_INITIALIZED)
        return MFManualFormPage(
            self._page,
            self._logger,
            self._config.mf_account,
            category_map=load_mf_category_map(
                self._config.advanced.mf_categories_path,
            ),
        )

    def _ensure_manual_form_page(self) -> MFManualFormPage:
        if self._manual_form_page is None:
            self._manual_form_page = self._build_manual_form_page()
        return self._manual_form_page

    def _take_screenshot(self) -> Path:
        """スクリーンショットを保存する。

        screenshot_on_error が True の場合のみ保存する。

        Returns:
            保存したスクリーンショットファイルの Path。
        """
        timestamp = datetime.now().strftime(AppConstants.TIMESTAMP_FORMAT)  # noqa: DTZ005
        logs_dir = (
            self._config.log_settings.logs_dir
            or Path(__file__).parent.parent / AppConstants.DEFAULT_LOGS_DIR
        )
        logs_dir.mkdir(parents=True, exist_ok=True)
        out_path = (
            logs_dir
            / f"{_SCREENSHOT_FILE_PREFIX}{timestamp}{AppConstants.PNG_EXTENSION}"
        )
        if self._page is not None:
            self._page.screenshot(path=str(out_path))
        return out_path

    def _close(self) -> None:
        """Playwright のブラウザとコンテキストを終了する。"""
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
