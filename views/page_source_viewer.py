"""
page_source_viewer.py — 元データ確認ページ

算定明細の各項目から📄ボタンで新タブに開かれるページ。
元のPDF/CSVファイルを表示し、該当箇所をハイライトする。

フェーズ1: ファイル全体を表示（ハイライトなし）
フェーズ2: ページジャンプ・行ハイライト・bboxハイライト対応
"""

import base64
import json
import logging

import pandas as pd
import streamlit as st

from fabric_connection import download_file_from_onelake

logger = logging.getLogger(__name__)


def render_source_viewer():
    """
    クエリパラメータからソース情報を読み取り、元データを表示する。

    クエリパラメータ:
      page: "source_viewer" （ルーティング用）
      item: 項目名（表示用）
      sources: base64エンコードされたJSON（ソースリスト）
    """
    params = st.query_params
    item_name = params.get("item", "（不明）")
    sources_b64 = params.get("sources", "")

    st.title("元データ確認")
    st.markdown(f"**項目:** {item_name}")

    # ソース情報をデコード
    if not sources_b64:
        st.warning("ソース情報が指定されていません。")
        return

    try:
        sources = json.loads(base64.urlsafe_b64decode(sources_b64).decode("utf-8"))
    except Exception as e:
        st.error(f"ソース情報の読み取りに失敗しました: {e}")
        return

    if not sources:
        st.warning("表示するソースがありません。")
        return

    # 複数ソースの場合はタブで切替
    if len(sources) > 1:
        tab_labels = [s.get("label", f"ソース{i+1}") for i, s in enumerate(sources)]
        tabs = st.tabs(tab_labels)
        for tab, source in zip(tabs, sources):
            with tab:
                _render_single_source(source)
    else:
        _render_single_source(sources[0])


def _render_single_source(source: dict):
    """
    1つのソースファイルを表示する。

    source dict:
      - label: ソース名
      - file: ファイル名
      - subfolder: サブフォルダ名
      - page: ページ番号（PDFの場合、フェーズ2）
      - row_num: 行番号（CSVの場合、フェーズ2）
      - bbox: {x, y, w, h}（PDF座標、フェーズ2）
    """
    file_name = source.get("file", "")
    subfolder = source.get("subfolder", "")

    if not file_name:
        st.warning("ファイル名が指定されていません。")
        return

    st.markdown(f"**ファイル:** `{file_name}`")

    # ファイルタイプの判定
    is_pdf = file_name.lower().endswith(".pdf") or subfolder in ("yakuzai", "masui_kensa")
    is_csv = file_name.lower().endswith(".csv") or subfolder in ("orsys", "karte_kiji")

    # ページ番号・行番号の表示（フェーズ2で有効化される）
    page_num = source.get("page")
    row_num = source.get("row_num")
    if page_num:
        st.markdown(f"**ページ:** {page_num}")
    if row_num:
        st.markdown(f"**行番号:** {row_num}")

    st.divider()

    # OneLakeからファイルをダウンロード
    with st.spinner("ファイルを読み込んでいます..."):
        file_bytes = _download_cached(file_name, subfolder)

    if file_bytes is None:
        st.error(
            f"ファイルの取得に失敗しました。\n\n"
            f"ファイル: `raw/{subfolder}/{file_name}`\n\n"
            f"Fabric環境変数が設定されているか、ファイルがOneLakeに存在するか確認してください。"
        )
        return

    # ファイルタイプに応じた表示
    if is_pdf:
        _render_pdf(file_bytes, page_num, source.get("bbox"))
    elif is_csv:
        _render_csv(file_bytes, row_num)
    else:
        st.warning(f"未対応のファイル形式です: {file_name}")
        # フォールバック: ダウンロードボタンを表示
        st.download_button(
            label="ファイルをダウンロード",
            data=file_bytes,
            file_name=file_name,
        )


