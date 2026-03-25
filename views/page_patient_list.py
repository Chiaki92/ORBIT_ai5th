"""
page_patient_list.py — 画面1: 患者一覧

患者の一覧をテーブル形式で表示し、選択した患者の算定明細画面に遷移する。
ステータスに応じたカラーバッジ表示を行う。
"""

import pandas as pd
import streamlit as st

from state_manager import get_patient_status


# =============================================================================
# ステータスのカラーバッジ表示用HTML
# =============================================================================

STATUS_BADGE = {
    "確認待ち": '<span style="background-color:#FFF3CD;color:#856404;padding:2px 8px;border-radius:4px;font-weight:bold;">確認待ち</span>',
    "保存済み": '<span style="background-color:#CCE5FF;color:#004085;padding:2px 8px;border-radius:4px;font-weight:bold;">保存済み</span>',
    "確定済み": '<span style="background-color:#D4EDDA;color:#155724;padding:2px 8px;border-radius:4px;font-weight:bold;">確定済み</span>',
    "要再確認": '<span style="background-color:#F8D7DA;color:#721C24;padding:2px 8px;border-radius:4px;font-weight:bold;">要再確認</span>',
}

NAVI_BADGE = {
    "対象": '<span style="background-color:#D4EDDA;color:#155724;padding:2px 8px;border-radius:4px;font-weight:bold;">対象</span>',
    "非対象": '<span style="background-color:#E2E3E5;color:#383D41;padding:2px 8px;border-radius:4px;font-weight:bold;">非対象</span>',
    "判定不可": '<span style="background-color:#FFF3CD;color:#856404;padding:2px 8px;border-radius:4px;font-weight:bold;">判定不可</span>',
}

def render_patient_list(header_df: pd.DataFrame, navi_df: pd.DataFrame | None = None):
    """
    患者一覧画面を描画する。

    表示内容:
      - テーブル形式で患者一覧（患者ID, 氏名, 手術日, 診療科, 術式, ステータス）
      - ステータスに応じたカラーバッジ
      - 患者を選択すると算定明細画面に遷移

    引数:
      header_df: load_header() で取得した患者基本情報のDataFrame
    """
    st.header("📋 患者一覧")

    # --- 患者一覧データの構築 ---
    # ヘッダーDataFrameから必要な列を取り出す
    display_data = []
    for _, row in header_df.iterrows():
        patient_id = row["患者ID"]
        surgery_date = row["手術日"]

        # 患者ステータスを取得（JSONになければ「確認待ち」）
        status_info = get_patient_status(patient_id, surgery_date)
        status_text = status_info["ステータス"]

        # ナビ判定（あれば）
        navi_flag = "判定不可"
        if navi_df is not None and not navi_df.empty:
            try:
                match = navi_df[(navi_df["患者ID"] == patient_id) & (navi_df["手術日"] == surgery_date)]
                if not match.empty:
                    navi_flag = str(match.iloc[0].get("ナビフラグ", navi_flag))
            except Exception:
                navi_flag = "判定不可"

        display_data.append({
            "患者ID": patient_id,
            "患者氏名": row["患者氏名"],
            "手術日": surgery_date,
            "診療科": str(row["診療科"]).replace("\n", "・") if pd.notna(row["診療科"]) else "",
            "術式": row["確定術式"] if pd.notna(row.get("確定術式")) else "",
            "ナビ": navi_flag,
            "ステータス": status_text,
        })

    # --- ステータスバッジ付きのHTMLテーブル表示 ---
    # まず、サマリー情報を表示
    total = len(display_data)
    waiting = sum(1 for d in display_data if d["ステータス"] == "確認待ち")
    confirmed = sum(1 for d in display_data if d["ステータス"] == "確定済み")

    # サマリーをメトリクスで表示
    col1, col2, col3 = st.columns(3)
    col1.metric("全患者数", total)
    col2.metric("確認待ち", waiting)
    col3.metric("確定済み", confirmed)

    st.divider()

    # --- 各患者を行として表示 ---
    for i, data in enumerate(display_data):
        patient_id = data["患者ID"]
        surgery_date = data["手術日"]
        status = data["ステータス"]
        badge_html = STATUS_BADGE.get(status, status)
        navi_badge = NAVI_BADGE.get(data.get("ナビ", "判定不可"), data.get("ナビ", "判定不可"))

        # 各患者を1行として表示
        cols = st.columns([1, 2, 1.5, 1.5, 3, 1.2, 1.5, 1])
        cols[0].write(str(patient_id))
        cols[1].write(data["患者氏名"])
        cols[2].write(surgery_date)
        cols[3].write(data["診療科"])
        cols[4].write(data["術式"])
        cols[5].markdown(navi_badge, unsafe_allow_html=True)
        cols[6].markdown(badge_html, unsafe_allow_html=True)

        # 「詳細」ボタン → 算定明細画面に遷移
        if cols[7].button("詳細", key=f"detail_{i}"):
            st.session_state["selected_patient_id"] = patient_id
            st.session_state["selected_surgery_date"] = surgery_date
            st.session_state["current_page"] = "算定明細"
            st.rerun()

    # ヘッダー行をテーブル上部に表示
    if display_data:
        st.caption("※ 患者行の「詳細」ボタンをクリックすると算定明細画面に移動します")
