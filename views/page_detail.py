"""
page_detail.py — 画面2: 算定明細（編集・保存・確定）

これがアプリの中核画面。
患者ごとの算定項目を表示し、ユーザーが値を編集・保存・確定できる。
"""

import pandas as pd
import streamlit as st

from state_manager import (
    build_box1,
    init_box2,
    get_box2,
    update_box2,
    reset_box2,
    has_unsaved_changes,
    save_edits,
    confirm_patient,
    get_patient_status,
)


def _get_masui_start_time(masui_df: pd.DataFrame, patient_id: int) -> str:
    """
    麻酔開始時間を取得する。

    引数:
      masui_df: apply_masui_rules() の出力
      patient_id: 患者ID

    戻り値:
      麻酔開始時間の文字列（例: "08:38"）。データがない場合は "-"
    """
    patient_data = masui_df[masui_df["患者ID"] == patient_id]
    if patient_data.empty:
        return "-"
    # 麻酔開始時間は全行で同じ値なので先頭行を取る
    start_time = patient_data.iloc[0].get("麻酔開始時間", "-")
    return str(start_time) if pd.notna(start_time) else "-"


def render_detail(
    header_df: pd.DataFrame,
    masui_df: pd.DataFrame,
    kensa_df: pd.DataFrame,
    drugs_df: pd.DataFrame,
    star_items_df: pd.DataFrame | None = None,
    navi_df: pd.DataFrame | None = None,
):
    """
    算定明細画面を描画する。

    表示内容:
      - 患者基本情報ヘッダー
      - 算定項目テーブル（システム値・現在値の二列表示）
      - 編集・保存・確定ボタン

    引数:
      header_df: load_header() で取得した患者基本情報
      masui_df: apply_masui_rules() の出力
      kensa_df: apply_kensa_rules() の出力
      drugs_df: apply_drug_rules() の出力
    """
    # --- 選択患者の確認 ---
    patient_id = st.session_state.get("selected_patient_id")
    surgery_date = st.session_state.get("selected_surgery_date")

    if patient_id is None:
        st.info("患者一覧画面で患者を選択してください。")
        return

    # --- 「一覧に戻る」ボタン ---
    if st.button("← 一覧に戻る"):
        # 未保存警告
        if has_unsaved_changes(patient_id):
            st.warning("未保存の変更があります。保存せずに移動しますか？")
            col_a, col_b = st.columns(2)
            if col_a.button("保存せずに移動", key="force_back"):
                st.session_state["current_page"] = "患者一覧"
                st.rerun()
            if col_b.button("キャンセル", key="cancel_back"):
                st.rerun()
            st.stop()
        else:
            st.session_state["current_page"] = "患者一覧"
            st.rerun()

    # --- 患者基本情報の取得 ---
    patient_row = header_df[header_df["患者ID"] == patient_id]
    if patient_row.empty:
        st.error(f"患者ID {patient_id} のデータが見つかりません。")
        return
    patient_row = patient_row.iloc[0]

    # --- ステータス取得 ---
    status_info = get_patient_status(patient_id, surgery_date)
    current_status = status_info["ステータス"]
    current_version = status_info["バージョン"]

    # 画面を開いた時点のバージョンをsession_stateに保存（楽観ロック用）
    version_key = f"version_{patient_id}"
    if version_key not in st.session_state:
        st.session_state[version_key] = current_version

    # --- 患者情報ヘッダーの表示 ---
    patient_name = patient_row["患者氏名"] if pd.notna(patient_row["患者氏名"]) else ""
    dept = str(patient_row["診療科"]).replace("\n", "・") if pd.notna(patient_row["診療科"]) else ""
    procedure = patient_row["確定術式"] if pd.notna(patient_row.get("確定術式")) else ""
    masui_start = _get_masui_start_time(masui_df, patient_id)

    st.header(f"{patient_name}（{patient_id}）")
    col1, col2, col3 = st.columns(3)
    col1.write(f"**手術日:** {surgery_date}")
    col2.write(f"**診療科:** {dept}")
    col3.write(f"**ステータス:** {current_status}")

    col4, col5, col6 = st.columns(3)
    col4.write(f"**術式:** {procedure}")
    col5.write(f"**麻酔開始時間:** {masui_start}")

    # --- ナビ判定表示 ---
    navi_text = "判定不可"
    if navi_df is not None and not navi_df.empty:
        match = navi_df[(navi_df["患者ID"] == patient_id) & (navi_df["手術日"] == surgery_date)] if "手術日" in navi_df.columns else navi_df[navi_df["患者ID"] == patient_id]
        if not match.empty:
            navi_text = str(match.iloc[0].get("ナビフラグ", navi_text))
    col6.write(f"**ナビ判定:** {navi_text}")

    # --- Silver追加フィールド（存在時のみ） ---
    extra_cols = []
    if "確定術式_申込" in patient_row.index and pd.notna(patient_row.get("確定術式_申込")):
        extra_cols.append(("確定術式_申込", str(patient_row.get("確定術式_申込"))))
    if "動脈ライン準備" in patient_row.index and pd.notna(patient_row.get("動脈ライン準備")):
        extra_cols.append(("動脈ライン準備", str(patient_row.get("動脈ライン準備"))))
    if "申込使用機器" in patient_row.index and pd.notna(patient_row.get("申込使用機器")):
        extra_cols.append(("申込使用機器", str(patient_row.get("申込使用機器"))))
    if extra_cols:
        st.caption(" / ".join([f"{k}: {v}" for k, v in extra_cols]))

    st.divider()

    # --- 箱1・箱2の初期化 ---
    box1 = build_box1(
        patient_id,
        masui_df,
        kensa_df,
        drugs_df,
        star_items_df=star_items_df,
        navi_df=navi_df,
        surgery_date=surgery_date,
    )
    init_box2(patient_id, box1)
    box2 = get_box2(patient_id)

    # --- 未保存警告のJavaScript（ブラウザ閉じ防止） ---
    if has_unsaved_changes(patient_id):
        st.components.v1.html("""
        <script>
        window.onbeforeunload = function() {
            return "未保存の変更があります。";
        };
        </script>
        """, height=0)

    # --- 算定テーブルの表示・編集 ---
    st.subheader("算定項目")

    # テーブルヘッダー
    header_cols = st.columns([1, 3, 1.5, 1.5, 1, 1.5])
    header_cols[0].markdown("**区分**")
    header_cols[1].markdown("**項目名**")
    header_cols[2].markdown("**システム値**")
    header_cols[3].markdown("**現在値**")
    header_cols[4].markdown("**単位**")
    header_cols[5].markdown("**操作**")

    st.divider()

    # 各行を表示
    updated_rows = []
    for i, row in enumerate(box2):
        row_state = row["状態"]

        # 削除された行は取り消し線で表示
        if row_state == "削除":
            cols = st.columns([1, 3, 1.5, 1.5, 1, 1.5])
            cols[0].markdown(f"~~{row['区分']}~~")
            cols[1].markdown(f"~~{row['項目名']}~~")
            cols[2].markdown(f"~~{row['システム値']}~~")
            cols[3].markdown(f"~~{row['現在値']}~~")
            cols[4].markdown(f"~~{row['単位']}~~")
            # 「元に戻す」ボタン
            if cols[5].button("元に戻す", key=f"restore_{i}"):
                row["状態"] = "未変更"
                row["現在値"] = row["システム値"]
            updated_rows.append(row)
            continue

        # 通常の行表示
        cols = st.columns([1, 3, 1.5, 1.5, 1, 1.5])
        cols[0].write(row["区分"])
        cols[1].write(row["項目名"])
        cols[2].write(row["システム値"])

        # 現在値を編集可能にする
        if row["区分"] == "ナビ":
            new_value = cols[3].selectbox(
                "現在値",
                options=["対象", "非対象", "判定不可"],
                index=["対象", "非対象", "判定不可"].index(str(row["現在値"])) if str(row["現在値"]) in ["対象", "非対象", "判定不可"] else 2,
                key=f"val_{i}",
                label_visibility="collapsed",
            )
        else:
            new_value = cols[3].text_input(
                "現在値",
                value=str(row["現在値"]),
                key=f"val_{i}",
                label_visibility="collapsed",
            )

        cols[4].write(row["単位"])

        # 値が変わったら状態を「修正済み」に更新
        if str(new_value) != str(row["システム値"]):
            row["現在値"] = new_value
            if row["状態"] != "追加":  # 追加行は状態を変えない
                row["状態"] = "修正済み"
        else:
            row["現在値"] = new_value
            if row["状態"] == "修正済み":
                row["状態"] = "未変更"

        # 操作ボタン
        if row_state == "修正済み":
            # 変更済み → 「元に戻す」ボタンを表示
            if cols[5].button("元に戻す", key=f"revert_{i}"):
                row["現在値"] = row["システム値"]
                row["状態"] = "未変更"
        elif row_state == "追加":
            # 追加行 → 「削除」ボタンを表示
            if cols[5].button("削除", key=f"del_added_{i}"):
                row["状態"] = "削除"
        else:
            # 未変更 → 「削除」ボタンを表示
            if cols[5].button("削除", key=f"del_{i}"):
                row["状態"] = "削除"

        # 修正済みの行は背景色で強調（CSSでの対応が難しいので、ラベルで表示）
        if row_state == "修正済み":
            cols[5].caption("✏️ 変更")
        elif row_state == "追加":
            cols[5].caption("🆕 追加")

        updated_rows.append(row)

    # 箱2を更新
    update_box2(patient_id, updated_rows)

    st.divider()

    # --- 項目追加フォーム ---
    with st.expander("＋ 項目を追加"):
        add_cols = st.columns([1, 3, 1.5, 1.5, 1])
        new_kubun = add_cols[0].selectbox(
            "区分", ["麻酔", "検査", "薬剤", "★項目", "ナビ"], key="add_kubun"
        )

        if new_kubun == "ナビ":
            new_name = "ナビゲーション加算"
            new_code = ""
            new_unit = ""
            new_qty = add_cols[3].selectbox("数量", ["対象", "非対象", "判定不可"], key="add_navi_qty")
            add_cols[1].text_input("項目名", value=new_name, disabled=True, key="add_name_disabled")
            add_cols[2].text_input("コード", value="", disabled=True, key="add_code_disabled")
            add_cols[4].text_input("単位", value="", disabled=True, key="add_unit_disabled")
        else:
            new_name = add_cols[1].text_input("項目名", key="add_name")
            new_code = add_cols[2].text_input("コード", key="add_code")
            new_qty = add_cols[3].text_input("数量", key="add_qty")
            new_unit = add_cols[4].text_input("単位", key="add_unit")

        if st.button("追加する"):
            code_required = new_kubun not in ["★項目", "ナビ"]
            if new_name and (new_code or not code_required):
                # 新しい行を箱2に追加
                current_box2 = get_box2(patient_id)
                new_row_id = f"added_{len(current_box2) + 1:03d}"
                if new_kubun == "★項目" and (new_qty is None or str(new_qty).strip() == ""):
                    new_qty = new_name
                new_row = {
                    "row_id": new_row_id,
                    "区分": new_kubun,
                    "項目名": new_name,
                    "コード": new_code,
                    "数量": new_qty,
                    "単位": new_unit,
                    "システム値": "-",
                    "現在値": new_qty,
                    "状態": "追加",
                }
                current_box2.append(new_row)
                update_box2(patient_id, current_box2)
                st.success(f"「{new_name}」を追加しました")
                st.rerun()
            else:
                if code_required:
                    st.warning("項目名とコードは必須です")
                else:
                    st.warning("項目名は必須です")

    # --- アクションボタン ---
    st.divider()
    btn_cols = st.columns([1, 1, 1])

    # 全てリセット
    if btn_cols[0].button("全てリセット", type="secondary"):
        reset_box2(patient_id, box1)
        st.success("全ての編集をリセットしました")
        st.rerun()

    # 保存
    if btn_cols[1].button("保存", type="primary"):
        expected_ver = st.session_state.get(version_key, 0)
        success, msg = save_edits(patient_id, surgery_date, box1, expected_ver)
        if success:
            st.success(msg)
            # バージョンを更新
            new_status = get_patient_status(patient_id, surgery_date)
            st.session_state[version_key] = new_status["バージョン"]
            st.rerun()
        else:
            st.error(msg)

    # 確定
    if btn_cols[2].button("確定"):
        # 未保存の変更がある場合は警告
        if has_unsaved_changes(patient_id):
            st.warning("先に保存してください")
        else:
            success, msg = confirm_patient(patient_id, surgery_date)
            if success:
                st.success(msg)
                # 一覧画面に戻る
                st.session_state["current_page"] = "患者一覧"
                st.rerun()
            else:
                st.error(msg)
