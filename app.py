"""
app.py — ORBIT（手術薬剤コスト算定システム）メインアプリ

UIモック準拠レイアウト:
  サイドバー: PDFアップロード / パイプライン実行 / 患者一覧
  メイン: 選択患者の算定詳細（基本情報 → 判定 → 麻酔 → 薬剤 → 検査）
"""

import os
from io import BytesIO

import pandas as pd
import streamlit as st

# --- データ読み込みモジュール ---
from data_loader import (
    load_surgery_summary,
    load_drug_items,
    load_anesthesia_times,
    load_exam_items,
)

# --- 状態管理モジュール ---
from state_manager import get_patient_status

# --- 画面モジュール ---
from views.page_detail import render_detail
from views.page_source_viewer import render_source_viewer

# --- Fabric接続モジュール ---
from fabric_connection import (
    download_file_from_onelake,
    is_fabric_available,
    upload_file_to_onelake,
    trigger_pipeline,
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
# データの読み込み（キャッシュ済み / Gold）
# =============================================================================

header_df = load_surgery_summary()
drug_items_df = load_drug_items()
anesthesia_times_df = load_anesthesia_times()
exam_items_df = load_exam_items()


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


@st.cache_data
def _load_orbit_workbook_from_export(filename: str = "ORBIT_算定シート.xlsx"):
    """
    Lakehouse Files/export 配下の算定シートを読み込み、全シートDataFrameを返す。
    """
    file_bytes = download_file_from_onelake(filename=filename, subfolder="", folder="export")
    if file_bytes is None:
        return None, {}

    try:
        sheets = pd.read_excel(BytesIO(file_bytes), sheet_name=None, engine="openpyxl")
        return file_bytes, sheets
    except Exception:
        return file_bytes, {}


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
                if not is_fabric_available():
                    st.error("Fabric環境変数が未設定です。")
                    st.stop()
                with st.status("アップロード中...", expanded=True) as status:
                    try:
                        for f, subfolder in all_uploaded:
                            data = f.getvalue()
                            upload_file_to_onelake(data, f.name, subfolder)
                            st.write(f"✅ OneLakeへアップロード: raw/{subfolder}/{f.name}（{len(data):,} bytes）")
                        status.update(label="アップロード完了", state="complete")
                    except Exception as e:
                        status.update(label="アップロード失敗", state="error")
                        st.error(f"アップロードに失敗しました: {e}")
                        st.stop()
                st.success("アップロード完了")

    st.divider()

    # --- パイプライン実行 ---
    if st.button("▶ パイプライン実行", use_container_width=True, type="primary"):
        if not is_fabric_available():
            st.error("Fabric環境変数が未設定です。")
        else:
            with st.status("パイプラインを実行中...", expanded=True) as status:
                try:
                    pipeline_id = os.environ.get("FABRIC_PIPELINE_ID", "").strip()
                    if pipeline_id:
                        st.write("▶ Fabric Pipeline を開始...")
                        loc = trigger_pipeline(pipeline_id)
                        wait_for_job(loc)
                        st.write("✅ Fabric Pipeline 完了")
                        status.update(label="パイプライン完了", state="complete")
                        st.session_state["pipeline_status"] = "done"
                        st.cache_data.clear()
                        st.rerun()

                    steps = [
                        ("NOTEBOOK_YAKUZAI_ID", "使用薬剤Notebook", trigger_notebook),
                        ("NOTEBOOK_MASUI_KENSA_ID", "麻酔検査Notebook", trigger_notebook),
                        ("NOTEBOOK_CSV_IMPORT_ID", "CSV取り込みNotebook", trigger_notebook),
                        ("DATAFLOW_ID", "Dataflow Gen2", trigger_dataflow),
                    ]
                    for env_key, label, trigger_fn in steps:
                        item_id = os.environ.get(env_key, "")
                        if not item_id:
                            st.write(f"⏭️ {label} — スキップ（{env_key} 未設定）")
                            continue
                        st.write(f"▶ {label} を開始...")
                        try:
                            loc = trigger_fn(item_id)
                            wait_for_job(loc)
                            st.write(f"✅ {label} 完了")
                        except Exception as step_error:
                            msg = str(step_error)
                            # Notebook をサービスプリンシパルで呼んだときの既知制約:
                            # UserAccessTokenException はUI手動実行で代替可能なため、全体は継続する
                            if (
                                trigger_fn is trigger_notebook
                                and (
                                    "UserAccessTokenException" in msg
                                    or "unable to acquire user token" in msg
                                )
                            ):
                                st.warning(
                                    f"⚠️ {label} はAPI実行をスキップしました（ユーザートークン要件）。"
                                    "Fabric UIでの手動実行結果を利用して続行します。"
                                )
                                continue
                            raise

                    status.update(label="パイプライン完了", state="complete")
                    st.session_state["pipeline_status"] = "done"
                    st.cache_data.clear()
                except Exception as e:
                    status.update(label="パイプライン失敗", state="error")
                    st.session_state["pipeline_status"] = "error"
                    st.error(f"パイプラインエラー: {e}")
                    st.stop()
            st.rerun()

    # パイプラインステータス表示
    pipeline_st = st.session_state.get("pipeline_status", "idle")
    if pipeline_st == "done":
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
        for row_idx, (_, row) in enumerate(header_df.iterrows()):
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
                    label, key=f"pt_{row_idx}_{pid}_{date}",
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
    anesthesia_times_df=anesthesia_times_df,
    exam_items_df=exam_items_df,
    drug_items_df=drug_items_df,
)


# =============================================================================
# ORBIT算定シート（Excel）全内容表示
# =============================================================================
with st.expander("📘 ORBIT_算定シート.xlsx（Files/export）全内容", expanded=True):
    wb_bytes, wb_sheets = _load_orbit_workbook_from_export()

    if wb_bytes is None:
        st.error("`Files/export/ORBIT_算定シート.xlsx` を取得できませんでした。")
    elif not wb_sheets:
        st.error("Excelは取得できましたが、シートの読み込みに失敗しました。")
    else:
        st.caption(f"シート数: {len(wb_sheets)}")
        for sheet_name, sheet_df in wb_sheets.items():
            st.markdown(f"### {sheet_name}")
            st.caption(f"{len(sheet_df)}行 × {len(sheet_df.columns)}列")
            st.dataframe(sheet_df, width="stretch", height=420)
