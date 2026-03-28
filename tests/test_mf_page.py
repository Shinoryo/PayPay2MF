"""mf_page モジュールのテスト。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

from src import mf_selectors
from src.mf_page import MFManualFormPage
from src.models import Transaction


class _FakeLocator:
    def __init__(self, selector: str, actions: list[tuple]) -> None:
        self._selector = selector
        self._actions = actions
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
        return _FakeLocator(f"{self._selector} >> {selector}", self._actions)

    def select_option(self, **kwargs: str) -> None:
        self._actions.append(("select_option", self._selector, kwargs))

    def wait_for(self, **kwargs: str | int) -> None:
        self._actions.append(("wait_for", self._selector, kwargs))


class _FakePage:
    def __init__(self, *, option_value: str | None = "account-001") -> None:
        self.actions: list[tuple] = []
        self._option_value = option_value

    def click(self, selector: str) -> None:
        self.actions.append(("page_click", selector))

    def evaluate(self, script: str, account_name: str) -> str | None:
        self.actions.append(("evaluate", script, account_name))
        return self._option_value

    def goto(self, url: str) -> None:
        self.actions.append(("goto", url))

    def locator(self, selector: str) -> _FakeLocator:
        self.actions.append(("page_locator", selector))
        return _FakeLocator(selector, self.actions)

    def wait_for_selector(self, selector: str, timeout: int) -> None:
        self.actions.append(("wait_for_selector", selector, timeout))


def _make_tx(*, category: str = "食料品") -> Transaction:
    return Transaction(
        date=datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
        amount=920,
        direction="out",
        memo="支払い",
        merchant="モスのネット注文",
        transaction_id="TX001",
        category=category,
    )


def test_open_navigates_to_moneyforward_page() -> None:
    """open が Money Forward 入出金ページへ遷移し、手入力ボタンを待つことを確認する。"""
    page = _FakePage()
    form_page = MFManualFormPage(
        page,
        Mock(),
        "PayPay残高",
        category_map={"食料品": "食費"},
    )

    form_page.open()

    assert ("goto", mf_selectors.MANUAL_FORM_URL) in page.actions
    assert (
        "wait_for_selector",
        mf_selectors.OPEN_MANUAL_FORM_BUTTON,
        mf_selectors.NAVIGATION_TIMEOUT_MS,
    ) in page.actions


def test_register_transaction_uses_selector_contract() -> None:
    """register_transaction がセレクタ定義経由でフォーム入力を進めることを確認する。"""
    page = _FakePage()
    form_page = MFManualFormPage(
        page,
        Mock(),
        "PayPay残高",
        category_map={"食料品": "食費"},
    )

    form_page.register_transaction(_make_tx())

    assert ("page_click", mf_selectors.OPEN_MANUAL_FORM_BUTTON) in page.actions
    assert ("page_locator", mf_selectors.MANUAL_FORM_MODAL) in page.actions
    assert (
        "fill",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.DATE_INPUT}",
        "2025/01/01",
    ) in page.actions
    assert (
        "fill",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.AMOUNT_INPUT}",
        "920",
    ) in page.actions
    assert (
        "select_option",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.ACCOUNT_SELECT}",
        {"value": "account-001"},
    ) in page.actions
    assert (
        "locator_click",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.CATEGORY_DROPDOWN}",
    ) in page.actions
    assert (
        "locator_click",
        f"{mf_selectors.MANUAL_FORM_MODAL} >> {mf_selectors.SUBMIT_BUTTON}",
    ) in page.actions


def test_register_transaction_warns_for_unknown_category() -> None:
    """未対応カテゴリでは warning を出し、カテゴリ操作をスキップすることを確認する。"""
    logger = Mock()
    page = _FakePage()
    form_page = MFManualFormPage(
        page,
        logger,
        "PayPay残高",
        category_map={"食料品": "食費"},
    )

    form_page.register_transaction(_make_tx(category="未知カテゴリ"))

    logger.warning.assert_called_once()
