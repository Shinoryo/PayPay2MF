"""Money Forward 手入力フォームの Page Object。"""

from __future__ import annotations

import re
from contextlib import suppress
from typing import TYPE_CHECKING

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    JavascriptException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

from paypay2mf import mf_selectors
from paypay2mf.constants import AppConstants
from paypay2mf.mf_category_map import load_mf_category_map

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

    from paypay2mf.models import Transaction


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
_SUBMIT_OUTCOME_TIMEOUT_MESSAGE = (
    "MF 登録結果を確認できませんでした。"
    "成功モーダルが閉じないか、エラー表示を検知できませんでした。"
)
_AMOUNT_INPUT_NOT_READY_MESSAGE = (
    "手入力フォームの金額入力欄が操作可能になりませんでした。"
    "フォーム切替の反映待ちに失敗した可能性があります。"
)
_SUBMIT_SUCCESS_MESSAGE_TEXT = "入力を保存しました。"
_ACCOUNT_NAME_SUFFIX_PATTERN = re.compile(r"\s*\([^()]*円\)\s*$")
_ACCOUNT_AMBIGUOUS_MESSAGE = (
    "口座 '{account_name}' に一致する MF 口座が複数見つかりました。"
    "config.yml の mf_account を見直してください。候補: {candidates}"
)
_ACCOUNT_AVAILABLE_MESSAGE = "利用可能な口座候補: {candidates}"
_MODAL_CLOSE_SKIPPED_DEBUG = "既存モーダルのクリーンアップをスキップしました: %s"


