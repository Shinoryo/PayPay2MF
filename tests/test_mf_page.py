"""mf_page モジュールのテスト。

対応テストレイヤー:
    ui_contract: Fake Page を使った UI 操作契約の検証

対応テストケース:
    TC-07-00: 手入力モーダル起動確認の前提契約
    TC-07-01: 取引登録操作のフォーム契約
    TC-08-01: 未対応カテゴリ時の warning 契約
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from src import mf_selectors
from src.constants import AppConstants
from src.mf_page import MFManualFormPage
from src.models import Transaction

_DEFAULT_OPTION_VALUE = "account-001"
_DEFAULT_ACCOUNT_NAME = "PayPay残高"
_DEFAULT_CATEGORY = "食料品"
_DEFAULT_LARGE_CATEGORY = "食費"
_UNKNOWN_CATEGORY = "未知カテゴリ"
_DATE_INPUT_VALUE = "2025/01/01"
_AMOUNT_INPUT_VALUE = "920"
_DEFAULT_MEMO = "支払い"
_DEFAULT_MERCHANT = "モスのネット注文"
_DEFAULT_TRANSACTION_ID = "TX001"
_SUBMIT_TIMEOUT_MESSAGE = "submit timeout"

pytestmark = pytest.mark.ui_contract


class _FakeLocator:
    def __init__(
        self,
        selector: str,
        actions: list[tuple],
        *,
        wait_failures: dict[tuple[str, str], Exception] | None = None,
    ) -> None:
        self._selector = selector
        self._actions = actions
        self._wait_failures = wait_failures or {}
        self.first = self

    def click(self) -> None:
        self._actions.append(("locator_click", self._selector))

    def fill(self, value: str) -> None:
        self._actions.append(("fill", self._selector, value))

    def press(self, key: str) -> None:
        self._actions.append(("press", self._selector, key))

    def hover(self) -> None:
        self._actions.append(("hover", self._selector))

    def locator(self, selector: str) -> _FakeLocator:
        self._actions.append(("locator", self._selector, selector))
        return _FakeLocator(
            f"{self._selector} >> {selector}",
            self._actions,
            wait_failures=self._wait_failures,
        )

    def select_option(self, **kwargs: str) -> None:
        self._actions.append(("select_option", self._selector, kwargs))

    def wait_for(self, **kwargs: str | int) -> None:
        self._actions.append(("wait_for", self._selector, kwargs))
        state = kwargs.get("state")
        failure = self._wait_failures.get((self._selector, str(state)))
        if failure is not None:
            raise failure


class _FakePage:
    def __init__(
        self,
        *,
        option_value: str | None = _DEFAULT_OPTION_VALUE,
        wait_failures: dict[tuple[str, str], Exception] | None = None,
    ) -> None:
        self.actions: list[tuple] = []
        self._option_value = option_value
        self._wait_failures = wait_failures or {}

    def click(self, selector: str) -> None:
        self.actions.append(("page_click", selector))

    def evaluate(self, script: str, account_name: str) -> str | None:
        self.actions.append(("evaluate", script, account_name))
        return self._option_value

    def goto(self, url: str) -> None:
        self.actions.append(("goto", url))

    def locator(self, selector: str) -> _FakeLocator:
        self.actions.append(("page_locator", selector))
        return _FakeLocator(
            selector,
            self.actions,
            wait_failures=self._wait_failures,
        )

    def wait_for_selector(self, selector: str, timeout: int) -> None:
        self.actions.append(("wait_for_selector", selector, timeout))


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
    """TC-07-00: open が Money Forward 入出金ページへ遷移し、手入力ボタンを待つことを確認する。"""
    page = _FakePage()
    form_page = MFManualFormPage(
        page,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.open()

    assert ("goto", mf_selectors.MANUAL_FORM_URL) in page.actions
    assert (
        "wait_for_selector",
        mf_selectors.OPEN_MANUAL_FORM_BUTTON,
        mf_selectors.NAVIGATION_TIMEOUT_MS,
    ) in page.actions


def test_register_transaction_uses_selector_contract() -> None:
    """TC-07-01: register_transaction がセレクタ定義経由でフォーム入力を進めることを確認する。"""
    page = _FakePage()
    form_page = MFManualFormPage(
        page,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert ("page_click", mf_selectors.OPEN_MANUAL_FORM_BUTTON) in page.actions
    assert ("page_locator", mf_selectors.MANUAL_FORM_MODAL) in page.actions
    assert (
        "fill",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.DATE_INPUT}",
        _DATE_INPUT_VALUE,
    ) in page.actions
    assert (
        "fill",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.AMOUNT_INPUT}",
        _AMOUNT_INPUT_VALUE,
    ) in page.actions
    assert (
        "select_option",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.ACCOUNT_SELECT}",
        {"value": _DEFAULT_OPTION_VALUE},
    ) in page.actions
    assert (
        "locator_click",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.CATEGORY_DROPDOWN}",
    ) in page.actions
    assert (
        "locator_click",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.SUBMIT_BUTTON}",
    ) in page.actions
    assert (
        "wait_for",
        mf_selectors.MANUAL_FORM_MODAL,
        {
            "state": AppConstants.LOCATOR_STATE_HIDDEN,
            "timeout": mf_selectors.SUBMIT_TIMEOUT_MS,
        },
    ) in page.actions
    assert (
        "page_locator",
        mf_selectors.CLOSE_BUTTON,
    ) not in page.actions


def test_register_transaction_raises_when_submit_does_not_close_modal() -> None:
    """TC-08-01: submit 後にモーダルが閉じなければ例外を送出することを確認する。"""
    page = _FakePage(
        wait_failures={
            (
                mf_selectors.MANUAL_FORM_MODAL,
                AppConstants.LOCATOR_STATE_HIDDEN,
            ): TimeoutError(_SUBMIT_TIMEOUT_MESSAGE),
        },
    )
    form_page = MFManualFormPage(
        page,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(TimeoutError, match=_SUBMIT_TIMEOUT_MESSAGE):
        form_page.register_transaction(_make_tx())

    assert (
        "locator_click",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.SUBMIT_BUTTON}",
    ) in page.actions
    assert (
        "wait_for",
        mf_selectors.MANUAL_FORM_MODAL,
        {
            "state": AppConstants.LOCATOR_STATE_HIDDEN,
            "timeout": mf_selectors.SUBMIT_TIMEOUT_MS,
        },
    ) in page.actions


def test_register_transaction_warns_for_unknown_category() -> None:
    """TC-08-01: 未対応カテゴリでは warning を出し、カテゴリ操作をスキップすることを確認する。"""
    logger = Mock()
    page = _FakePage()
    form_page = MFManualFormPage(
        page,
        logger,
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx(category=_UNKNOWN_CATEGORY))

    logger.warning.assert_called_once()
