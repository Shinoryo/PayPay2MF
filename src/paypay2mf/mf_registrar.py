"""MoneyForward ME への手動フォーム登録を Selenium で自動化するモジュール。"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from typing import TYPE_CHECKING, Self

from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from paypay2mf import mf_selectors
from paypay2mf.constants import AppConstants
from paypay2mf.mf_category_map import load_mf_category_map
from paypay2mf.mf_page import MFManualFormPage

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterator
    from types import TracebackType

    from selenium.webdriver.remote.webelement import WebElement

    from paypay2mf.models import AppConfig, Transaction


_LOG_MSG_CHROME_STARTED = "Chrome を起動しました"
_LOG_MSG_WAITING_FOR_LOGIN = (
    "Money Forward のトップページを開きました。ログイン後に Enter を押してください。"
)
_LOG_MSG_MF_PAGE_OPENED = "MF ページへ遷移しました"
_LOG_MSG_SCREENSHOT_SAVED = "スクリーンショットを保存しました: %s"
_LOG_MSG_SCREENSHOT_SKIPPED = (
    "Selenium driver が未初期化のため、スクリーンショットを保存しませんでした。"
)
_LOG_MSG_SCREENSHOT_SENSITIVE = (
    "スクリーンショットは機微情報を含む可能性があります。共有しないでください。"
)
_MSG_DRIVER_NOT_INITIALIZED = "Selenium driver が初期化されていません。"
_SCREENSHOT_FILE_PREFIX = "screenshot_"
_SELENIUM_MANAGER_AVOID_STATS_ENV_VAR = "SE_AVOID_STATS"
_SELENIUM_MANAGER_AVOID_STATS_ENABLED = "true"
_TEMP_PROFILE_PREFIX = "paypay2mf-selenium-"


@contextmanager
def _suppress_selenium_manager_stats() -> Iterator[None]:
    existing_value = os.environ.get(_SELENIUM_MANAGER_AVOID_STATS_ENV_VAR)
    if existing_value is not None:
        yield
        return

    os.environ[_SELENIUM_MANAGER_AVOID_STATS_ENV_VAR] = (
        _SELENIUM_MANAGER_AVOID_STATS_ENABLED
    )
    try:
        yield
    finally:
        os.environ.pop(_SELENIUM_MANAGER_AVOID_STATS_ENV_VAR, None)


def create_chrome_driver(options: ChromeOptions) -> Chrome:
    with _suppress_selenium_manager_stats():
        return Chrome(options=options)


class MFRegistrar:
    """MF の手動入力フォームへの登録を管理するコンテキストマネージャー。"""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        """MFRegistrar を初期化する。"""
        self._config = config
        self._logger = logger
        self._driver = None
        self._temporary_profile_dir = None
        self._manual_form_page = None

    def __enter__(self) -> Self:
        """Chrome を起動し、MF 手動入力フォームへ移動する。"""
        self._temporary_profile_dir = Path(
            tempfile.mkdtemp(prefix=_TEMP_PROFILE_PREFIX)
        )
        options = ChromeOptions()
        options.page_load_strategy = "eager"
        options.add_argument(f"--user-data-dir={self._temporary_profile_dir}")
        options.add_argument("--start-maximized")
        self._driver = create_chrome_driver(options)
        self._logger.info(_LOG_MSG_CHROME_STARTED)

        self._open_moneyforward_page()
        self._wait_for_manual_login()
        self._open_household_book_tab()

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
        """ブラウザを安全にクローズする。"""
        self._close()

    def register(self, tx: Transaction) -> None:
        """1件の取引を MF 手動入力フォームへ登録する。"""
        try:
            self._ensure_manual_form_page().register_transaction(tx)
        except Exception:
            if self._config.advanced.screenshot_on_error:
                shot_path = self._take_screenshot()
                if shot_path is None:
                    self._logger.warning(_LOG_MSG_SCREENSHOT_SKIPPED)
                else:
                    self._logger.warning(_LOG_MSG_SCREENSHOT_SAVED, shot_path.name)
                    self._logger.warning(_LOG_MSG_SCREENSHOT_SENSITIVE)
            raise

    def open_manual_form(self) -> WebElement:
        """スモークテスト用に手入力モーダルを開く。"""
        return self._ensure_manual_form_page().open_manual_form()

    def _build_manual_form_page(self) -> MFManualFormPage:
        return MFManualFormPage(
            self._ensure_driver(),
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

    def _take_screenshot(self) -> Path | None:
        """スクリーンショットを保存する。"""
        if self._driver is None:
            return None

        timestamp = datetime.now().strftime(AppConstants.TIMESTAMP_FORMAT)  # noqa: DTZ005
        logs_dir = self._config.log_settings.logs_dir
        if logs_dir is None:
            base_dir = self._config.runtime_base_dir or Path.cwd()
            logs_dir = base_dir / AppConstants.DEFAULT_LOGS_DIR
        logs_dir.mkdir(parents=True, exist_ok=True)
        out_path = (
            logs_dir
            / f"{_SCREENSHOT_FILE_PREFIX}{timestamp}{AppConstants.PNG_EXTENSION}"
        )
        self._driver.save_screenshot(str(out_path))
        return out_path

    def _close(self) -> None:
        """Selenium のブラウザを終了する。"""
        try:
            if self._driver is not None:
                self._driver.quit()
        finally:
            if self._temporary_profile_dir is not None:
                rmtree(self._temporary_profile_dir, ignore_errors=True)

    def _open_moneyforward_page(self) -> None:
        self._ensure_driver().get(mf_selectors.TOP_PAGE_URL)

    def _wait_for_manual_login(self) -> None:
        self._logger.info(_LOG_MSG_WAITING_FOR_LOGIN)
        input("Money Forward へログインしたら Enter を押してください: ")

    def _open_household_book_tab(self) -> None:
        tab = self._wait(mf_selectors.NAVIGATION_TIMEOUT_MS).until(
            self._find_household_book_tab,
        )
        tab.click()
        self._wait(mf_selectors.NAVIGATION_TIMEOUT_MS).until(
            expected_conditions.url_contains(mf_selectors.MANUAL_FORM_URL),
        )

    def _find_household_book_tab(self, driver: Chrome) -> WebElement | bool:
        for element in driver.find_elements(
            By.CSS_SELECTOR,
            mf_selectors.HOUSEHOLD_BOOK_TAB_CSS,
        ):
            if element.is_displayed() and element.is_enabled():
                return element

        for element in driver.find_elements(
            By.XPATH,
            mf_selectors.HOUSEHOLD_BOOK_TAB_XPATH,
        ):
            if element.is_displayed() and element.is_enabled():
                return element

        return False

    def _ensure_driver(self) -> Chrome:
        if self._driver is None:
            raise RuntimeError(_MSG_DRIVER_NOT_INITIALIZED)
        return self._driver

    def _wait(self, timeout_ms: int) -> WebDriverWait:
        return WebDriverWait(
            self._ensure_driver(),
            timeout_ms / 1000,
            poll_frequency=0.2,
        )
