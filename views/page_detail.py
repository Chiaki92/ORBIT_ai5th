"""
page_detail.py — 算定詳細画面
"""

from __future__ import annotations

import html
import uuid
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from fabric_connection import download_file_from_onelake
from state_manager import (
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


@st.cache_data(show_spinner=False)
def _download_orbit_sheet_bytes() -> bytes | None:
    """Files/export の ORBIT_算定シート.xlsx を取得する。"""
    return download_file_from_onelake(
        filename="ORBIT_算定シート.xlsx",
        subfolder="",
        folder="export",
    )


def _render_detail_header() -> None:
    """算定明細タイトルと算定シートDLボタンを横並びで表示する。"""
    title_col, button_col = st.columns([0.7, 0.3])
    with title_col:
        st.subheader("算定明細")

    orbit_sheet_bytes = _download_orbit_sheet_bytes()
    with button_col:
        st.download_button(
            label="ORBIT_算定シート（Excel）をダウンロード",
            data=orbit_sheet_bytes or b"",
            file_name="ORBIT_算定シート.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=orbit_sheet_bytes is None,
            use_container_width=True,
            help=None if orbit_sheet_bytes else "Files/export にファイルが見つかりません。",
        )


def _inject_detail_styles() -> None:
    st.markdown(
        """
        <style>
        .judgment-list { display:flex; flex-direction:column; gap:10px; }
        .judgment-card {
            border:1px solid #DDD9D1;
            background:#FFFFFF;
            border-radius:8px;
            padding:10px 12px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }
        .judgment-head { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
        .judgment-label {
            font-weight:700;
            font-size:13px;
            color:#1A1917;
            min-width:140px;
        }
        .judgment-badge {
            display:inline-block;
            font-size:12px;
            font-weight:700;
            padding:2px 10px;
            border-radius:999px;
            border:1px solid transparent;
        }
        .judgment-badge.yes { background:#E6F3ED; color:#14543D; border-color:#B9DFC9; }
        .judgment-badge.no { background:#F3F4F6; color:#374151; border-color:#D1D5DB; }
        .judgment-badge.target { background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE; }
        .judgment-badge.unknown { background:#FEF3C7; color:#92400E; border-color:#FCD34D; }
        .judgment-reason {
            font-size:12px;
            color:#4B5563;
            line-height:1.6;
            margin-left:148px;
        }
        @media (max-width: 900px) {
            .judgment-head { flex-wrap:wrap; }
            .judgment-label { min-width:0; }
            .judgment-reason { margin-left:0; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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


def _pick_value(row: pd.Series, candidates: list[str], default: str = "") -> str:
    for col in candidates:
        if col in row.index:
            val = row.get(col, default)
            if pd.notna(val) and str(val).strip() != "":
                return str(val).strip()
    return default


def _render_basic_info(h: pd.Series, patient_id: int, surgery_date: str) -> None:
    masui_start = _pick_value(h, ["最初の麻酔開始時間", "麻酔開始時間"], "-")

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
        ("最初の麻酔開始時間", masui_start),
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

    with st.expander("基本情報", expanded=True):
        st.markdown(
            f'<div class="info-grid">{"".join(html_items)}</div>',
            unsafe_allow_html=True,
        )


def _aline_judgment(h: pd.Series) -> tuple[bool, str]:
    aline_txt = _pick_value(h, ["Aライン判定", "Aライン"], "")
    if aline_txt:
        has_aline = aline_txt in ("あり", "有", "Yes", "YES", "True", "1", "対象")
        return has_aline, f"Aライン判定: {aline_txt}"
    line_txt = _safe(h, "ライン", "")
    has_aline = "動脈" in line_txt
    if has_aline:
        return True, f"ライン列に「動脈」を含む（{line_txt}）"
    return False, "Aライン判定情報なし"


def _navi_judgment(h: pd.Series) -> tuple[str, str]:
    raw_flag = _pick_value(h, ["ナビゲーション判定", "ナビ判定", "ナビフラグ"], "")
    normalized = str(raw_flag).strip()
    if normalized in ("対象",):
        flag = "対象"
    elif normalized in ("対象外", "非対象"):
        flag = "対象外"
    elif normalized:
        # 想定外の表記ゆれは「対象外」に丸める
        flag = "対象外"
    else:
        # 仕様上は対象/対象外の2択。空値は対象外扱いにする。
        flag = "対象外"
    reason = _pick_value(h, ["ナビゲーション根拠", "ナビ判定理由", "判定理由"], "")
    if not reason and raw_flag in ("", "判定不可"):
        reason = "ナビ判定データ未連携"
    return flag, (reason or "判定理由なし")


def _badge_html(label: str, css: str) -> str:
    return f'<span class="judgment-badge {css}">{html.escape(label)}</span>'


def _render_judgments(h: pd.Series) -> bool:
    aline_flag, aline_reason = _aline_judgment(h)
    navi_flag, navi_reason = _navi_judgment(h)
    navi_css = "target" if navi_flag == "対象" else ("no" if navi_flag == "対象外" else "unknown")
    aline_html = _badge_html("あり" if aline_flag else "なし", "yes" if aline_flag else "no")
    navi_html = _badge_html(navi_flag, navi_css)
    with st.expander("判定項目", expanded=True):
        st.markdown(
            '<div class="judgment-list">'
            '<div class="judgment-card">'
            f'<div class="judgment-head"><div class="judgment-label">Aライン判定</div>{aline_html}</div>'
            f'<div class="judgment-reason">{html.escape(aline_reason)}</div>'
            "</div>"
            '<div class="judgment-card">'
            f'<div class="judgment-head"><div class="judgment-label">ナビ判定</div>{navi_html}</div>'
            f'<div class="judgment-reason">{html.escape(navi_reason)}</div>'
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    return aline_flag


def _to_table_df(rows: list[dict], cols: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([{c: r.get(c, "") for c in cols} for r in rows])


def _filter_patient_rows(df: pd.DataFrame, patient_id: int, surgery_date: str) -> pd.DataFrame:
    if df is None or df.empty or "患者ID" not in df.columns:
        return df.iloc[0:0] if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df[df["患者ID"] == patient_id]
    if "手術日" in out.columns:
        out = out[out["手術日"].astype(str) == str(surgery_date)]
    return out


def _to_box1_rows(
    patient_id: int,
    surgery_date: str,
    header_row: pd.Series,
    anesthesia_times_df: pd.DataFrame,
    exam_items_df: pd.DataFrame,
    drug_items_df: pd.DataFrame,
) -> list[dict]:
    rows: list[dict] = []
    counter = 1

    patient_masui = _filter_patient_rows(anesthesia_times_df, patient_id, surgery_date)
    for _, row in patient_masui.iterrows():
        rows.append({
            "row_id": f"masui_{counter:03d}",
            "区分": "麻酔",
            "項目名": _pick_value(row, ["名称", "麻酔種別", "麻酔区分"], "麻酔"),
            "コード": _pick_value(row, ["コード", "算定コード"], ""),
            "数量": _pick_value(row, ["合計時間", "時間", "数量"], "0"),
            "単位": _pick_value(row, ["単位"], "時間"),
            "生食課金コード": "",
        })
        counter += 1

    counter = 1
    patient_exam = _filter_patient_rows(exam_items_df, patient_id, surgery_date)
    for _, row in patient_exam.iterrows():
        rows.append({
            "row_id": f"kensa_{counter:03d}",
            "区分": "検査",
            "項目名": _pick_value(row, ["名称", "検査名", "項目名"], ""),
            "コード": _pick_value(row, ["コード", "検査コード"], ""),
            "数量": _pick_value(row, ["回数", "数量"], "0"),
            "単位": _pick_value(row, ["単位"], "回"),
            "生食課金コード": "",
        })
        counter += 1

    counter = 1
    patient_drugs = _filter_patient_rows(drug_items_df, patient_id, surgery_date)
    for _, row in patient_drugs.iterrows():
        source = _pick_value(row, ["ソース", "区分"], "")
        category = _pick_value(row, ["薬剤カテゴリ", "カテゴリ", "区分"], "")
        if "Aライン" in source:
            kubun = "Aライン"
            category = "Aライン"
        elif "★" in source:
            kubun = "★項目"
            category = "★項目"
        elif "術後鎮痛" in category:
            kubun = "薬剤（術後鎮痛）"
            category = "術後鎮痛薬"
        else:
            kubun = "薬剤"

        rows.append({
            "row_id": f"drug_{counter:03d}",
            "区分": kubun,
            "薬剤カテゴリ": category,
            "項目名": _pick_value(row, ["項目名", "薬剤名", "名称", "★項目"], ""),
            "コード": _pick_value(row, ["コード", "課金コード"], ""),
            "数量": _pick_value(row, ["数量", "使用量", "請求量", "回数"], ""),
            "単位": _pick_value(row, ["単位", "請求単位"], ""),
            "生食課金コード": _pick_value(row, ["生食課金コード"], ""),
        })
        counter += 1

    raw_navi_flag = _pick_value(header_row, ["ナビゲーション判定", "ナビ判定", "ナビフラグ"], "")
    if str(raw_navi_flag).strip() in ("対象",):
        navi_flag = "対象"
    else:
        navi_flag = "対象外"
    navi_reason = _pick_value(header_row, ["ナビゲーション根拠", "ナビ判定理由", "判定理由"], "")
    if not navi_reason and raw_navi_flag in ("", "判定不可"):
        navi_reason = "ナビ判定データ未連携"
    item_name = f"ナビゲーション加算（{navi_reason}）" if navi_reason else "ナビゲーション加算"
    rows.append({
        "row_id": "navi_001",
        "区分": "ナビ",
        "項目名": item_name,
        "コード": "",
        "数量": navi_flag,
        "単位": "",
        "生食課金コード": "",
    })
    return rows


def _render_masui_section(box2: list[dict]) -> None:
    masui_rows = [r for r in box2 if r.get("区分") == "麻酔" and r.get("状態") != "削除"]
    with st.expander("麻酔時間", expanded=True):
        st.dataframe(
            _to_table_df(masui_rows, ["項目名", "コード", "現在値", "単位"]),
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
    with st.expander("薬剤コスト", expanded=True):
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
                paste_code = paste_code_line(
                    {
                        "区分": r.get("区分", ""),
                        "コード": r.get("システムコード", r.get("コード", "")),
                        "現在値": r.get("システム値", r.get("現在値", "")),
                        "単位": r.get("単位", ""),
                        "生食課金コード": r.get("生食課金コード", ""),
                    }
                )
                base.append(
                    {
                        "_row_id": r.get("row_id", ""),
                        "薬品名": r.get("項目名", ""),
                        "課金コード": r.get("コード", ""),
                        "使用量": r.get("現在値", ""),
                        "単位": r.get("単位", ""),
                        "生食課金コード": r.get("生食課金コード", ""),
                        "貼り付けコード": paste_code,
                        "_status": r.get("状態", "未変更"),
                        "_system_value": r.get("システム値", r.get("現在値", "")),
                        "_system_code": r.get("システムコード", r.get("コード", "")),
                    }
                )
            base_df = pd.DataFrame(base)
            if base_df.empty:
                base_df = pd.DataFrame(columns=["_row_id", "薬品名", "課金コード", "使用量", "単位", "生食課金コード", "貼り付けコード", "_status", "_system_value", "_system_code"])

            edited_df = st.data_editor(
                base_df,
                key=f"drug_editor_{patient_id}_{cat}",
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                column_order=["薬品名", "課金コード", "使用量", "単位", "生食課金コード", "貼り付けコード"],
                column_config={
                    "薬品名": st.column_config.TextColumn("薬品名"),
                    "課金コード": st.column_config.TextColumn("課金コード"),
                    "使用量": st.column_config.TextColumn("使用量"),
                    "単位": st.column_config.TextColumn("単位"),
                    "生食課金コード": st.column_config.TextColumn("生食課金コード"),
                    "貼り付けコード": st.column_config.TextColumn("貼り付けコード", disabled=True),
                },
                disabled=["貼り付けコード"],
            )
            edited_rows = edited_df.to_dict("records")
            seen_postop = False
            for er in edited_rows:
                row_id = str(er.get("_row_id", "")).strip() or f"added_{uuid.uuid4().hex[:8]}"
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
    with st.expander("検査", expanded=True):
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
    with st.expander("コードコピー", expanded=True):
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
    anesthesia_times_df: pd.DataFrame,
    exam_items_df: pd.DataFrame,
    drug_items_df: pd.DataFrame,
) -> None:
    _render_detail_header()
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
    _inject_detail_styles()

    _render_basic_info(h, int(patient_id), surgery_date)
    _render_judgments(h)

    box1 = _to_box1_rows(
        int(patient_id),
        surgery_date,
        h,
        anesthesia_times_df,
        exam_items_df,
        drug_items_df,
    )
    init_box2(int(patient_id), box1)
    box2 = get_box2(int(patient_id))

    _render_masui_section(box2)
    box2 = _render_drug_section(box2, int(patient_id))
    _render_kensa_section(box2)
    _render_copy_bar(box2)
    update_box2(int(patient_id), box2)
    st.divider()
    _render_confirm_bar(int(patient_id), surgery_date, box1)
