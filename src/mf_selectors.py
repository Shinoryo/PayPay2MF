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

SUBMIT_SUCCESS_FEEDBACK_SELECTORS = (
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

ACCOUNT_OPTION_LOOKUP_SCRIPT = """(name) => {
    const sel = document.querySelector(
        '#user_asset_act_new #user_asset_act_sub_account_id_hash'
    );
    if (!sel) return null;
    for (const opt of sel.options) {
        if (opt.text.trim() === name) return opt.value;
    }
    return null;
}"""

SUBMIT_OUTCOME_SCRIPT = """({ modalSelector, successSelectors, errorSelectors }) => {
    const isVisible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        return style.visibility !== 'hidden' && style.display !== 'none' && (
            element.offsetWidth > 0 ||
            element.offsetHeight > 0 ||
            element.getClientRects().length > 0
        );
    };

    const firstVisible = (selectors, root) => {
        for (const selector of selectors) {
            try {
                for (const element of root.querySelectorAll(selector)) {
                    if (isVisible(element)) {
                        return {
                            selector,
                            text: (element.textContent || '').trim(),
                        };
                    }
                }
            } catch (_error) {
                continue;
            }
        }
        return null;
    };

    const modal = document.querySelector(modalSelector);
    const errorMatch = modal ? firstVisible(errorSelectors, modal) : null;
    if (errorMatch) {
        return {
            status: 'error',
            selector: errorMatch.selector,
            text: errorMatch.text,
        };
    }

    const successMatch = firstVisible(successSelectors, document);
    if (successMatch) {
        return {
            status: 'success',
            selector: successMatch.selector,
            text: successMatch.text,
        };
    }

    if (!modal || !isVisible(modal)) {
        return { status: 'closed' };
    }

    return null;
}"""


def large_category_option(name: str) -> str:
    """大項目リンクの selector を返す。"""
    return f"{LARGE_CATEGORY_LINK}:text-is('{name}')"


def middle_category_option(name: str) -> str:
    """中項目リンクの selector を返す。"""
    return f"{MIDDLE_CATEGORY_LINK}:text-is('{name}')"
