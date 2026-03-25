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


def _build_detail_patient_options(header_df: pd.DataFrame) -> tuple[list[str], dict[str, tuple], dict[tuple, str]]:
    """
    算定明細用の患者選択肢を構築する。

    戻り値:
      (all_labels, label_to_tuple, tuple_to_label)
      - all_labels: selectbox 用ラベル列（先頭はプレースホルダ）
      - label_to_tuple: ラベル → (患者ID or None, 手術日 or None)
      - tuple_to_label: (患者ID, 手術日) → ラベル（未選択は (None, None)）
    """
    placeholder = "（患者を選択）"
    rows: list[tuple[int, object, str]] = []
    for _, row in header_df.iterrows():
        pid = int(row["患者ID"])
        sdate = row["手術日"]
        name = row["患者氏名"] if pd.notna(row["患者氏名"]) else ""
        lbl = f"{pid} / {name} / {sdate}"
        rows.append((pid, sdate, lbl))

    label_to_tuple: dict[str, tuple] = {placeholder: (None, None)}
    tuple_to_label: dict[tuple, str] = {(None, None): placeholder}
    for pid, sdate, lbl in rows:
        label_to_tuple[lbl] = (pid, sdate)
        tuple_to_label[(pid, sdate)] = lbl

    all_labels = [placeholder] + [r[2] for r in rows]
    return all_labels, label_to_tuple, tuple_to_label


def _ordered_kubun_labels(rows: list) -> list[str]:
    """
    算定項目をタブ表示する際の区分ラベル順を返す。
    定義済み区分を優先し、その後データ出現順で未知の区分を付与する。
    """
    if not rows:
        return []
    preferred = ["麻酔", "検査", "薬剤", "薬剤（術後鎮痛）", "★項目", "ナビ"]
    ordered: list[str] = [k for k in preferred if any(r.get("区分") == k for r in rows)]
    for r in rows:
        k = r.get("区分") or "（未分類）"
        if k not in ordered:
            ordered.append(k)
    return ordered


def _indices_by_kubun(box2: list) -> dict[str, list[int]]:
    """区分ごとの元リスト上の行インデックス（ウィジェット key 整合用）。"""
    out: dict[str, list[int]] = {}
    for i, row in enumerate(box2):
        k = row.get("区分") or "（未分類）"
        out.setdefault(k, []).append(i)
    return out


