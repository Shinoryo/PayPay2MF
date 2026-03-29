"""Money Forward UI 自動化で使用するセレクタ定義。"""

from __future__ import annotations

MANUAL_FORM_URL = "https://moneyforward.com/cf"

OPEN_MANUAL_FORM_BUTTON = 'button.modal-switch[href="#user_asset_act_new"]'
MANUAL_FORM_MODAL = "#user_asset_act_new"

PLUS_PAYMENT_INPUT = "input.plus-payment"
MINUS_PAYMENT_INPUT = "input.minus-payment"
DATE_INPUT = "#updated-at"
AMOUNT_INPUT = "#appendedPrependedInput"
ACCOUNT_SELECT = "#user_asset_act_sub_account_id_hash"
MEMO_INPUT = "#js-content-field"
SUBMIT_BUTTON = "#submit-button"
CLOSE_BUTTON = "#cancel-button"

CATEGORY_DROPDOWN = ".btn_l_ctg .v_l_ctg"
LARGE_CATEGORY_LINK = "a.l_c_name"
MIDDLE_CATEGORY_LINK = "a.m_c_name"

NAVIGATION_TIMEOUT_MS = 30_000
MODAL_TIMEOUT_MS = 10_000
SUBMIT_TIMEOUT_MS = 15_000

ACCOUNT_OPTION_LOOKUP_SCRIPT = """(name) => {
    const sel = document.querySelector(
        '#user_asset_act_new #user_asset_act_sub_account_id_hash'
    );
    if (!sel) return null;
    for (const opt of sel.options) {
        if (opt.text.trim().startsWith(name)) return opt.value;
    }
    return null;
}"""


def large_category_option(name: str) -> str:
    """大項目リンクの selector を返す。"""
    return f"{LARGE_CATEGORY_LINK}:text-is('{name}')"


def middle_category_option(name: str) -> str:
    """中項目リンクの selector を返す。"""
    return f"{MIDDLE_CATEGORY_LINK}:text-is('{name}')"
