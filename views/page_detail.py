"""
page_detail.py — 算定詳細画面
"""

from __future__ import annotations

import html
import uuid
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from state_manager import (
    build_box1,
    confirm_patient,
    get_box2,
    get_patient_status,
    has_unsaved_changes,
    init_box2,
    reset_box2,
    save_edits,
    update_box2,
)
from views.santei_format import paste_code_line

DRUG_CATEGORY_ORDER = ["麻酔薬", "術後鎮痛薬", "注射薬", "その他薬剤", "Aライン", "★項目"]


def _safe(row: pd.Series, col: str, default: str = "-") -> str:
    val = row.get(col, default)
    if pd.isna(val):
        return default
    text = str(val).strip()
    return text if text else default


def _pick_patient_row(header_df: pd.DataFrame, patient_id: int, surgery_date: str) -> pd.Series | None:
    filt = header_df["患者ID"] == patient_id
    if "手術日" in header_df.columns:
        filt = filt & (header_df["手術日"].astype(str) == str(surgery_date))
    matched = header_df[filt]
    if matched.empty:
        return None
    return matched.iloc[0]


def _render_basic_info(h: pd.Series, masui_processed: pd.DataFrame, patient_id: int, surgery_date: str) -> None:
    def _get_masui_start() -> str:
        if masui_processed is None or masui_processed.empty:
            return "-"
        df = masui_processed[masui_processed["患者ID"] == patient_id]
        if "手術日" in df.columns:
            df = df[df["手術日"].astype(str) == str(surgery_date)]
        if df.empty:
            return "-"
        return _safe(df.iloc[0], "麻酔開始時間")

    dept = _safe(h, "診療科", "").replace("\n", "／")
    fields = [
        ("患者ID", _safe(h, "患者ID")),
        ("患者氏名", _safe(h, "患者氏名")),
        ("性別", _safe(h, "性別")),
        ("年齢", _safe(h, "年齢")),
        ("生年月日", _safe(h, "生年月日")),
        ("手術日", _safe(h, "手術日")),
        ("診療科", dept or "-"),
        ("手術室", _safe(h, "手術室")),
        ("病棟", _safe(h, "病棟")),
        ("予定区分", _safe(h, "予定区分")),
        ("確定術式", _safe(h, "確定術式")),
        ("確定病名", _safe(h, "確定病名")),
        ("手術時間", _safe(h, "手術時間")),
        ("麻酔時間", _safe(h, "麻酔時間")),
        ("入院外来", _safe(h, "入院外来")),
        ("感染症", _safe(h, "感染症")),
        ("感染症有無", _safe(h, "感染症有無")),
        ("最初の麻酔開始時間", _get_masui_start()),
        ("麻酔科医", _safe(h, "麻酔科医")),
        ("術者", _safe(h, "術者")),
    ]

    html_items: list[str] = []
    for idx, (label, value) in enumerate(fields, start=1):
        cls = "info-item full" if idx in (11, 12, 20) else "info-item"
        html_items.append(
            f'<div class="{cls}"><div class="info-label">{html.escape(label)}</div>'
            f'<div class="info-value">{html.escape(value)}</div></div>'
        )

    st.markdown(
        '<div class="section-box"><div style="padding:10px 12px;border-bottom:1px solid #ECEAE5;font-weight:600;">基本情報</div>'
        f'<div class="info-grid">{"".join(html_items)}</div></div>',
        unsafe_allow_html=True,
    )


def _aline_judgment(h: pd.Series) -> tuple[bool, str]:
    line_txt = _safe(h, "ライン", "")
    has_aline = "動脈" in line_txt
    if has_aline:
        return True, f"ライン列に「動脈」を含む（{line_txt}）"
    return False, "ライン列に「動脈」がない"


