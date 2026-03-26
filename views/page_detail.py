"""
page_detail.py — 画面2: 算定明細（編集・保存・確定）

これがアプリの中核画面。
患者ごとの算定項目を表示し、ユーザーが値を編集・保存・確定できる。
"""

import html
import json
import base64
import pandas as pd
import streamlit as st
import streamlit.components.v1 as st_components

from views.ui_helpers import zebra_row_container, inject_colored_cell_style
from views.santei_format import (
    description_line,
    paste_code_line,
    seishoku_display,
)
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


def _sync_masui_segments_from_box1(box2: list, box1: list) -> None:
    """
    箱2は初回のみ箱1から作られるため、既存セッションでも麻酔の内訳を毎回箱1に合わせる。
    （生データに基づく参照情報のため、編集内容には影響しない。）
    """
    by_id = {r["row_id"]: r for r in box1}
    for r in box2:
        if r.get("区分") != "麻酔":
            continue
        src = by_id.get(r["row_id"])
        if not src:
            continue
        if src.get("麻酔時間内訳"):
            r["麻酔時間内訳"] = src["麻酔時間内訳"]
        else:
            r.pop("麻酔時間内訳", None)


def _masui_segments_tooltip_st_html(
    row_index: int,
    slot: str,
    segments: list,
    trigger_label: str,
    *,
    icon: bool = False,
) -> str:
    """
    ホバーで内訳を表示する HTML（st.html 用）。

    st.markdown の HTML は DOMPurify で class が落ち、app 側の CSS が効かないため、
    行ごとにユニーク id と埋め込み <style> で :hover を定義する。
    """
    esc = html.escape
    wrap_id = f"omw{row_index}{slot}"
    panel_id = f"omp{row_index}{slot}"
    esc_label = esc(trigger_label)
    aria = esc("開始・終了・合計の内訳")

    body_parts: list[str] = []
    n = len(segments)
    for idx, seg in enumerate(segments, start=1):
        s0, s1, s2 = esc(str(seg["開始"])), esc(str(seg["終了"])), esc(str(seg["合計"]))
        sep = "" if idx == n else "margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid rgba(30,58,95,.1);"
        body_parts.append(
            f'<div style="{sep}">'
            f'<span style="display:block;font-weight:600;margin-bottom:4px;color:#1a5276;">区間 {idx}</span>'
            f'<span style="color:#1e3a4c;">{s0} 〜 {s1}</span>'
            f'<span style="display:block;margin-top:4px;font-size:12px;color:#5c7a8f;">合計 {s2}</span>'
            f"</div>"
        )
    panel_body = "".join(body_parts)

    if icon:
        trig = (
            "cursor:help;border-bottom:none;font-weight:600;font-size:1rem;line-height:1;"
            "padding:2px 6px;border-radius:4px;color:#2e86c1;transition:background .15s,color .15s;"
        )
        trig_hover = f"#{wrap_id}:hover > span:first-child {{ color:#1a5276;background:rgba(46,134,193,.12); }}"
    else:
        trig = (
            "cursor:help;border-bottom:1px dashed rgba(46,134,193,.75);"
            "transition:border-color .15s,color .15s;"
        )
        trig_hover = (
            f"#{wrap_id}:hover > span:first-child {{ "
            f"border-bottom-color:rgba(26,82,118,.95) !important;color:#1a5276; }}"
        )

    panel_style = (
        "position:absolute;left:0;top:100%;margin-top:8px;min-width:240px;max-width:min(360px,90vw);"
        "padding:12px 14px;"
        "background:linear-gradient(165deg,rgba(255,255,255,.98) 0%,#f5f9fc 45%,#eef6fb 100%);"
        "color:#1e3a4c;font-size:13px;line-height:1.45;border-radius:10px;"
        "box-shadow:0 10px 36px rgba(30,58,95,.1),0 2px 10px rgba(0,0,0,.06);"
        "border:1px solid rgba(46,134,193,.2);opacity:0;visibility:hidden;"
        "transform:translateY(-6px) scale(0.98);transition:opacity .2s ease,transform .22s cubic-bezier(0.22,1,0.36,1),visibility .2s;"
        "z-index:999999;pointer-events:none;"
    )

    hover_panel = (
        f"#{wrap_id}:hover #{panel_id} {{ "
        f"opacity:1 !important;visibility:visible !important;"
        f"transform:translateY(0) scale(1) !important;pointer-events:auto !important; }}"
    )

    return (
        f"<style>{hover_panel}{trig_hover}</style>"
        f'<div id="{wrap_id}" style="position:relative;display:inline-block;vertical-align:baseline;">'
        f'<span style="{trig}" title="" aria-label="{aria}">{esc_label}</span>'
        f'<div id="{panel_id}" role="tooltip" style="{panel_style}">{panel_body}</div>'
        f"</div>"
    )


