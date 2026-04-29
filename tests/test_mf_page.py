"""mf_page モジュールのテスト。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
)
from selenium.webdriver.common.by import By

import paypay2mf.mf_page as mf_page_module
from paypay2mf import mf_selectors
from paypay2mf.constants import AppConstants
from paypay2mf.mf_page import MFManualFormPage
from paypay2mf.models import Transaction

_DEFAULT_OPTION_VALUE = "account-001"
_LEGACY_OPTION_VALUE = "account-legacy"
_DEFAULT_ACCOUNT_NAME = "PayPay残高"
_PREFIX_ACCOUNT_NAME = "PayPay残高 旧"
_DYNAMIC_BALANCE_ACCOUNT_NAME = "PayPay"
_DYNAMIC_BALANCE_OPTION_TEXT = "PayPay (439,670円)"
_SECOND_DYNAMIC_BALANCE_OPTION_TEXT = "PayPay (12,000円)"
_DEFAULT_CATEGORY = "食料品"
_DEFAULT_LARGE_CATEGORY = "食費"
_UNKNOWN_CATEGORY = "未知カテゴリ"
_DATE_INPUT_VALUE = "2025/01/01"
_AMOUNT_INPUT_VALUE = "920"
_DEFAULT_MEMO = "支払い"
_DEFAULT_MERCHANT = "モスのネット注文"
_DEFAULT_TRANSACTION_ID = "TX001"
_SUBMIT_TIMEOUT_MESSAGE = "submit timeout"
_SUBMIT_ERROR_MESSAGE = "入力エラーです"
_SUBMIT_SUCCESS_MESSAGE = "入力を保存しました。"

pytestmark = pytest.mark.ui_contract


class _FakeOption:
    def __init__(self, text: str, value: str) -> None:
        self.text = text
        self._value = value
        self._driver = None

    def bind_driver(self, driver: _FakeDriver) -> None:
        self._driver = driver

    def get_attribute(self, name: str) -> str | None:
        if name == "value":
            return self._value
        return None


class _FakeElement:
    def __init__(
        self,
        selector: str,
        *,
        text: str = AppConstants.EMPTY_STRING,
        displayed: bool = True,
        enabled: bool = True,
        interactable: bool = True,
        on_click=None,
        on_send_keys=None,
        options: list[_FakeOption] | None = None,
    ) -> None:
        self.selector = selector
        self.text = text
        self._displayed = displayed
        self._enabled = enabled
        self._interactable = interactable
        self._on_click = on_click
        self._on_send_keys = on_send_keys
        self._children: dict[tuple[str, str], list[_FakeElement]] = {}
        self.options = options or []
        self._driver = None

    def bind_driver(self, driver: _FakeDriver) -> None:
        self._driver = driver
        for child_list in self._children.values():
            for child in child_list:
                child.bind_driver(driver)
        for option in self.options:
            option.bind_driver(driver)

    def add_child(
        self,
        by: str,
        value: str,
        element: _FakeElement,
    ) -> _FakeElement:
        self._children.setdefault((by, value), []).append(element)
        if self._driver is not None:
            element.bind_driver(self._driver)
        return element

    def click(self) -> None:
        self._driver.actions.append(("click", self.selector))
        if self._on_click is not None:
            self._on_click()

    def clear(self) -> None:
        if not self._interactable:
            raise ElementNotInteractableException(f"not interactable: {self.selector}")
        self._driver.actions.append(("clear", self.selector))

    def send_keys(self, value: str) -> None:
        if not self._interactable:
            raise ElementNotInteractableException(f"not interactable: {self.selector}")
        self._driver.actions.append(("send_keys", self.selector, value))
        if self._on_send_keys is not None:
            self._on_send_keys(value)

    def find_element(self, by: str, value: str) -> _FakeElement:
        matches = self.find_elements(by, value)
        if not matches:
            raise NoSuchElementException(f"missing child: {by}={value}")
        return matches[0]

    def find_elements(self, by: str, value: str) -> list[_FakeElement]:
        return list(self._children.get((by, value), []))

    def is_displayed(self) -> bool:
        return self._displayed

    def is_enabled(self) -> bool:
        return self._enabled

    def set_displayed(self, displayed: bool) -> None:
        self._displayed = displayed

    def set_interactable(self, interactable: bool) -> None:
        self._interactable = interactable


class _FakeDriver:
    def __init__(self) -> None:
        self.actions: list[tuple] = []
        self.current_url = AppConstants.EMPTY_STRING
        self._registry: dict[tuple[str, str], list[_FakeElement]] = {}
        self.wait_failure: Exception | None = None
        self.on_wait_poll = None

    def register(
        self,
        by: str,
        value: str,
        element: _FakeElement,
    ) -> _FakeElement:
        self._registry.setdefault((by, value), []).append(element)
        element.bind_driver(self)
        return element

    def get(self, url: str) -> None:
        self.current_url = url
        self.actions.append(("get", url))

    def find_element(self, by: str, value: str) -> _FakeElement:
        matches = self.find_elements(by, value)
        if not matches:
            raise NoSuchElementException(f"missing element: {by}={value}")
        return matches[0]

    def find_elements(self, by: str, value: str) -> list[_FakeElement]:
        self.actions.append(("driver_find", by, value))
        return list(self._registry.get((by, value), []))

    def execute_script(self, _script: str, element: _FakeElement):
        if ".click();" in _script:
            element.click()
            return True
        return element._interactable


class _FakeWait:
    def __init__(
        self,
        driver: _FakeDriver,
        _timeout: float,
        *,
        poll_frequency: float,
        ignored_exceptions: tuple[type[Exception], ...],
    ) -> None:
        self._driver = driver
        self._ignored_exceptions = ignored_exceptions

    def until(self, condition):
        for _ in range(4):
            try:
                result = condition(self._driver)
            except self._ignored_exceptions:
                result = False
            if result:
                return result
            if self._driver.on_wait_poll is not None:
                self._driver.on_wait_poll()
        if self._driver.wait_failure is not None:
            raise self._driver.wait_failure
        raise TimeoutError(_SUBMIT_TIMEOUT_MESSAGE)


class _FakeSelect:
    def __init__(self, element: _FakeElement) -> None:
        self._element = element
        self.options = list(element.options)

    def select_by_value(self, value: str) -> None:
        self._element._driver.actions.append(("select_by_value", self._element.selector, value))


class _FakeActionChains:
    def __init__(self, driver: _FakeDriver) -> None:
        self._driver = driver

    def move_to_element(self, element: _FakeElement) -> _FakeActionChains:
        self._driver.actions.append(("move_to_element", element.selector))
        return self

    def perform(self) -> None:
        self._driver.actions.append(("perform_action_chain",))


@pytest.fixture(autouse=True)
def patch_selenium_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mf_page_module, "WebDriverWait", _FakeWait)
    monkeypatch.setattr(mf_page_module, "Select", _FakeSelect)
    monkeypatch.setattr(mf_page_module, "ActionChains", _FakeActionChains)


def _make_driver(*, account_options: list[tuple[str, str]] | None = None) -> _FakeDriver:
    driver = _FakeDriver()
    open_button = driver.register(
        By.CSS_SELECTOR,
        mf_selectors.OPEN_MANUAL_FORM_BUTTON,
        _FakeElement(mf_selectors.OPEN_MANUAL_FORM_BUTTON),
    )
    modal = driver.register(
        By.CSS_SELECTOR,
        mf_selectors.MANUAL_FORM_MODAL,
        _FakeElement(mf_selectors.MANUAL_FORM_MODAL, displayed=False),
    )
    open_button._on_click = lambda: modal.set_displayed(True)

    close_button = modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.CLOSE_BUTTON,
        _FakeElement(mf_selectors.CLOSE_BUTTON),
    )
    close_button._on_click = lambda: modal.set_displayed(False)

    modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.MINUS_PAYMENT_INPUT,
        _FakeElement(mf_selectors.MINUS_PAYMENT_INPUT),
    )
    modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.PLUS_PAYMENT_INPUT,
        _FakeElement(mf_selectors.PLUS_PAYMENT_INPUT),
    )
    modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.DATE_INPUT,
        _FakeElement(mf_selectors.DATE_INPUT),
    )
    modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.AMOUNT_INPUT,
        _FakeElement(mf_selectors.AMOUNT_INPUT),
    )
    modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.MEMO_INPUT,
        _FakeElement(mf_selectors.MEMO_INPUT),
    )
    modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.CATEGORY_DROPDOWN,
        _FakeElement(mf_selectors.CATEGORY_DROPDOWN),
    )
    options = [
        _FakeOption(text, value)
        for text, value in (account_options or [(_DEFAULT_ACCOUNT_NAME, _DEFAULT_OPTION_VALUE)])
    ]
    modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.ACCOUNT_SELECT,
        _FakeElement(mf_selectors.ACCOUNT_SELECT, options=options),
    )
    submit = modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.SUBMIT_BUTTON,
        _FakeElement(mf_selectors.SUBMIT_BUTTON),
    )
    submit._on_click = lambda: modal.set_displayed(False)

    driver.register(
        By.CSS_SELECTOR,
        mf_selectors.LARGE_CATEGORY_LINK,
        _FakeElement(mf_selectors.LARGE_CATEGORY_LINK, text=_DEFAULT_LARGE_CATEGORY),
    )
    driver.register(
        By.CSS_SELECTOR,
        mf_selectors.MIDDLE_CATEGORY_LINK,
        _FakeElement(mf_selectors.MIDDLE_CATEGORY_LINK, text=_DEFAULT_CATEGORY),
    )
    return driver


def _make_tx(*, category: str = _DEFAULT_CATEGORY) -> Transaction:
    return Transaction(
        date=datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
        amount=920,
        direction=AppConstants.DIRECTION_OUT,
        memo=_DEFAULT_MEMO,
        merchant=_DEFAULT_MERCHANT,
        transaction_id=_DEFAULT_TRANSACTION_ID,
        category=category,
    )


def test_open_navigates_to_moneyforward_page() -> None:
    driver = _make_driver()
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.open()

    assert ("get", mf_selectors.MANUAL_FORM_URL) in driver.actions


def test_register_transaction_uses_selector_contract() -> None:
    driver = _make_driver()
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert ("click", mf_selectors.OPEN_MANUAL_FORM_BUTTON) in driver.actions
    assert ("clear", mf_selectors.AMOUNT_INPUT) in driver.actions
    assert ("send_keys", mf_selectors.AMOUNT_INPUT, _AMOUNT_INPUT_VALUE) in driver.actions
    assert (
        "select_by_value",
        mf_selectors.ACCOUNT_SELECT,
        _DEFAULT_OPTION_VALUE,
    ) in driver.actions
    assert ("click", mf_selectors.CATEGORY_DROPDOWN) in driver.actions
    assert ("move_to_element", mf_selectors.LARGE_CATEGORY_LINK) in driver.actions
    assert ("click", mf_selectors.MIDDLE_CATEGORY_LINK) in driver.actions
    assert ("clear", mf_selectors.MEMO_INPUT) in driver.actions
    assert ("send_keys", mf_selectors.MEMO_INPUT, _DEFAULT_MEMO) in driver.actions
    assert ("clear", mf_selectors.DATE_INPUT) in driver.actions
    assert ("send_keys", mf_selectors.DATE_INPUT, _DATE_INPUT_VALUE) in driver.actions
    assert ("click", mf_selectors.SUBMIT_BUTTON) in driver.actions

    amount_clear_index = driver.actions.index(("clear", mf_selectors.AMOUNT_INPUT))
    memo_send_index = driver.actions.index(("send_keys", mf_selectors.MEMO_INPUT, _DEFAULT_MEMO))
    date_clear_index = driver.actions.index(("clear", mf_selectors.DATE_INPUT))
    submit_click_index = driver.actions.index(("click", mf_selectors.SUBMIT_BUTTON))
    assert amount_clear_index < date_clear_index
    assert memo_send_index < date_clear_index
    assert date_clear_index < submit_click_index


def test_register_transaction_waits_until_amount_input_becomes_interactable() -> None:
    driver = _make_driver()
    modal = driver.find_element(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
    amount_input = modal.find_element(By.CSS_SELECTOR, mf_selectors.AMOUNT_INPUT)
    amount_input.set_interactable(False)
    driver.on_wait_poll = lambda: amount_input.set_interactable(True)
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert ("clear", mf_selectors.AMOUNT_INPUT) in driver.actions
    assert ("send_keys", mf_selectors.AMOUNT_INPUT, _AMOUNT_INPUT_VALUE) in driver.actions


def test_open_manual_form_closes_existing_modal_before_reopening() -> None:
    driver = _make_driver()
    modal = driver.find_element(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
    modal.set_displayed(True)
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    returned_modal = form_page.open_manual_form()

    assert returned_modal is modal
    assert ("click", mf_selectors.CLOSE_BUTTON) in driver.actions
    assert ("click", mf_selectors.OPEN_MANUAL_FORM_BUTTON) in driver.actions


def test_register_transaction_commits_date_after_other_fields() -> None:
    driver = _make_driver()
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert ("send_keys", mf_selectors.DATE_INPUT, _DATE_INPUT_VALUE) in driver.actions
    assert ("send_keys", mf_selectors.DATE_INPUT, mf_page_module.Keys.ESCAPE) not in driver.actions
    amount_send_index = driver.actions.index(("send_keys", mf_selectors.AMOUNT_INPUT, _AMOUNT_INPUT_VALUE))
    date_send_index = driver.actions.index(("send_keys", mf_selectors.DATE_INPUT, _DATE_INPUT_VALUE))
    submit_click_index = driver.actions.index(("click", mf_selectors.SUBMIT_BUTTON))
    assert amount_send_index < date_send_index
    assert date_send_index < submit_click_index


def test_register_transaction_raises_when_amount_input_never_becomes_interactable() -> None:
    driver = _make_driver()
    modal = driver.find_element(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
    amount_input = modal.find_element(By.CSS_SELECTOR, mf_selectors.AMOUNT_INPUT)
    amount_input.set_interactable(False)
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(RuntimeError, match="金額入力欄"):
        form_page.register_transaction(_make_tx())


def test_register_transaction_raises_when_submit_does_not_close_modal() -> None:
    driver = _make_driver()
    driver.wait_failure = TimeoutError(_SUBMIT_TIMEOUT_MESSAGE)
    modal = driver.find_element(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
    submit = modal.find_element(By.CSS_SELECTOR, mf_selectors.SUBMIT_BUTTON)
    submit._on_click = lambda: None
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(RuntimeError, match="MF 登録結果を確認できませんでした"):
        form_page.register_transaction(_make_tx())


def test_register_transaction_accepts_success_confirmation_modal() -> None:
    driver = _make_driver()
    modal = driver.find_element(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
    success_message = modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.SUBMIT_SUCCESS_MESSAGE,
        _FakeElement(
            mf_selectors.SUBMIT_SUCCESS_MESSAGE,
            text=_SUBMIT_SUCCESS_MESSAGE,
            displayed=False,
        ),
    )
    continue_button = modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.SUBMIT_CONTINUE_BUTTON,
        _FakeElement(mf_selectors.SUBMIT_CONTINUE_BUTTON, displayed=False),
    )
    close_button = modal.find_element(By.CSS_SELECTOR, mf_selectors.CLOSE_BUTTON)
    close_button.set_displayed(False)

    def _show_success_confirmation() -> None:
        success_message.set_displayed(True)
        continue_button.set_displayed(True)
        close_button.set_displayed(True)

    submit = modal.find_element(By.CSS_SELECTOR, mf_selectors.SUBMIT_BUTTON)
    submit._on_click = _show_success_confirmation
    close_button._on_click = lambda: modal.set_displayed(False)

    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert ("click", mf_selectors.CLOSE_BUTTON) in driver.actions


def test_register_transaction_raises_when_submit_error_is_reported() -> None:
    driver = _make_driver()
    modal = driver.find_element(By.CSS_SELECTOR, mf_selectors.MANUAL_FORM_MODAL)
    error_element = modal.add_child(
        By.CSS_SELECTOR,
        mf_selectors.SUBMIT_ERROR_FEEDBACK_SELECTORS[0],
        _FakeElement(mf_selectors.SUBMIT_ERROR_FEEDBACK_SELECTORS[0], text=_SUBMIT_ERROR_MESSAGE, displayed=False),
    )
    submit = modal.find_element(By.CSS_SELECTOR, mf_selectors.SUBMIT_BUTTON)
    submit._on_click = lambda: error_element.set_displayed(True)
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(RuntimeError, match=_SUBMIT_ERROR_MESSAGE):
        form_page.register_transaction(_make_tx())


def test_register_transaction_accepts_closed_modal_without_success_feedback() -> None:
    driver = _make_driver()
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert ("click", mf_selectors.SUBMIT_BUTTON) in driver.actions


def test_register_transaction_selects_exact_account_match_when_prefix_exists() -> None:
    driver = _make_driver(
        account_options=[
            (_PREFIX_ACCOUNT_NAME, _LEGACY_OPTION_VALUE),
            (f"  {_DEFAULT_ACCOUNT_NAME}  ", _DEFAULT_OPTION_VALUE),
        ]
    )
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert (
        "select_by_value",
        mf_selectors.ACCOUNT_SELECT,
        _DEFAULT_OPTION_VALUE,
    ) in driver.actions
    assert (
        "select_by_value",
        mf_selectors.ACCOUNT_SELECT,
        _LEGACY_OPTION_VALUE,
    ) not in driver.actions


def test_register_transaction_selects_account_with_balance_suffix() -> None:
    driver = _make_driver(
        account_options=[(_DYNAMIC_BALANCE_OPTION_TEXT, _DEFAULT_OPTION_VALUE)]
    )
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DYNAMIC_BALANCE_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert (
        "select_by_value",
        mf_selectors.ACCOUNT_SELECT,
        _DEFAULT_OPTION_VALUE,
    ) in driver.actions


def test_register_transaction_raises_when_multiple_accounts_match_after_normalization() -> None:
    driver = _make_driver(
        account_options=[
            (_DYNAMIC_BALANCE_OPTION_TEXT, _DEFAULT_OPTION_VALUE),
            (_SECOND_DYNAMIC_BALANCE_OPTION_TEXT, _LEGACY_OPTION_VALUE),
        ]
    )
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DYNAMIC_BALANCE_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(ValueError, match="複数見つかりました"):
        form_page.register_transaction(_make_tx())


def test_register_transaction_raises_when_exact_account_match_is_missing() -> None:
    driver = _make_driver(account_options=[(_PREFIX_ACCOUNT_NAME, _LEGACY_OPTION_VALUE)])
    form_page = MFManualFormPage(
        driver,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(ValueError, match=_DEFAULT_ACCOUNT_NAME):
        form_page.register_transaction(_make_tx())

    with pytest.raises(ValueError, match=_PREFIX_ACCOUNT_NAME):
        form_page.register_transaction(_make_tx())

    select_calls = [action for action in driver.actions if action[0] == "select_by_value"]
    assert select_calls == []


def test_register_transaction_warns_for_unknown_category() -> None:
    logger = Mock()
    driver = _make_driver()
    form_page = MFManualFormPage(
        driver,
        logger,
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx(category=_UNKNOWN_CATEGORY))

    logger.warning.assert_called_once()