def _navi_judgment(navi_df: pd.DataFrame | None, patient_id: int, surgery_date: str) -> tuple[str, str]:
    if navi_df is None or navi_df.empty:
        return "判定不可", "ナビ判定データなし"
    df = navi_df[navi_df["患者ID"] == patient_id]
    if "手術日" in df.columns:
        df = df[df["手術日"].astype(str) == str(surgery_date)]
    if df.empty:
        return "判定不可", "該当患者のナビ判定なし"
    first = df.iloc[0]
    flag = _safe(first, "ナビフラグ", "判定不可")
    reason = _safe(first, "判定理由", "")
    return flag, (reason or "判定理由なし")


def _badge_html(label: str, css: str) -> str:
    return f'<span class="judgment-badge {css}">{html.escape(label)}</span>'


def _render_judgments(h: pd.Series, navi_df: pd.DataFrame | None, patient_id: int, surgery_date: str) -> bool:
    aline_flag, aline_reason = _aline_judgment(h)
    navi_flag, navi_reason = _navi_judgment(navi_df, patient_id, surgery_date)
    navi_css = "target" if navi_flag == "対象" else ("no" if navi_flag == "非対象" else "unknown")
    aline_html = _badge_html("あり" if aline_flag else "なし", "yes" if aline_flag else "no")
    navi_html = _badge_html(navi_flag, navi_css)
    st.markdown(
        '<div class="section-box"><div style="padding:10px 12px;border-bottom:1px solid #ECEAE5;font-weight:600;">判定項目</div>'
        '<div style="padding:10px 12px;">'
        f'<div class="judgment-row"><div class="judgment-label">Aライン判定</div>{aline_html}<div class="judgment-reason">{html.escape(aline_reason)}</div></div>'
        f'<div class="judgment-row"><div class="judgment-label">ナビ判定</div>{navi_html}<div class="judgment-reason">{html.escape(navi_reason)}</div></div>'
        "</div></div>",
        unsafe_allow_html=True,
    )
    return aline_flag


