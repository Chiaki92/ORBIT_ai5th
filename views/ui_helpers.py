"""Streamlit 用の共通 UI ヘルパー。"""

from contextlib import contextmanager

import streamlit as st

# 白行と色付き行の2色ゼブラ（行全体 = st.container(key=...) に st-key-<key> が付く）
_ZEBRA_TINT = "rgba(46, 134, 193, 0.1)"
_ZEBRA_WHITE = "#ffffff"


@contextmanager
def zebra_row_container(stripe_index: int, row_css_key: str):
    """
    直後の st.container(key=row_css_key) ブロックに薄い行背景を付ける。

    Streamlit 1.30+ で container に key を付けると DOM に class ``st-key-<key>`` が付与される。
    グローバル CSS の隣接セレクタが効かない環境向けに、行ごとに st.html で <style> を注入する。
    row_css_key は英数字とアンダースコアのみ（CSS クラス用）。
    """
    bg = _ZEBRA_TINT if stripe_index % 2 == 0 else _ZEBRA_WHITE
    # style のみだと event コンテナに送られ DOM に載らない場合があるためダミー要素を付ける
    st.html(
        f"<style>.st-key-{row_css_key} {{ background: {bg} !important; border-radius: 0; "
        f"padding: 8px 12px !important; margin-bottom: 6px !important; box-sizing: border-box; }}</style>"
        '<span aria-hidden="true" style="display:none">.</span>',
        width="content",
    )
    with st.container(key=row_css_key):
        yield


def inject_colored_cell_style(
    cell_key: str,
    bg: str,
    *,
    left_border: str | None = None,
) -> None:
    """
    直後の st.container(key=cell_key) に背景色（と任意の左ボーダー）を付ける。
    算定表の「課金コード」「使用量」など列ごとの色分け用。
    """
    left = f"border-left: {left_border} !important;" if left_border else ""
    st.html(
        f"<style>.st-key-{cell_key} {{ background: {bg} !important; padding: 6px 8px !important; "
        f"border-radius: 4px; border: 1px solid #d0d0d0; {left} }}</style>"
        '<span aria-hidden="true" style="display:none">.</span>',
        width="content",
    )