@st.cache_data(show_spinner=False)
def _download_cached(filename: str, subfolder: str) -> bytes | None:
    """OneLakeからのダウンロード結果をキャッシュする。"""
    return download_file_from_onelake(filename, subfolder)


def _render_pdf(file_bytes: bytes, page_num: int | None = None, bbox: dict | None = None):
    """
    PDFファイルを表示する。

    フェーズ1: iframe でPDF全体を表示
    フェーズ2: PyMuPDFでbbox座標にハイライト注釈を描画してから表示
    """
    display_bytes = file_bytes

    # フェーズ2: bboxがある場合はPyMuPDFでハイライトを描画
    if bbox and page_num:
        try:
            display_bytes = _add_pdf_highlight(file_bytes, page_num, bbox)
        except Exception as e:
            logger.warning(f"PDFハイライト描画に失敗（フォールバック）: {e}")
            # フォールバック: 元のPDFをそのまま表示

    # base64エンコードしてiframeで表示
    b64 = base64.b64encode(display_bytes).decode("utf-8")

    # ページジャンプ用のフラグメント
    page_fragment = f"#page={page_num}" if page_num else ""

    st.markdown(
        f'<iframe src="data:application/pdf;base64,{b64}{page_fragment}" '
        f'width="100%" height="800px" style="border: 1px solid #ddd; border-radius: 4px;">'
        f'</iframe>',
        unsafe_allow_html=True,
    )

    # ダウンロードボタンも表示
    st.download_button(
        label="PDFをダウンロード",
        data=file_bytes,
        file_name="source.pdf",
        mime="application/pdf",
    )


def _add_pdf_highlight(file_bytes: bytes, page_num: int, bbox: dict) -> bytes:
    """
    PyMuPDFでPDFの指定ページ・座標にハイライト注釈を描画する。
    フェーズ2で使用。PyMuPDFがインストールされていない場合は元のバイトを返す。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.info("PyMuPDFが未インストールのため、ハイライトなしで表示")
        return file_bytes

    x = bbox.get("x", 0)
    y = bbox.get("y", 0)
    w = bbox.get("w", 0)
    h = bbox.get("h", 0)

    if w == 0 or h == 0:
        return file_bytes

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    # page_numは1-based
    page_idx = page_num - 1
    if 0 <= page_idx < len(doc):
        page = doc[page_idx]
        rect = fitz.Rect(x, y, x + w, y + h)
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=(1, 1, 0))  # 黄色
        annot.update()

    result_bytes = doc.tobytes()
    doc.close()
    return result_bytes


def _render_csv(file_bytes: bytes, row_num: int | None = None):
    """
    CSVファイルをテーブルとして表示する。

    フェーズ1: 全行を表示
    フェーズ2: 指定行を黄色でハイライト
    """
    # エンコーディングを自動検出して読み込み
    df = None
    for encoding in ["utf-8-sig", "utf-8", "shift_jis", "cp932"]:
        try:
            df = pd.read_csv(
                pd.io.common.BytesIO(file_bytes),
                encoding=encoding,
            )
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue

    if df is None:
        st.error("CSVファイルの読み込みに失敗しました（文字コード不明）。")
        return

    st.markdown(f"**データ件数:** {len(df)}行")

    # フェーズ2: 行ハイライト
    if row_num is not None and 1 <= row_num <= len(df):
        # row_numは1-based、DataFrameは0-based
        target_idx = row_num - 1

        def highlight_row(s):
            if s.name == target_idx:
                return ["background-color: #fff3cd; font-weight: bold"] * len(s)
            return [""] * len(s)

        styled = df.style.apply(highlight_row, axis=1)
        st.dataframe(styled, use_container_width=True, height=600)
    else:
        st.dataframe(df, use_container_width=True, height=600)

    # ダウンロードボタン
    st.download_button(
        label="CSVをダウンロード",
        data=file_bytes,
        file_name="source.csv",
        mime="text/csv",
    )
