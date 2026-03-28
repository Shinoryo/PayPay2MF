"""Money Forward 手入力フォームの Page Object。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src import mf_selectors
from src.mf_category_map import load_mf_category_map

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from playwright.sync_api import Locator, Page

    from src.models import Transaction


class MFManualFormPage:
    """Money Forward 手入力ページの DOM 契約をまとめる。"""

    def __init__(
        self,
        page: Page,
        logger: logging.Logger,
        mf_account: str,
        *,
        mf_categories_path: Path | None = None,
        category_map: dict[str, str] | None = None,
    ) -> None:
        self._page = page
        self._logger = logger
        self._mf_account = mf_account
        self._category_map = (
            load_mf_category_map(mf_categories_path)
            if category_map is None
            else dict(category_map)
        )

    def open(self) -> None:
        """入出金ページへ遷移し、手入力ボタンの表示を確認する。"""
        self._page.goto(mf_selectors.MANUAL_FORM_URL)
        self._page.wait_for_selector(
            mf_selectors.OPEN_MANUAL_FORM_BUTTON,
            timeout=mf_selectors.NAVIGATION_TIMEOUT_MS,
        )

    def open_manual_form(self) -> Locator:
        """手入力モーダルを開き、表示完了を待つ。"""
        self._page.click(mf_selectors.OPEN_MANUAL_FORM_BUTTON)
        modal = self._page.locator(mf_selectors.MANUAL_FORM_MODAL)
        modal.wait_for(state="visible", timeout=mf_selectors.MODAL_TIMEOUT_MS)
        return modal

    def register_transaction(self, tx: Transaction) -> None:
        """1件の取引を手入力フォームへ反映して保存する。"""
        modal = self.open_manual_form()

        if tx.direction == "in":
            modal.locator(mf_selectors.PLUS_PAYMENT_INPUT).click()
        else:
            modal.locator(mf_selectors.MINUS_PAYMENT_INPUT).click()

        date_input = modal.locator(mf_selectors.DATE_INPUT)
        date_input.fill(tx.date.strftime("%Y/%m/%d"))
        date_input.press("Escape")

        modal.locator(mf_selectors.AMOUNT_INPUT).fill(str(tx.amount))
        self._select_account(modal)

        if tx.category not in ("未分類", ""):
            self._select_category(modal, tx.category)

        modal.locator(mf_selectors.MEMO_INPUT).fill(tx.memo)
        modal.locator(mf_selectors.SUBMIT_BUTTON).click()

        self._page.locator(mf_selectors.CLOSE_BUTTON).wait_for(
            state="visible",
            timeout=mf_selectors.SUBMIT_TIMEOUT_MS,
        )
        self._page.locator(mf_selectors.CLOSE_BUTTON).click()

    def _select_account(self, modal: Locator) -> None:
        option_value: str | None = self._page.evaluate(
            mf_selectors.ACCOUNT_OPTION_LOOKUP_SCRIPT,
            self._mf_account,
        )
        if option_value is None:
            msg = (
                f"口座 '{self._mf_account}' が MF で見つかりません。"
                "config.yml の mf_account を確認してください。"
            )
            raise ValueError(msg)
        modal.locator(mf_selectors.ACCOUNT_SELECT).select_option(value=option_value)

    def _select_category(self, modal: Locator, category: str) -> None:
        large_name = self._category_map.get(category)
        if large_name is None:
            self._logger.warning(
                "カテゴリ '%s' がマップに存在しません。未分類で登録します。",
                category,
            )
            return

        modal.locator(mf_selectors.CATEGORY_DROPDOWN).click()
        self._page.locator(mf_selectors.large_category_option(large_name)).first.hover()
        self._page.locator(mf_selectors.middle_category_option(category)).first.click()
