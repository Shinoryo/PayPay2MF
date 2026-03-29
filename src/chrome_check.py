"""Chrome プロセスの起動確認ユーティリティ。

psutil を使用して Chrome プロセスの存在を確認する。
"""

from __future__ import annotations

import psutil

from src.constants import AppConstants

# psutil の参照キーに使う定数。
_PROCESS_INFO_NAME = "name"


def is_chrome_running() -> bool:
    """Chrome プロセスが起動中かどうかを確認する。

    psutil を使用して "chrome.exe" プロセスの存在を検索する。

    Returns:
        Chrome が起動中であれば True、そうでなければ False。
    """
    return any(
        p.info[_PROCESS_INFO_NAME]
        and p.info[_PROCESS_INFO_NAME].lower() == AppConstants.CHROME_EXECUTABLE
        for p in psutil.process_iter([_PROCESS_INFO_NAME])
    )