def _render_masui_tooltip_dg(dg, row_index: int, slot: str, segments: list, label: str, *, icon: bool = False) -> None:
    """st.html が使える場合はサニタイズ後も style/id が効く。無ければ details でフォールバック。"""
    fragment = _masui_segments_tooltip_st_html(row_index, slot, segments, label, icon=icon)
    html_fn = getattr(dg, "html", None)
    if callable(html_fn):
        html_fn(fragment, width="content")
    else:
        lines = [
            f"区間 {idx}: {seg['開始']} 〜 {seg['終了']}（合計 {seg['合計']}）"
            for idx, seg in enumerate(segments, start=1)
        ]
        dg.markdown(
            "<details><summary>" + html.escape(label) + "</summary><pre>"
            + html.escape("\n".join(lines))
            + "</pre></details>",
            unsafe_allow_html=True,
        )


def _render_source_button(container, row: dict, i: int) -> None:
    """元データ確認ボタンを描画する。ソース情報がない場合は何も表示しない。"""
    sources = row.get("_sources", [])
    if not sources:
        return

    item_name = row.get("項目名", "")
    sources_json = json.dumps(sources, ensure_ascii=False)
    sources_b64 = base64.urlsafe_b64encode(sources_json.encode("utf-8")).decode("utf-8")

    # URLエンコードされた項目名
    import urllib.parse
    item_encoded = urllib.parse.quote(item_name, safe="")

    url = f"?page=source_viewer&item={item_encoded}&sources={sources_b64}"

    # ボタンクリックでJavaScriptで新タブを開く
    with container:
        if st.button("📄", key=f"src_{i}", help="元データを確認"):
            st_components.html(
                f'<script>window.open("{url}", "_blank");</script>',
                height=0,
            )


def _editable_billing_code_kubun(kubun: str) -> bool:
    """課金コードを画面上で編集できる区分（プレースホルダが出るのは主に薬剤）。"""
    return kubun in ("薬剤", "薬剤（術後鎮痛）")


