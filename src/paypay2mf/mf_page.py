"""Money Forward 手入力フォームの Page Object。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from paypay2mf import mf_selectors
from paypay2mf.constants import AppConstants
from paypay2mf.mf_category_map import load_mf_category_map

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from playwright.sync_api import Locator, Page

    from paypay2mf.models import Transaction


# フォーム入力時の分岐や警告に使う定数。
_SKIP_CATEGORY_VALUES = {
    AppConstants.DEFAULT_CATEGORY,
    AppConstants.EMPTY_STRING,
}
_ACCOUNT_NOT_FOUND_MESSAGE = (
    "口座 '{account_name}' が MF で見つかりません。"
    "config.yml の mf_account に完全一致する口座名を確認してください。"
)
_CATEGORY_NOT_FOUND_WARNING = (
    "カテゴリ '%s' がマップに存在しません。未分類で登録します。"
)
_SUBMIT_REPORTED_ERROR_MESSAGE = "MF 登録に失敗しました。{detail}"
_SUBMIT_ERROR_FALLBACK_DETAIL = "送信後にフォームエラーが表示されました。"


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
        modal.wait_for(
            state=AppConstants.LOCATOR_STATE_VISIBLE,
            timeout=mf_selectors.MODAL_TIMEOUT_MS,
        )
        return modal

    def register_transaction(self, tx: Transaction) -> None:
        """1件の取引を手入力フォームへ反映して保存する。"""
        modal = self.open_manual_form()

        if tx.direction == AppConstants.DIRECTION_IN:
            modal.locator(mf_selectors.PLUS_PAYMENT_INPUT).click()
        else:
            modal.locator(mf_selectors.MINUS_PAYMENT_INPUT).click()

        date_input = modal.locator(mf_selectors.DATE_INPUT)
        date_input.fill(tx.date.strftime(AppConstants.FORM_DATE_FORMAT))
        date_input.press(AppConstants.KEY_ESCAPE)

        modal.locator(mf_selectors.AMOUNT_INPUT).fill(str(tx.amount))
        self._select_account(modal)

        if tx.category not in _SKIP_CATEGORY_VALUES:
            self._select_category(modal, tx.category)

        modal.locator(mf_selectors.MEMO_INPUT).fill(tx.memo)
        modal.locator(mf_selectors.SUBMIT_BUTTON).click()

        self._wait_for_submit_outcome(modal)

    def _wait_for_submit_outcome(self, modal: Locator) -> None:
        outcome_handle = self._page.wait_for_function(
            mf_selectors.SUBMIT_OUTCOME_SCRIPT,
            {
                "modalSelector": mf_selectors.MANUAL_FORM_MODAL,
                "errorSelectors": list(mf_selectors.SUBMIT_ERROR_FEEDBACK_SELECTORS),
            },
            timeout=mf_selectors.SUBMIT_TIMEOUT_MS,
        )
        outcome = outcome_handle.json_value()

        if isinstance(outcome, dict) and outcome.get("status") == "error":
            detail = str(
                outcome.get("text")
                or outcome.get("selector")
                or _SUBMIT_ERROR_FALLBACK_DETAIL
            )
            msg = _SUBMIT_REPORTED_ERROR_MESSAGE.format(detail=detail)
            raise RuntimeError(msg)

        if not isinstance(outcome, dict) or outcome.get("status") != "closed":
            modal.wait_for(
                state=AppConstants.LOCATOR_STATE_HIDDEN,
                timeout=mf_selectors.SUBMIT_TIMEOUT_MS,
            )

    def _select_account(self, modal: Locator) -> None:
        option_value: str | None = self._page.evaluate(
            mf_selectors.ACCOUNT_OPTION_LOOKUP_SCRIPT,
            self._mf_account,
        )
        if option_value is None:
            msg = _ACCOUNT_NOT_FOUND_MESSAGE.format(account_name=self._mf_account)
            raise ValueError(msg)
        modal.locator(mf_selectors.ACCOUNT_SELECT).select_option(value=option_value)

    def _select_category(self, modal: Locator, category: str) -> None:
        large_name = self._category_map.get(category)
        if large_name is None:
            self._logger.warning(_CATEGORY_NOT_FOUND_WARNING, category)
            return

        modal.locator(mf_selectors.CATEGORY_DROPDOWN).click()
        self._page.locator(mf_selectors.large_category_option(large_name)).first.hover()
        self._page.locator(mf_selectors.middle_category_option(category)).first.click()