class MFManualFormPage:
    """Money Forward 手入力ページの DOM 契約をまとめる。"""

    def __init__(
        self,
        driver: WebDriver,
        logger: logging.Logger,
        mf_account: str,
        *,
        mf_categories_path: Path | None = None,
        category_map: dict[str, str] | None = None,
    ) -> None:
        self._driver = driver
        self._logger = logger
        self._mf_account = mf_account
        self._category_map = (
            load_mf_category_map(mf_categories_path)
            if category_map is None
            else dict(category_map)
        )

    def open(self) -> None:
        """入出金ページへ遷移し、手入力ボタンの表示を確認する。"""
        self._driver.get(mf_selectors.MANUAL_FORM_URL)
        self._wait(mf_selectors.NAVIGATION_TIMEOUT_MS).until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, mf_selectors.OPEN_MANUAL_FORM_BUTTON),
            )
        )

    def open_manual_form(self) -> WebElement:
        """手入力モーダルを開き、表示完了を待つ。"""
        self._close_existing_modal_if_present()
        open_button = self._wait(mf_selectors.NAVIGATION_TIMEOUT_MS).until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, mf_selectors.OPEN_MANUAL_FORM_BUTTON),
            )
        )
        self._click_element(open_button)
        return self._wait(mf_selectors.MODAL_TIMEOUT_MS).until(
            expected_conditions.visibility_of_element_located(
                (By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL),
            )
        )

    def register_transaction(self, tx: Transaction) -> None:
        """1件の取引を手入力フォームへ反映して保存する。"""
        modal = self.open_manual_form()

        payment_selector = (
            mf_selectors.PLUS_PAYMENT_INPUT
            if tx.direction == AppConstants.DIRECTION_IN
            else mf_selectors.MINUS_PAYMENT_INPUT
        )
        modal.find_element(By.CSS_SELECTOR, payment_selector).click()
        amount_input = self._wait_for_amount_input(modal)
        try:
            amount_input.clear()
            amount_input.send_keys(str(tx.amount))
        except ElementNotInteractableException as exc:
            raise RuntimeError(_AMOUNT_INPUT_NOT_READY_MESSAGE) from exc
        self._select_account(modal)

        if tx.category not in _SKIP_CATEGORY_VALUES:
            self._select_category(modal, tx.category)

        memo_input = modal.find_element(By.CSS_SELECTOR, mf_selectors.MEMO_INPUT)
        memo_input.clear()
        memo_input.send_keys(tx.memo)

        date_input = modal.find_element(By.CSS_SELECTOR, mf_selectors.DATE_INPUT)
        self._commit_date_input(
            date_input,
            tx.date.strftime(AppConstants.FORM_DATE_FORMAT),
        )
        self._click_element(
            modal.find_element(By.CSS_SELECTOR, mf_selectors.SUBMIT_BUTTON)
        )

        self._wait_for_submit_outcome()

    def _wait_for_submit_outcome(self) -> None:
        try:
            status, detail = self._wait(mf_selectors.SUBMIT_TIMEOUT_MS).until(
                self._resolve_submit_outcome,
            )
        except (TimeoutException, TimeoutError) as exc:
            raise RuntimeError(_SUBMIT_OUTCOME_TIMEOUT_MESSAGE) from exc

        if status == "error":
            msg = _SUBMIT_REPORTED_ERROR_MESSAGE.format(detail=detail)
            raise RuntimeError(msg)

    def _resolve_submit_outcome(
        self,
        _driver: WebDriver,
    ) -> tuple[str, str] | bool:
        modal = self._find_optional(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
        if modal is None or not modal.is_displayed():
            return ("closed", AppConstants.EMPTY_STRING)

        if self._is_submit_success_state(modal):
            self._close_submit_success_modal(modal)
            return False

        for selector in mf_selectors.SUBMIT_ERROR_FEEDBACK_SELECTORS:
            for element in modal.find_elements(By.CSS_SELECTOR, selector):
                if not element.is_displayed():
                    continue
                detail = element.text.strip() or _SUBMIT_ERROR_FALLBACK_DETAIL
                return ("error", detail)

        return False

    def _is_submit_success_state(self, modal: WebElement) -> bool:
        for element in modal.find_elements(
            By.CSS_SELECTOR,
            mf_selectors.SUBMIT_SUCCESS_MESSAGE,
        ):
            if not element.is_displayed():
                continue
            if element.text.strip() == _SUBMIT_SUCCESS_MESSAGE_TEXT:
                return True

        for element in modal.find_elements(
            By.CSS_SELECTOR,
            mf_selectors.SUBMIT_CONTINUE_BUTTON,
        ):
            if not element.is_displayed():
                continue
            return True

        return False

    def _close_submit_success_modal(self, modal: WebElement) -> None:
        close_button = self._find_first_visible_in_modal(
            modal,
            (
                *mf_selectors.MODAL_CLOSE_BUTTON_SELECTORS,
                mf_selectors.SUBMIT_CONTINUE_BUTTON,
            ),
        )
        if close_button is None:
            return
        self._click_element(close_button)

    def _select_account(self, modal: WebElement) -> None:
        account_select = Select(
            modal.find_element(By.CSS_SELECTOR, mf_selectors.ACCOUNT_SELECT)
        )
        normalized_target = self._normalize_account_name(self._mf_account)
        matched_options = []

        for option in account_select.options:
            option_text = option.text.strip()
            if self._normalize_account_name(option_text) != normalized_target:
                continue
            matched_options.append(option)

        if len(matched_options) > 1:
            msg = _ACCOUNT_AMBIGUOUS_MESSAGE.format(
                account_name=self._mf_account,
                candidates=", ".join(option.text.strip() for option in matched_options),
            )
            raise ValueError(msg)

        if len(matched_options) == 1:
            option_value = matched_options[0].get_attribute("value")
            if option_value is not None:
                account_select.select_by_value(option_value)
                return

        available_options = [option.text.strip() for option in account_select.options]
        msg = _ACCOUNT_NOT_FOUND_MESSAGE.format(account_name=self._mf_account)
        if available_options:
            candidates_text = ", ".join(available_options)
            msg = (
                f"{msg} {_ACCOUNT_AVAILABLE_MESSAGE.format(candidates=candidates_text)}"
            )
        raise ValueError(msg)

    def _normalize_account_name(self, account_name: str) -> str:
        normalized = account_name.strip()
        return _ACCOUNT_NAME_SUFFIX_PATTERN.sub(
            AppConstants.EMPTY_STRING,
            normalized,
        )

    def _select_category(self, modal: WebElement, category: str) -> None:
        large_name = self._category_map.get(category)
        if large_name is None:
            self._logger.warning(_CATEGORY_NOT_FOUND_WARNING, category)
            return

        modal.find_element(By.CSS_SELECTOR, mf_selectors.CATEGORY_DROPDOWN).click()
        large_option = self._wait(mf_selectors.MODAL_TIMEOUT_MS).until(
            lambda _driver: self._find_visible_text_match(
                By.CSS_SELECTOR,
                mf_selectors.LARGE_CATEGORY_LINK,
                large_name,
            )
        )
        ActionChains(self._driver).move_to_element(large_option).perform()
        middle_option = self._wait(mf_selectors.MODAL_TIMEOUT_MS).until(
            lambda _driver: self._find_visible_text_match(
                By.CSS_SELECTOR,
                mf_selectors.MIDDLE_CATEGORY_LINK,
                category,
            )
        )
        middle_option.click()

    def _wait(self, timeout_ms: int) -> WebDriverWait:
        return WebDriverWait(
            self._driver,
            timeout_ms / 1000,
            poll_frequency=0.2,
            ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
        )

    def _commit_date_input(
        self,
        date_input: WebElement,
        date_value: str,
    ) -> None:
        date_input.clear()
        date_input.send_keys(date_value)
        self._blur_element(date_input)

    def _blur_element(self, element: WebElement) -> None:
        execute_script = getattr(self._driver, "execute_script", None)
        if execute_script is not None:
            with suppress(
                JavascriptException,
                WebDriverException,
                StaleElementReferenceException,
            ):
                execute_script(
                    """
                    arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                    arguments[0].blur();
                    """,
                    element,
                )
                return

        element.send_keys(Keys.TAB)

    def _click_element(self, element: WebElement) -> None:
        execute_script = getattr(self._driver, "execute_script", None)
        if execute_script is not None:
            with suppress(
                JavascriptException,
                WebDriverException,
                StaleElementReferenceException,
            ):
                execute_script(
                    "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                    element,
                )

        try:
            element.click()
        except ElementClickInterceptedException:
            if execute_script is None:
                raise
            execute_script("arguments[0].click();", element)

    def _close_existing_modal_if_present(self) -> None:
        modal = self._find_optional(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
        if modal is None or not modal.is_displayed():
            return

        close_button = self._find_first_visible_in_modal(
            modal,
            mf_selectors.MODAL_CLOSE_BUTTON_SELECTORS,
        )
        if close_button is None:
            return

        try:
            self._click_element(close_button)
            self._wait(mf_selectors.MODAL_TIMEOUT_MS).until(
                lambda _driver: not self._is_modal_visible(),
            )
        except (
            ElementClickInterceptedException,
            NoSuchElementException,
            StaleElementReferenceException,
            TimeoutException,
            TimeoutError,
        ) as exc:
            self._logger.debug(_MODAL_CLOSE_SKIPPED_DEBUG, str(exc))
            return

    def _is_modal_visible(self) -> bool:
        modal = self._find_optional(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
        return modal is not None and modal.is_displayed()

    def _wait_for_amount_input(self, modal: WebElement) -> WebElement:
        try:
            return self._wait(mf_selectors.MODAL_TIMEOUT_MS).until(
                lambda _driver: self._find_interactable_amount_input(modal)
            )
        except (TimeoutException, TimeoutError) as exc:
            raise RuntimeError(_AMOUNT_INPUT_NOT_READY_MESSAGE) from exc

    def _find_interactable_amount_input(self, modal: WebElement) -> WebElement | bool:
        if not modal.is_displayed():
            return False

        for element in modal.find_elements(By.CSS_SELECTOR, mf_selectors.AMOUNT_INPUT):
            if not element.is_displayed() or not element.is_enabled():
                continue
            if not self._is_element_unobscured(element):
                continue
            return element
        return False

    def _is_element_unobscured(self, element: WebElement) -> bool:
        execute_script = getattr(self._driver, "execute_script", None)
        if execute_script is None:
            return True

        try:
            return bool(
                execute_script(
                    """
                    const target = arguments[0];
                    const rect = target.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) {
                        return false;
                    }
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const top = document.elementFromPoint(x, y);
                    return top === target || target.contains(top);
                    """,
                    element,
                )
            )
        except (
            JavascriptException,
            WebDriverException,
            StaleElementReferenceException,
        ):
            return True

    def _find_optional(self, by: str, value: str) -> WebElement | None:
        matches = self._driver.find_elements(by, value)
        if not matches:
            return None
        return matches[0]

    def _find_first_visible_in_modal(
        self,
        modal: WebElement,
        selectors: tuple[str, ...],
    ) -> WebElement | None:
        for selector in selectors:
            for element in modal.find_elements(By.CSS_SELECTOR, selector):
                if not element.is_displayed():
                    continue
                return element
        return None

    def _find_visible_text_match(
        self,
        by: str,
        selector: str,
        text: str,
    ) -> WebElement | bool:
        for element in self._driver.find_elements(by, selector):
            if not element.is_displayed():
                continue
            if element.text.strip() != text:
                continue
            return element
        return False
