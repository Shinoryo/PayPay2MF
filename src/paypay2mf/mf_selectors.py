"""Money Forward UI 自動化で使用するセレクタ定義。"""

from __future__ import annotations

SIGN_IN_PAGE_URL = "https://moneyforward.com/sign_in"
MANUAL_FORM_URL = "https://moneyforward.com/cf"

HOUSEHOLD_BOOK_TAB_CSS = 'a[href="/cf"], a[href="https://moneyforward.com/cf"]'
HOUSEHOLD_BOOK_TAB_XPATH = (
    "//a[contains(@href, '/cf')][contains(normalize-space(.), '家計簿')]"
)

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
SUBMIT_SUCCESS_MESSAGE = "#alert-area"
SUBMIT_CONTINUE_BUTTON = "#confirmation-button"
MODAL_CLOSE_BUTTON_SELECTORS = (
    CLOSE_BUTTON,
    ".modal-header .close",
    "button.close",
)

SUBMIT_SUCCESS_FEEDBACK_SELECTORS = (
    SUBMIT_SUCCESS_MESSAGE,
    ".flash_notice",
    ".alert-success",
    ".toast-success",
)
SUBMIT_ERROR_FEEDBACK_SELECTORS = (
    ".flash_alert",
    ".alert-danger",
    ".alert-error",
    ".errorExplanation",
    ".error-message",
    ".mf-input-error",
    ".formError",
)

CATEGORY_DROPDOWN = ".btn_l_ctg .v_l_ctg"
LARGE_CATEGORY_LINK = "a.l_c_name"
MIDDLE_CATEGORY_LINK = "a.m_c_name"

NAVIGATION_TIMEOUT_MS = 30_000
MODAL_TIMEOUT_MS = 10_000
SUBMIT_TIMEOUT_MS = 15_000
