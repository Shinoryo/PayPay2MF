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

from paypay2mf import mf_selectors
from paypay2mf.constants import AppConstants
from paypay2mf.mf_page import MFManualFormPage
from paypay2mf.models import Transaction

_DEFAULT_OPTION_VALUE = "account-001"
_LEGACY_OPTION_VALUE = "account-legacy"
_DEFAULT_ACCOUNT_NAME = "PayPay残高"
_PREFIX_ACCOUNT_NAME = "PayPay残高 旧"
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
_UNEXPECTED_ACCOUNT_LOOKUP_SCRIPT = "Unexpected account lookup script"

pytestmark = pytest.mark.ui_contract


class _FakeJSHandle:
    def __init__(self, value: dict[str, str]) -> None:
        self._value = value

    def json_value(self) -> dict[str, str]:
        return dict(self._value)


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
        account_options: list[tuple[str, str]] | None = None,
        wait_failures: dict[tuple[str, str], Exception] | None = None,
        submit_outcome: dict[str, str] | None = None,
        wait_for_function_failure: Exception | None = None,
    ) -> None:
        self.actions: list[tuple] = []
        self._option_value = option_value
        self._account_options = account_options
        self._wait_failures = wait_failures or {}
        self._submit_outcome = submit_outcome or {"status": "closed"}
        self._wait_for_function_failure = wait_for_function_failure

    def click(self, selector: str) -> None:
        self.actions.append(("page_click", selector))

    def evaluate(self, script: str, account_name: str) -> str | None:
        self.actions.append(("evaluate", script, account_name))
        if self._account_options is None:
            return self._option_value

        for option_name, option_value in self._account_options:
            normalized_name = option_name.strip()
            if "startsWith(name)" in script and normalized_name.startswith(
                account_name
            ):
                return option_value
            if "=== name" in script and normalized_name == account_name:
                return option_value

        if "startsWith(name)" not in script and "=== name" not in script:
            raise AssertionError(_UNEXPECTED_ACCOUNT_LOOKUP_SCRIPT)

        return None

    def goto(self, url: str) -> None:
        self.actions.append(("goto", url))

    def locator(self, selector: str) -> _FakeLocator:
        self.actions.append(("page_locator", selector))
        return _FakeLocator(
            selector,
            self.actions,
            wait_failures=self._wait_failures,
        )

    def wait_for_function(
        self,
        script: str,
        arg: dict[str, object],
        *,
        timeout: int,
    ) -> _FakeJSHandle:
        self.actions.append(("wait_for_function", script, arg, timeout))
        if self._wait_for_function_failure is not None:
            raise self._wait_for_function_failure
        return _FakeJSHandle(self._submit_outcome)

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
    page = _FakePage(submit_outcome={"status": "success"})
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
    wait_for_function_calls = [
        action for action in page.actions if action[0] == "wait_for_function"
    ]
    assert len(wait_for_function_calls) == 1
    _, _, wait_arg, wait_timeout = wait_for_function_calls[0]
    assert wait_arg == {
        "modalSelector": mf_selectors.MANUAL_FORM_MODAL,
        "successSelectors": list(mf_selectors.SUBMIT_SUCCESS_FEEDBACK_SELECTORS),
        "errorSelectors": list(mf_selectors.SUBMIT_ERROR_FEEDBACK_SELECTORS),
    }
    assert wait_timeout == mf_selectors.SUBMIT_TIMEOUT_MS
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
        wait_for_function_failure=TimeoutError(_SUBMIT_TIMEOUT_MESSAGE),
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
    wait_for_function_calls = [
        action for action in page.actions if action[0] == "wait_for_function"
    ]
    assert len(wait_for_function_calls) == 1


def test_register_transaction_raises_when_submit_error_is_reported() -> None:
    """submit 後にフォームエラー要素が出た場合は明示的な RuntimeError を送出する。"""
    page = _FakePage(
        submit_outcome={
            "status": "error",
            "selector": ".alert-danger",
            "text": _SUBMIT_ERROR_MESSAGE,
        }
    )
    form_page = MFManualFormPage(
        page,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(RuntimeError, match=_SUBMIT_ERROR_MESSAGE):
        form_page.register_transaction(_make_tx())

    hidden_wait_calls = [
        action
        for action in page.actions
        if action[0] == "wait_for" and action[1] == mf_selectors.MANUAL_FORM_MODAL
    ]
    assert hidden_wait_calls == [
        (
            "wait_for",
            mf_selectors.MANUAL_FORM_MODAL,
            {
                "state": AppConstants.LOCATOR_STATE_VISIBLE,
                "timeout": mf_selectors.MODAL_TIMEOUT_MS,
            },
        )
    ]


def test_register_transaction_accepts_closed_modal_without_success_feedback() -> None:
    """成功通知が取れなくても、モーダル閉鎖を検知できれば成功として扱う。"""
    page = _FakePage(submit_outcome={"status": "closed"})
    form_page = MFManualFormPage(
        page,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    hidden_wait_calls = [
        action
        for action in page.actions
        if action[0] == "wait_for"
        and action[1] == mf_selectors.MANUAL_FORM_MODAL
        and action[2].get("state") == AppConstants.LOCATOR_STATE_HIDDEN
    ]
    assert hidden_wait_calls == []


def test_register_transaction_selects_exact_account_match_when_prefix_exists() -> None:
    """mf_account は前方一致ではなく完全一致で選択する。"""
    page = _FakePage(
        account_options=[
            (_PREFIX_ACCOUNT_NAME, _LEGACY_OPTION_VALUE),
            (f"  {_DEFAULT_ACCOUNT_NAME}  ", _DEFAULT_OPTION_VALUE),
        ],
        submit_outcome={"status": "closed"},
    )
    form_page = MFManualFormPage(
        page,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx())

    assert (
        "select_option",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.ACCOUNT_SELECT}",
        {"value": _DEFAULT_OPTION_VALUE},
    ) in page.actions
    assert (
        "select_option",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.ACCOUNT_SELECT}",
        {"value": _LEGACY_OPTION_VALUE},
    ) not in page.actions


def test_register_transaction_raises_when_exact_account_match_is_missing() -> None:
    """完全一致の口座候補がなければ即失敗する。"""
    page = _FakePage(
        account_options=[(_PREFIX_ACCOUNT_NAME, _LEGACY_OPTION_VALUE)],
    )
    form_page = MFManualFormPage(
        page,
        Mock(),
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    with pytest.raises(ValueError, match=_DEFAULT_ACCOUNT_NAME):
        form_page.register_transaction(_make_tx())

    select_option_calls = [
        action for action in page.actions if action[0] == "select_option"
    ]
    assert select_option_calls == []


def test_register_transaction_warns_for_unknown_category() -> None:
    """TC-08-01: 未対応カテゴリでは warning を出し、カテゴリ操作をスキップすることを確認する。"""
    logger = Mock()
    page = _FakePage(submit_outcome={"status": "closed"})
    form_page = MFManualFormPage(
        page,
        logger,
        _DEFAULT_ACCOUNT_NAME,
        category_map={_DEFAULT_CATEGORY: _DEFAULT_LARGE_CATEGORY},
    )

    form_page.register_transaction(_make_tx(category=_UNKNOWN_CATEGORY))

    logger.warning.assert_called_once()