def _to_table_df(rows: list[dict], cols: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([{c: r.get(c, "") for c in cols} for r in rows])


def _render_masui_section(box2: list[dict]) -> None:
    masui_rows = [r for r in box2 if r.get("区分") == "麻酔" and r.get("状態") != "削除"]
    for r in masui_rows:
        r["貼り付けコード"] = paste_code_line(r)
    st.markdown("### 麻酔時間")
    st.dataframe(
        _to_table_df(masui_rows, ["項目名", "コード", "現在値", "単位", "貼り付けコード"]),
        use_container_width=True,
        hide_index=True,
    )


def _row_to_drug_category(row: dict) -> str:
    kubun = row.get("区分", "")
    if kubun == "Aライン":
        return "Aライン"
    if kubun == "★項目":
        return "★項目"
    if kubun == "薬剤（術後鎮痛）":
        return "術後鎮痛薬"
    cat = str(row.get("薬剤カテゴリ", "")).strip()
    return cat if cat else "その他薬剤"


def _render_drug_section(box2: list[dict], patient_id: int) -> list[dict]:
    st.markdown("### 薬剤コスト")
    source_drug_rows = [r for r in box2 if r.get("区分") in ("薬剤", "薬剤（術後鎮痛）", "Aライン", "★項目")]
    by_cat = {cat: [] for cat in DRUG_CATEGORY_ORDER}
    for r in source_drug_rows:
        by_cat.setdefault(_row_to_drug_category(r), []).append(r)

    rebuilt_drug_rows: list[dict] = []
    for cat in DRUG_CATEGORY_ORDER:
        st.markdown(f"#### ■ {cat}")
        rows = by_cat.get(cat, [])
        base = []
        for r in rows:
            base.append(
                {
                    "row_id": r.get("row_id", ""),
                    "薬品名": r.get("項目名", ""),
                    "課金コード": r.get("コード", ""),
                    "使用量": r.get("現在値", ""),
                    "単位": r.get("単位", ""),
                    "生食課金コード": r.get("生食課金コード", ""),
                    "_status": r.get("状態", "未変更"),
                    "_system_value": r.get("システム値", r.get("現在値", "")),
                    "_system_code": r.get("システムコード", r.get("コード", "")),
                }
            )
        base_df = pd.DataFrame(base)
        if base_df.empty:
            base_df = pd.DataFrame(columns=["row_id", "薬品名", "課金コード", "使用量", "単位", "生食課金コード", "_status", "_system_value", "_system_code"])

        edited_df = st.data_editor(
            base_df,
            key=f"drug_editor_{patient_id}_{cat}",
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "row_id": st.column_config.TextColumn("row_id", disabled=True),
                "薬品名": st.column_config.TextColumn("薬品名"),
                "課金コード": st.column_config.TextColumn("課金コード"),
                "使用量": st.column_config.TextColumn("使用量"),
                "単位": st.column_config.TextColumn("単位"),
                "生食課金コード": st.column_config.TextColumn("生食課金コード"),
                "_status": st.column_config.TextColumn("_status", disabled=True),
                "_system_value": st.column_config.TextColumn("_system_value", disabled=True),
                "_system_code": st.column_config.TextColumn("_system_code", disabled=True),
            },
            disabled=["row_id", "_status", "_system_value", "_system_code"],
        )
        edited_rows = edited_df.to_dict("records")
        seen_postop = False
        for er in edited_rows:
            row_id = str(er.get("row_id", "")).strip() or f"added_{uuid.uuid4().hex[:8]}"
            is_new = not any(str(r.get("row_id", "")) == row_id for r in rows)
            kubun = "薬剤"
            if cat == "術後鎮痛薬":
                kubun = "薬剤（術後鎮痛）"
            elif cat == "Aライン":
                kubun = "Aライン"
            elif cat == "★項目":
                kubun = "★項目"
            row = {
                "row_id": row_id,
                "区分": kubun,
                "薬剤カテゴリ": cat,
                "項目名": str(er.get("薬品名", "")),
                "コード": str(er.get("課金コード", "")),
                "システムコード": str(er.get("_system_code", er.get("課金コード", ""))),
                "システム値": str(er.get("_system_value", er.get("使用量", ""))),
                "現在値": str(er.get("使用量", "")),
                "単位": str(er.get("単位", "")),
                "生食課金コード": str(er.get("生食課金コード", "")),
                "状態": "追加" if is_new else "未変更",
            }
            if (row["コード"] != row["システムコード"] or row["現在値"] != row["システム値"]) and row["状態"] != "追加":
                row["状態"] = "修正済み"
            if cat == "術後鎮痛薬":
                row["_is_first_postop"] = not seen_postop
                seen_postop = True
            rebuilt_drug_rows.append(row)

    masui_rows = [r for r in box2 if r.get("区分") == "麻酔"]
    kensa_rows = [r for r in box2 if r.get("区分") == "検査"]
    navi_rows = [r for r in box2 if r.get("区分") == "ナビ"]
    other_rows = [
        r
        for r in box2
        if r.get("区分") not in ("麻酔", "薬剤", "薬剤（術後鎮痛）", "Aライン", "★項目", "検査", "ナビ")
    ]
    ordered = masui_rows + rebuilt_drug_rows + kensa_rows + navi_rows + other_rows
    for r in ordered:
        if r.get("区分") == "薬剤（術後鎮痛）" and "_is_first_postop" not in r:
            r["_is_first_postop"] = False
    return ordered


def _render_kensa_section(box2: list[dict]) -> None:
    kensa_rows = [r for r in box2 if r.get("区分") == "検査" and r.get("状態") != "削除"]
    st.markdown("### 検査")
    st.dataframe(
        _to_table_df(kensa_rows, ["項目名", "コード", "現在値", "単位"]),
        use_container_width=True,
        hide_index=True,
    )


