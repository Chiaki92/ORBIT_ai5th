"""
page_output.py — 画面3: コピペ用出力・ダウンロード

確定済みの患者の算定データをコピペ用のフォーマットで表示する。
CSV/Excelダウンロード機能も提供する。
"""

import io

import pandas as pd
import streamlit as st

from state_manager import (
    build_box1,
    get_box2,
    init_box2,
    get_patient_status,
    get_all_patient_statuses,
)


def _build_output_text(box2_rows: list) -> str:
    """
    箱2のデータをコピペ用のテキストに変換する。

    出力フォーマット:
      コード+数量,
      ※ 術後鎮痛薬は末尾に配置し、コード先頭に /33+ を付与

    引数:
      box2_rows: 箱2のデータ（辞書のリスト）

    戻り値:
      コピペ用テキスト文字列
    """
    lines = []
    postop_lines = []

    for row in box2_rows:
        # 削除された行はスキップ
        if row["状態"] == "削除":
            continue

        # ★項目/ナビはコピペ出力から除外（コード+数量形式に合わない）
        if row.get("区分") in ["★項目", "ナビ"]:
            continue

        code = row["コード"]
        qty = row["現在値"]

        # 術後鎮痛薬は /33+ プレフィックス付きで末尾に
        if row["区分"] == "薬剤（術後鎮痛）":
            postop_lines.append(f"/33+{code}+{qty},")
        else:
            lines.append(f"{code}+{qty},")

    # 通常の項目 + 術後鎮痛薬（末尾）
    all_lines = lines + postop_lines
    return "\n".join(all_lines)


def _build_download_df(
    header_df: pd.DataFrame,
    patient_ids: list,
    masui_df: pd.DataFrame,
    kensa_df: pd.DataFrame,
    drugs_df: pd.DataFrame,
    star_items_df: pd.DataFrame | None = None,
    navi_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    ダウンロード用のDataFrameを構築する。

    引数:
      header_df: 患者基本情報
      patient_ids: 出力対象の患者IDリスト
      masui_df, kensa_df, drugs_df: ルール適用後のデータ

    戻り値:
      ダウンロード用DataFrame
    """
    all_rows = []

    for pid in patient_ids:
        # 患者情報の取得
        p_row = header_df[header_df["患者ID"] == pid]
        if p_row.empty:
            continue
        p_row = p_row.iloc[0]

        patient_name = p_row["患者氏名"] if pd.notna(p_row["患者氏名"]) else ""
        surgery_date = p_row["手術日"]

        # 箱2のデータを取得（初期化済みでなければ初期化）
        box1 = build_box1(
            pid,
            masui_df,
            kensa_df,
            drugs_df,
            star_items_df=star_items_df,
            navi_df=navi_df,
            surgery_date=surgery_date,
        )
        init_box2(pid, box1)
        box2 = get_box2(pid)

        for row in box2:
            if row["状態"] == "削除":
                continue
            all_rows.append({
                "患者ID": pid,
                "患者氏名": patient_name,
                "手術日": surgery_date,
                "区分": row["区分"],
                "項目名": row["項目名"],
                "コード": row["コード"],
                "数量": row["現在値"],
                "単位": row["単位"],
            })

    return pd.DataFrame(all_rows)


def render_output(
    header_df: pd.DataFrame,
    masui_df: pd.DataFrame,
    kensa_df: pd.DataFrame,
    drugs_df: pd.DataFrame,
    star_items_df: pd.DataFrame | None = None,
    navi_df: pd.DataFrame | None = None,
):
    """
    出力画面を描画する。

    表示内容:
      - 確定済み患者の一覧
      - 患者ごとのコピペ用出力ブロック
      - CSV/Excelダウンロードボタン

    引数:
      header_df: 患者基本情報
      masui_df, kensa_df, drugs_df: ルール適用後のデータ
    """
    st.header("📤 データ出力")

    # --- 出力対象の選択 ---
    output_scope = st.radio(
        "出力対象",
        ["確定済みのみ", "全患者"],
        horizontal=True,
    )

    # ステータス一覧を取得
    all_statuses = get_all_patient_statuses()
    confirmed_ids = set()
    for s in all_statuses:
        if s["ステータス"] == "確定済み":
            confirmed_ids.add(s["患者ID"])

    # 出力対象の患者IDリストを決定
    all_patient_ids = header_df["患者ID"].tolist()
    if output_scope == "確定済みのみ":
        target_ids = [pid for pid in all_patient_ids if pid in confirmed_ids]
    else:
        target_ids = all_patient_ids

    if not target_ids:
        st.info("出力対象の患者がいません。算定明細画面で確定操作を行ってください。")
        return

    st.write(f"**出力対象: {len(target_ids)}名**")

    st.divider()

    # --- 患者ごとのコピペ用出力 ---
    for pid in target_ids:
        p_row = header_df[header_df["患者ID"] == pid]
        if p_row.empty:
            continue
        p_row = p_row.iloc[0]

        patient_name = p_row["患者氏名"] if pd.notna(p_row["患者氏名"]) else ""
        surgery_date = p_row["手術日"]

        # 箱2データの取得
        box1 = build_box1(
            pid,
            masui_df,
            kensa_df,
            drugs_df,
            star_items_df=star_items_df,
            navi_df=navi_df,
            surgery_date=surgery_date,
        )
        init_box2(pid, box1)
        box2 = get_box2(pid)

        # 出力テキストの生成
        output_text = _build_output_text(box2)

        # 表示（st.codeでコピーボタン付き）
        st.subheader(f"■ {patient_name}（{pid}）{surgery_date}")
        st.code(output_text, language=None)

    # --- ダウンロード ---
    st.divider()
    st.subheader("ダウンロード")

    download_df = _build_download_df(
        header_df,
        target_ids,
        masui_df,
        kensa_df,
        drugs_df,
        star_items_df=star_items_df,
        navi_df=navi_df,
    )

    if download_df.empty:
        st.info("ダウンロードするデータがありません。")
        return

    # CSVダウンロード
    csv_data = download_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 CSVダウンロード",
        data=csv_data,
        file_name="orbit_output.csv",
        mime="text/csv",
    )

    # Excelダウンロード
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        download_df.to_excel(writer, index=False, sheet_name="算定データ")
    excel_data = excel_buffer.getvalue()

    st.download_button(
        label="📥 Excelダウンロード",
        data=excel_data,
        file_name="orbit_output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
