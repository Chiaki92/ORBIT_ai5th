"""
app.py — ORBIT（手術薬剤コスト算定システム）メインアプリ

UIモック準拠レイアウト:
  サイドバー: PDFアップロード / パイプライン実行 / 患者一覧
  メイン: 選択患者の算定詳細（基本情報 → 判定 → 麻酔 → 薬剤 → 検査）
"""

import os
import streamlit as st

# --- データ読み込みモジュール ---
from data_loader import (
    load_header,
    load_masui_time,
    load_kensa,
    load_drugs,
    load_seishoku_master,
    load_aline_master,
    load_star_items,
    load_kiji,
)

# --- 算定ルールモジュール ---
from rules.masui_rules import apply_masui_rules
from rules.kensa_rules import apply_kensa_rules
from rules.drug_rules import apply_drug_rules
from rules.navi_rules import apply_navi_rules

# --- 状態管理モジュール ---
from state_manager import get_patient_status

# --- 画面モジュール ---
from views.page_detail import render_detail
from views.page_source_viewer import render_source_viewer

# --- Fabric接続モジュール ---
from fabric_connection import (
    is_fabric_available,
    upload_file_to_onelake,
    trigger_notebook,
    trigger_dataflow,
    wait_for_job,
)


# =============================================================================
# ページ設定
# =============================================================================