def _render_copy_bar(box2: list[dict]) -> None:
    codes = [paste_code_line(r) for r in box2 if r.get("状態") != "削除"]
    codes = [c for c in codes if c and c != "—"]
    merged = "\n".join(codes)
    preview = (merged[:120] + "...") if len(merged) > 120 else merged
    esc_text = html.escape(merged, quote=True).replace("`", "\\`")
    st.markdown("### コードコピー")
    components.html(
        f"""
        <div style="background:#1E293B;padding:10px 12px;border-radius:6px;display:flex;align-items:center;gap:10px;">
          <code style="flex:1;color:#94A3B8;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{html.escape(preview)}</code>
          <button onclick="navigator.clipboard.writeText(`{esc_text}`).then(()=>{{this.textContent='✓ コピー済み';setTimeout(()=>this.textContent='📋 全コードをコピー',1500);}})"
                  style="background:#10B981;color:#fff;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:600;">
            📋 全コードをコピー
          </button>
        </div>
        """,
        height=52,
    )


def _render_confirm_bar(patient_id: int, surgery_date: str, box1: list[dict]) -> None:
    version_key = f"version_{patient_id}"
    cols = st.columns([1, 1, 1])
    if cols[0].button("全てリセット", type="secondary"):
        reset_box2(patient_id, box1)
        st.success("編集内容をリセットしました")
        st.rerun()
    if cols[1].button("保存", type="primary"):
        expected_ver = st.session_state.get(version_key, 0)
        ok, msg = save_edits(patient_id, surgery_date, box1, expected_ver)
        if ok:
            st.success(msg)
            st.session_state[version_key] = get_patient_status(patient_id, surgery_date)["バージョン"]
            st.rerun()
        else:
            st.error(msg)
    if cols[2].button("確定"):
        if has_unsaved_changes(patient_id):
            st.warning("先に保存してください")
            return
        ok, msg = confirm_patient(patient_id, surgery_date)
        if ok:
            st.success(msg)
        else:
            st.error(msg)


def render_detail(
    header_df: pd.DataFrame,
    masui_processed: pd.DataFrame,
    kensa_processed: pd.DataFrame,
    drugs_processed: pd.DataFrame,
    star_items_df: pd.DataFrame | None = None,
    navi_df: pd.DataFrame | None = None,
    masui_time_raw_df: pd.DataFrame | None = None,
    aline_master: pd.DataFrame | None = None,
) -> None:
    st.subheader("算定明細")
    if header_df is None or header_df.empty:
        st.warning("患者データがありません。")
        return

    patient_id = st.session_state.get("selected_patient_id")
    surgery_date = str(st.session_state.get("selected_surgery_date", ""))
    if patient_id is None:
        st.info("左の患者一覧から患者を選択してください。")
        return

    h = _pick_patient_row(header_df, int(patient_id), surgery_date)
    if h is None:
        st.error("患者ヘッダーが見つかりません。")
        return

    status = get_patient_status(int(patient_id), surgery_date)
    version_key = f"version_{patient_id}"
    if version_key not in st.session_state:
        st.session_state[version_key] = status["バージョン"]

    st.markdown(f"## {_safe(h, '患者氏名')}（ID: {patient_id}）")
    st.caption(f"手術日: {surgery_date} / ステータス: {status['ステータス']}")

    _render_basic_info(h, masui_processed, int(patient_id), surgery_date)
    aline_flag = _render_judgments(h, navi_df, int(patient_id), surgery_date)

    box1 = build_box1(
        int(patient_id),
        masui_processed,
        kensa_processed,
        drugs_processed,
        star_items_df=star_items_df,
        navi_df=navi_df,
        surgery_date=surgery_date,
        masui_time_raw_df=masui_time_raw_df,
        aline_master=aline_master,
        aline_flag=aline_flag,
    )
    init_box2(int(patient_id), box1)
    box2 = get_box2(int(patient_id))

    st.divider()
    _render_masui_section(box2)
    st.divider()
    box2 = _render_drug_section(box2, int(patient_id))
    st.divider()
    _render_kensa_section(box2)
    st.divider()
    _render_copy_bar(box2)
    update_box2(int(patient_id), box2)
    st.divider()
    _render_confirm_bar(int(patient_id), surgery_date, box1)
