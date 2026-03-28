"""Chrome プロセスの起動確認ユーティリティ。

psutil を使用して Chrome プロセスの存在を確認する。
"""

from __future__ import annotations

import psutil

# 比較対象のプロセス名
_CHROME_EXE = "chrome.exe"


def is_chrome_running() -> bool:
    """Chrome プロセスが起動中かどうかを確認する。

    psutil を使用して "chrome.exe" プロセスの存在を検索する。

    Returns:
        Chrome が起動中であれば True、そうでなければ False。
    """
    return any(
        p.info["name"] and p.info["name"].lower() == _CHROME_EXE
        for p in psutil.process_iter(["name"])
    )