st.set_page_config(
    page_title="ORBIT - 手術薬剤コスト算定",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# CSSスタイリング（モック準拠）
# =============================================================================

st.markdown("""
<style>
    /* サイドバーのスタイル */
    [data-testid="stSidebar"] {
        background-color: #FFFFFF;
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        padding-top: 0.5rem;
    }

    /* サイドバー見出し */
    .sidebar-brand {
        font-size: 20px;
        font-weight: 700;
        letter-spacing: 2px;
        color: #1A6B4E;
        margin-bottom: 0;
    }
    .sidebar-brand-sub {
        font-size: 11px;
        color: #9E9B93;
        margin-top: -4px;
    }

    /* ステータスバッジ */
    .badge {
        display: inline-block;
        font-size: 10px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 10px;
    }
    .badge-confirmed { background: #E6F3ED; color: #1A6B4E; }
    .badge-saved { background: #EFF6FF; color: #2563EB; }
    .badge-pending { background: #FFF7ED; color: #C2410C; }
    .badge-review { background: #FEE2E2; color: #991B1B; }

    /* パイプラインステータス */
    .pipeline-status {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 10px;
        border-radius: 6px;
        font-size: 11px;
        margin-top: 8px;
    }
    .pipeline-idle { background: #F0EFEC; color: #9E9B93; }
    .pipeline-running { background: #EFF6FF; color: #2563EB; }
    .pipeline-done { background: #E6F3ED; color: #1A6B4E; }

    /* テーブルのスタイル */
    .stDataFrame { font-size: 13px; }

    /* 算定明細: st.html のホバーパネルが列の overflow で切れにくくする */
    [data-testid="column"] { overflow: visible !important; }

    /* アップロード済みファイル */
    .uploaded-file-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        background: #E6F3ED;
        border-radius: 6px;
        margin-bottom: 4px;
        font-size: 11px;
    }
    .uploaded-file-item .fname { flex: 1; font-weight: 500; color: #1A6B4E; }
    .uploaded-file-item .fsize { color: #9E9B93; }

    /* セクションスタイル（モック準拠） */
    .section-box {
        background: #FFFFFF;
        border: 1px solid #DDD9D1;
        border-radius: 6px;
        margin-bottom: 16px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }

    /* 判定バッジ */
    .judgment-badge {
        display: inline-block;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 10px;
        min-width: 48px;
        text-align: center;
    }
    .judgment-yes { background: #E6F3ED; color: #1A6B4E; }
    .judgment-no { background: #F0EFEC; color: #9E9B93; }
    .judgment-target { background: #EFF6FF; color: #2563EB; }
    .judgment-unknown { background: #FFF7ED; color: #C2410C; }

    /* 情報グリッド */
    .info-grid {
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 0;
    }
    .info-item {
        padding: 6px 10px;
        border-bottom: 1px solid #ECEAE5;
        border-right: 1px solid #ECEAE5;
    }
    .info-item:nth-child(5n) { border-right: none; }
    .info-label {
        font-size: 9px;
        font-weight: 600;
        color: #9E9B93;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .info-value {
        font-size: 12px;
        font-weight: 500;
        margin-top: 1px;
    }
    .info-item.wide { grid-column: span 2; }
    .info-item.full { grid-column: 1 / -1; }

    /* モバイル対応 */
    @media (max-width: 767px) {
        .info-grid { grid-template-columns: repeat(2, 1fr); }
        .info-item.wide { grid-column: span 2; }
        .info-item.full { grid-column: 1 / -1; }
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# 元データ確認ページへのルーティング（新タブで開かれた場合）
# =============================================================================

query_params = st.query_params
if query_params.get("page") == "source_viewer":
    render_source_viewer()
    st.stop()


# =============================================================================
# データの読み込み（キャッシュ済み）
# =============================================================================

header_df = load_header()
masui_time_df = load_masui_time()
kensa_df = load_kensa()
drugs_df = load_drugs()
star_items_df = load_star_items()
kiji_df = load_kiji()
seishoku_master = load_seishoku_master()
aline_master = load_aline_master()


# =============================================================================
# 算定ルールの適用
# =============================================================================

masui_processed = apply_masui_rules(masui_time_df)
kensa_processed = apply_kensa_rules(kensa_df)
drugs_processed = apply_drug_rules(drugs_df, seishoku_master)
navi_result = apply_navi_rules(header_df, kiji_df)


# =============================================================================
# ヘルパー関数
# =============================================================================

def _status_badge_html(status_text: str) -> str:
    """ステータスに対応するバッジHTMLを返す"""
    css_class = {
        "確認待ち": "badge-pending",
        "保存済み": "badge-saved",
        "確定済み": "badge-confirmed",
        "要再確認": "badge-review",
    }.get(status_text, "badge-pending")
    label = {
        "確認待ち": "確認待",
        "保存済み": "保存済",
        "確定済み": "確認済",
        "要再確認": "要確認",
    }.get(status_text, status_text)
    return f'<span class="badge {css_class}">{label}</span>'


# =============================================================================
# サイドバー
# =============================================================================

with st.sidebar:
    # --- ブランドヘッダー ---
    st.markdown('<div class="sidebar-brand">ORBIT</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sidebar-brand-sub">手術薬剤コスト算定システム</div>',
        unsafe_allow_html=True,
    )

    # --- データ再読み込み ---
    if st.button("🔄 データ再読み込み", use_container_width=True):
        st.cache_data.clear()
        for k in list(st.session_state.keys()):
            if k.startswith("box2_") or k.startswith("version_"):
                del st.session_state[k]
        st.rerun()

    st.divider()

    # --- PDFアップロード ---
    with st.expander("📂 PDFアップロード", expanded=False):
        yakuzai_files = st.file_uploader(
            "使用薬剤レポート (PDF)", type=["pdf"],
            accept_multiple_files=True, key="upload_yakuzai",
        )
        masui_files = st.file_uploader(
            "麻酔検査レポート (PDF)", type=["pdf"],
            accept_multiple_files=True, key="upload_masui",
        )
        orsys_files = st.file_uploader(
            "ORSYS特殊検索 (CSV)", type=["csv"],
            accept_multiple_files=True, key="upload_orsys",
        )
        kiji_files = st.file_uploader(
            "記事データ (CSV)", type=["csv"],
            accept_multiple_files=True, key="upload_kiji",
        )

        # アップロード済みファイルを表示
        all_uploaded = []
        for f_list, label in [
            (yakuzai_files, "yakuzai"), (masui_files, "masui_kensa"),
            (orsys_files, "orsys"), (kiji_files, "karte_kiji"),
        ]:
            if f_list:
                for f in f_list:
                    all_uploaded.append((f, label))

        if all_uploaded:
            for f, subfolder in all_uploaded:
                sz = f.size
                size_str = f"{sz/1024:.0f}KB" if sz < 1024*1024 else f"{sz/(1024*1024):.1f}MB"
                st.markdown(
                    f'<div class="uploaded-file-item">'
                    f'<span>📄</span><span class="fname">{f.name}</span>'
                    f'<span class="fsize">{size_str}</span></div>',
                    unsafe_allow_html=True,
                )

            if st.button("📤 アップロード実行", use_container_width=True, type="primary"):
                if is_fabric_available():
                    with st.spinner("アップロード中..."):
                        for f, subfolder in all_uploaded:
                            upload_file_to_onelake(f.getvalue(), f.name, subfolder)
                    st.success("アップロード完了")
                else:
                    st.error("Fabric環境変数が未設定です。")

    st.divider()

    # --- パイプライン実行 ---
    if st.button("▶ パイプライン実行", use_container_width=True, type="primary"):
        if is_fabric_available():
            st.session_state["pipeline_status"] = "running"
            st.rerun()
        else:
            st.error("Fabric環境変数が未設定です。")

    # パイプラインステータス表示
    pipeline_st = st.session_state.get("pipeline_status", "idle")
    if pipeline_st == "running":
        st.markdown(
            '<div class="pipeline-status pipeline-running">'
            '<span>●</span> 実行中 — Bronze → Silver → Gold...</div>',
            unsafe_allow_html=True,
        )
        try:
            for env_key, trigger_fn in [
                ("NOTEBOOK_YAKUZAI_ID", trigger_notebook),
                ("NOTEBOOK_MASUI_KENSA_ID", trigger_notebook),
                ("NOTEBOOK_CSV_IMPORT_ID", trigger_notebook),
                ("DATAFLOW_ID", trigger_dataflow),
            ]:
                item_id = os.environ.get(env_key, "")
                if item_id:
                    loc = trigger_fn(item_id)
                    wait_for_job(loc)
            st.session_state["pipeline_status"] = "done"
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.session_state["pipeline_status"] = "error"
            st.error(f"パイプラインエラー: {e}")
    elif pipeline_st == "done":
        st.markdown(
            '<div class="pipeline-status pipeline-done">'
            f'<span>●</span> 完了 — {len(header_df)}件処理済み</div>',
            unsafe_allow_html=True,
        )
    elif pipeline_st == "error":
        st.markdown(
            '<div class="pipeline-status" style="background:#FEE2E2;color:#991B1B;">'
            '<span>●</span> エラーが発生しました</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="pipeline-status pipeline-idle">'
            '<span>○</span> 待機中</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- 患者一覧 ---
    if not header_df.empty:
        dates = sorted(header_df["手術日"].unique(), reverse=True)
        st.markdown(f"**患者一覧（{dates[0] if dates else ''}）**")
    else:
        st.markdown("**患者一覧**")
        st.info("データがありません。")

    if not header_df.empty:
        for _, row in header_df.iterrows():
            pid = row["患者ID"]
            name = str(row.get("患者氏名", "")).strip() or f"患者{pid}"
            date = str(row.get("手術日", "")).strip()
            dept = str(row.get("診療科", "")).strip()
            surgery = str(row.get("確定術式", "")).strip()
            meta = f"{dept}／{surgery}" if dept and surgery else (dept or surgery)

            status = get_patient_status(pid, date)
            badge = _status_badge_html(status["ステータス"])

            is_selected = (
                st.session_state.get("selected_patient_id") == pid
                and st.session_state.get("selected_surgery_date") == date
            )

            col_btn, col_badge = st.columns([4, 1])
            with col_btn:
                label = f"{'▸ ' if is_selected else ''}{name}（{pid}）"
                if st.button(
                    label, key=f"pt_{pid}_{date}",
                    use_container_width=True,
                    type="primary" if is_selected else "secondary",
                ):
                    st.session_state["selected_patient_id"] = pid
                    st.session_state["selected_surgery_date"] = date
                    st.rerun()
            with col_badge:
                st.markdown(badge, unsafe_allow_html=True)

            if meta:
                st.caption(f"　{meta[:35]}{'...' if len(meta) > 35 else ''}")


# =============================================================================
# メインコンテンツエリア
# =============================================================================

# 患者が選択されていない場合、最初の患者を自動選択
if "selected_patient_id" not in st.session_state and not header_df.empty:
    first = header_df.iloc[0]
    st.session_state["selected_patient_id"] = first["患者ID"]
    st.session_state["selected_surgery_date"] = str(first["手術日"])

# メイン画面の描画
render_detail(
    header_df=header_df,
    masui_processed=masui_processed,
    kensa_processed=kensa_processed,
    drugs_processed=drugs_processed,
    star_items_df=star_items_df,
    navi_df=navi_result,
    masui_time_raw_df=masui_time_df,
    aline_master=aline_master,
)