def _render_santei_grid_header() -> None:
    """スプレッドシート風の列見出し（画像の帳票イメージに合わせる）。"""
    st.markdown(
        """
<style>
.orbit-santei-head { display: grid; grid-template-columns: minmax(0,2.2fr) 1fr 1.2fr 1fr 1.2fr 0.7fr 0.35fr; gap: 0; align-items: stretch; font-size: 13px; font-weight: 600; border-bottom: 2px solid #333; margin-bottom: 4px; }
.orbit-santei-head > div { padding: 8px 6px; border-top: 1px solid #bbb; border-right: 1px solid #bbb; border-bottom: 1px solid #bbb; }
.orbit-santei-head > div:first-child { border-left: 1px solid #bbb; }
.orbit-santei-h-desc { background: #ffffff; }
.orbit-santei-h-code { background: #ffffff; }
.orbit-santei-h-qty { background: #ffffff; }
.orbit-santei-h-sei { background: #ffffff; }
.orbit-santei-h-paste { background: #ffffff; border-left: 3px solid #000 !important; }
</style>
<div class="orbit-santei-head">
  <div class="orbit-santei-h-desc">↓ 貼り付け / Paste</div>
  <div class="orbit-santei-h-code">課金コード</div>
  <div class="orbit-santei-h-qty">使用量（システム値 / 現在値）</div>
  <div class="orbit-santei-h-sei">生食課金コード</div>
  <div class="orbit-santei-h-paste">貼り付けコード</div>
  <div class="orbit-santei-h-desc">操作</div>
  <div class="orbit-santei-h-desc">元</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_santei_row(
    i: int,
    row: dict,
    *,
    stripe_index: int,
    box1_by_id: dict,
) -> None:
    """算定項目の1行を描画し、row をその場で更新する。"""
    row.setdefault("生食課金コード", "")
    row_state = row["状態"]
    masui_segments = row.get("麻酔時間内訳") or []
    sys_code = str(row.get("システムコード", row.get("コード", "")))
    src_box1 = box1_by_id.get(row["row_id"])

    with zebra_row_container(stripe_index, f"orbit_santei_{i}"):
        if row_state == "削除":
            cols = st.columns([2.2, 1.0, 1.3, 1.0, 1.3, 0.8, 0.4])
            with cols[0]:
                inject_colored_cell_style(f"orbit_desc_{i}", "#ffffff")
                with st.container(key=f"orbit_desc_{i}"):
                    st.markdown(f"~~{html.escape(description_line(row))}~~", unsafe_allow_html=True)
            with cols[1]:
                inject_colored_cell_style(f"orbit_code_{i}", "#ffffff")
                with st.container(key=f"orbit_code_{i}"):
                    code_disp = row.get("コード", "")
                    st.markdown(
                        f"~~{html.escape(str(code_disp) if str(code_disp).strip() else '—')}~~",
                        unsafe_allow_html=True,
                    )
            with cols[2]:
                inject_colored_cell_style(f"orbit_qty_{i}", "#ffffff")
                with st.container(key=f"orbit_qty_{i}"):
                    st.markdown(
                        f"~~システム: {html.escape(str(row['システム値']))} / 現在: {html.escape(str(row['現在値']))}~~",
                        unsafe_allow_html=True,
                    )
            with cols[3]:
                inject_colored_cell_style(f"orbit_sei_{i}", "#ffffff")
                with st.container(key=f"orbit_sei_{i}"):
                    st.markdown(
                        f"~~{html.escape(seishoku_display(row))}~~",
                        unsafe_allow_html=True,
                    )
            with cols[4]:
                inject_colored_cell_style(f"orbit_paste_{i}", "#ffffff", left_border="3px solid #000")
                with st.container(key=f"orbit_paste_{i}"):
                    pd = paste_code_line(row) or "—"
                    st.markdown(f"~~{html.escape(pd)}~~", unsafe_allow_html=True)
            with cols[5]:
                inject_colored_cell_style(f"orbit_act_{i}", "#ffffff")
                with st.container(key=f"orbit_act_{i}"):
                    if st.button("元に戻す", key=f"restore_{i}"):
                        row["状態"] = "未変更"
                        row["現在値"] = row["システム値"]
                        row["コード"] = row.get("システムコード", row.get("コード", ""))
                        if src_box1 is not None:
                            row["生食課金コード"] = src_box1.get("生食課金コード", "")
            _render_source_button(cols[6], row, i)
            return

        cols = st.columns([2.2, 1.0, 1.3, 1.0, 1.3, 0.8, 0.4])

        with cols[0]:
            inject_colored_cell_style(f"orbit_desc_{i}", "#ffffff")
            with st.container(key=f"orbit_desc_{i}"):
                st.markdown(html.escape(description_line(row)), unsafe_allow_html=True)

        code_disp = row.get("コード", "")
        with cols[1]:
            inject_colored_cell_style(f"orbit_code_{i}", "#ffffff")
            with st.container(key=f"orbit_code_{i}"):
                if _editable_billing_code_kubun(row["区分"]):
                    new_code = st.text_input(
                        "課金コード",
                        value=str(code_disp),
                        key=f"code_{i}",
                        label_visibility="collapsed",
                    )
                else:
                    st.markdown(
                        html.escape(str(code_disp) if str(code_disp).strip() else "—"),
                        unsafe_allow_html=True,
                    )
                    new_code = str(code_disp)

        with cols[2]:
            inject_colored_cell_style(f"orbit_qty_{i}", "#ffffff")
            with st.container(key=f"orbit_qty_{i}"):
                st.caption("システム値")
                if row["区分"] == "麻酔" and masui_segments:
                    _render_masui_tooltip_dg(st, i, "sys", masui_segments, str(row["システム値"]), icon=False)
                else:
                    st.write(row["システム値"])
                st.caption("現在値")
                if row["区分"] == "ナビ":
                    new_value = st.selectbox(
                        "現在値",
                        options=["対象", "非対象", "判定不可"],
                        index=["対象", "非対象", "判定不可"].index(str(row["現在値"]))
                        if str(row["現在値"]) in ["対象", "非対象", "判定不可"]
                        else 2,
                        key=f"val_{i}",
                        label_visibility="collapsed",
                    )
                elif row["区分"] == "麻酔" and masui_segments:
                    c4a, c4b = st.columns([5.2, 0.55], vertical_alignment="center")
                    with c4a:
                        new_value = st.text_input(
                            "現在値",
                            value=str(row["現在値"]),
                            key=f"val_{i}",
                            label_visibility="collapsed",
                        )
                    with c4b:
                        _render_masui_tooltip_dg(c4b, i, "ico", masui_segments, "ⓘ", icon=True)
                else:
                    new_value = st.text_input(
                        "現在値",
                        value=str(row["現在値"]),
                        key=f"val_{i}",
                        label_visibility="collapsed",
                    )

        _tmp = {**row, "コード": new_code, "現在値": new_value}
        paste_disp = paste_code_line(_tmp)
        if not paste_disp:
            paste_disp = "—"

        with cols[3]:
            inject_colored_cell_style(f"orbit_sei_{i}", "#ffffff")
            with st.container(key=f"orbit_sei_{i}"):
                st.markdown(html.escape(seishoku_display(row)), unsafe_allow_html=True)

        with cols[4]:
            inject_colored_cell_style(f"orbit_paste_{i}", "#ffffff", left_border="3px solid #000")
            with st.container(key=f"orbit_paste_{i}"):
                st.markdown(html.escape(paste_disp), unsafe_allow_html=True)

        if _editable_billing_code_kubun(row["区分"]):
            row["コード"] = new_code

        code_changed = str(new_code).strip() != str(sys_code).strip()
        value_changed = str(new_value) != str(row["システム値"])
        if code_changed or value_changed:
            row["現在値"] = new_value
            if row["状態"] != "追加":
                row["状態"] = "修正済み"
        else:
            row["現在値"] = new_value
            if row["状態"] == "修正済み":
                row["状態"] = "未変更"

        with cols[5]:
            inject_colored_cell_style(f"orbit_act_{i}", "#ffffff")
            with st.container(key=f"orbit_act_{i}"):
                if row_state == "修正済み":
                    if st.button("元に戻す", key=f"revert_{i}"):
                        row["現在値"] = row["システム値"]
                        row["コード"] = sys_code
                        if src_box1 is not None:
                            row["生食課金コード"] = src_box1.get("生食課金コード", "")
                        row["状態"] = "未変更"
                elif row_state == "追加":
                    if st.button("削除", key=f"del_added_{i}"):
                        row["状態"] = "削除"
                else:
                    if st.button("削除", key=f"del_{i}"):
                        row["状態"] = "削除"
                if row_state == "修正済み":
                    st.caption("✏️ 変更")
                elif row_state == "追加":
                    st.caption("🆕 追加")

        # 元データ確認ボタン（7列目）
        _render_source_button(cols[6], row, i)


def _get_masui_start_time(
    masui_df: pd.DataFrame, patient_id: int, surgery_date: str | None = None
) -> str:
    """
    麻酔開始時間を取得する。

    引数:
      masui_df: apply_masui_rules() の出力
      patient_id: 患者ID
      surgery_date: 手術日（列がある場合はこの日で絞り込む）

    戻り値:
      麻酔開始時間の文字列（例: "08:38"）。データがない場合は "-"
    """
    patient_data = masui_df[masui_df["患者ID"] == patient_id]
    if surgery_date is not None and "手術日" in patient_data.columns:
        patient_data = patient_data[
            patient_data["手術日"].astype(str) == str(surgery_date)
        ]
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
    masui_time_raw_df: pd.DataFrame | None = None,
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
      masui_time_raw_df: load_masui_time() の生データ（開始・終了の内訳表示用）
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
    masui_start = _get_masui_start_time(masui_df, patient_id, surgery_date)

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
        masui_time_raw_df=masui_time_raw_df,
    )
    init_box2(patient_id, box1)
    box2 = get_box2(patient_id)
    _sync_masui_segments_from_box1(box2, box1)

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
    st.caption(
        "区分ごとにタブを切り替えて確認・編集できます。"
        " 列は帳票イメージに合わせています（貼り付け / 課金コード / 使用量 / 生食課金コード / 貼り付けコード）。"
        " **課金コード** はコストシステム入力用（**貼り付けコード**列の「コード+数量」と対応）。"
        " **薬剤**・**薬剤（術後鎮痛）** の行では、ルールが「要手入力」「登録なし」などとしたコードを課金コード列で直接修正できます（**使用量**の現在値は数量のまま）。"
        " 区分が「薬剤（術後鎮痛）」の行は、出力・コピペ時にコード先頭へ **/33+** が付きます。"
        " **麻酔**のシステム値は下線の数字にカーソルを合わせると開始・終了の内訳が表示されます（現在値の **ⓘ** にも同じ内訳があります）。"
    )

    if not box2:
        st.info("算定項目がありません。")
    else:
        box1_by_id = {r["row_id"]: r for r in box1}
        kubun_order = _ordered_kubun_labels(box2)
        by_kubun = _indices_by_kubun(box2)
        tab_list = st.tabs(kubun_order)
        for tab_panel, kubun in zip(tab_list, kubun_order):
            with tab_panel:
                _render_santei_grid_header()
                st.divider()
                for stripe_j, i in enumerate(by_kubun.get(kubun, [])):
                    _render_santei_row(i, box2[i], stripe_index=stripe_j, box1_by_id=box1_by_id)

    update_box2(patient_id, list(box2))

    st.divider()

    # --- 項目追加フォーム ---
    with st.expander("＋ 項目を追加"):
        add_cols = st.columns([1, 3, 1.5, 1.5, 1])
        new_kubun = add_cols[0].selectbox(
            "追加先",
            ["麻酔", "検査", "薬剤", "★項目", "ナビ"],
            key="add_kubun",
            help="タブのグループ（麻酔・検査・薬剤など）と同じ区分に追加します。",
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
                    "システムコード": new_code,
                    "数量": new_qty,
                    "単位": new_unit,
                    "システム値": "-",
                    "現在値": new_qty,
                    "状態": "追加",
                    "生食課金コード": "",
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