def _render_santei_row(i: int, row: dict) -> None:
    """算定項目の1行を描画し、row をその場で更新する。"""
    row_state = row["状態"]

    if row_state == "削除":
        cols = st.columns([1, 3, 1.5, 1.5, 1, 1.5])
        cols[0].markdown(f"~~{row['区分']}~~")
        cols[1].markdown(f"~~{row['項目名']}~~")
        cols[2].markdown(f"~~{row['システム値']}~~")
        cols[3].markdown(f"~~{row['現在値']}~~")
        cols[4].markdown(f"~~{row['単位']}~~")
        if cols[5].button("元に戻す", key=f"restore_{i}"):
            row["状態"] = "未変更"
            row["現在値"] = row["システム値"]
        return

    cols = st.columns([1, 3, 1.5, 1.5, 1, 1.5])
    cols[0].write(row["区分"])
    cols[1].write(row["項目名"])
    cols[2].write(row["システム値"])

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

    if str(new_value) != str(row["システム値"]):
        row["現在値"] = new_value
        if row["状態"] != "追加":
            row["状態"] = "修正済み"
    else:
        row["現在値"] = new_value
        if row["状態"] == "修正済み":
            row["状態"] = "未変更"

    if row_state == "修正済み":
        if cols[5].button("元に戻す", key=f"revert_{i}"):
            row["現在値"] = row["システム値"]
            row["状態"] = "未変更"
    elif row_state == "追加":
        if cols[5].button("削除", key=f"del_added_{i}"):
            row["状態"] = "削除"
    else:
        if cols[5].button("削除", key=f"del_{i}"):
            row["状態"] = "削除"

    if row_state == "修正済み":
        cols[5].caption("✏️ 変更")
    elif row_state == "追加":
        cols[5].caption("🆕 追加")


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
    st.subheader("算定明細")

    if header_df is None or header_df.empty:
        st.warning("患者データがありません。アップロード画面でデータを取り込んでください。")
        return

    all_labels, label_to_tuple, tuple_to_label = _build_detail_patient_options(header_df)
    _applied_key = "_detail_last_applied_tuple"
    select_key = "detail_patient_select"

    patient_id = st.session_state.get("selected_patient_id")
    surgery_date = st.session_state.get("selected_surgery_date")
    sess_tuple = (patient_id, surgery_date)

    # 患者一覧など別画面で session が変わったときだけウィジェットを同期する
    if st.session_state.get(_applied_key) != sess_tuple:
        if "detail_pending_switch" in st.session_state:
            del st.session_state["detail_pending_switch"]
        st.session_state[select_key] = tuple_to_label.get(sess_tuple, all_labels[0])
        st.session_state[_applied_key] = sess_tuple

    pending = st.session_state.get("detail_pending_switch")
    if pending:
        st.warning("未保存の変更があります。別の患者に切り替えますか？")
        pc1, pc2 = st.columns(2)
        if pc1.button("保存せずに切り替え", key="detail_force_patient_switch"):
            new_pid, new_date = pending
            st.session_state["selected_patient_id"] = new_pid
            st.session_state["selected_surgery_date"] = new_date
            st.session_state[select_key] = tuple_to_label[(new_pid, new_date)]
            st.session_state[_applied_key] = (new_pid, new_date)
            del st.session_state["detail_pending_switch"]
            st.rerun()
        if pc2.button("キャンセル", key="detail_cancel_patient_switch"):
            del st.session_state["detail_pending_switch"]
            st.rerun()

    st.selectbox("表示する患者", options=all_labels, key=select_key)
    chosen_label = st.session_state[select_key]
    chosen_tuple = label_to_tuple[chosen_label]

    if chosen_tuple != sess_tuple:
        new_pid, new_date = chosen_tuple
        if new_pid is None:
            st.session_state["selected_patient_id"] = None
            st.session_state["selected_surgery_date"] = None
            st.session_state[_applied_key] = (None, None)
            st.info("上のリストから患者を選択すると算定明細を表示します。")
            return
        if patient_id is not None and has_unsaved_changes(patient_id):
            st.session_state[select_key] = tuple_to_label.get(sess_tuple, all_labels[0])
            st.session_state["detail_pending_switch"] = (new_pid, new_date)
            st.rerun()
        st.session_state["selected_patient_id"] = new_pid
        st.session_state["selected_surgery_date"] = new_date
        st.session_state[_applied_key] = (new_pid, new_date)
        st.rerun()

    if patient_id is None:
        st.info("上のリストから患者を選択すると算定明細を表示します。")
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

    # --- 算定テーブルの表示・編集（区分ごとにタブ） ---
    st.subheader("算定項目")
    st.caption("区分ごとにタブを切り替えて確認・編集できます。")

    def _render_santei_table_header() -> None:
        header_cols = st.columns([1, 3, 1.5, 1.5, 1, 1.5])
        header_cols[0].markdown("**区分**")
        header_cols[1].markdown("**項目名**")
        header_cols[2].markdown("**システム値**")
        header_cols[3].markdown("**現在値**")
        header_cols[4].markdown("**単位**")
        header_cols[5].markdown("**操作**")

    if not box2:
        st.info("算定項目がありません。")
    else:
        kubun_order = _ordered_kubun_labels(box2)
        by_kubun = _indices_by_kubun(box2)
        tab_list = st.tabs(kubun_order)
        for tab_panel, kubun in zip(tab_list, kubun_order):
            with tab_panel:
                _render_santei_table_header()
                st.divider()
                for i in by_kubun.get(kubun, []):
                    _render_santei_row(i, box2[i])

    update_box2(patient_id, list(box2))

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
