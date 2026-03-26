"""
app.py — ORBIT（手術算定支援システム）メインアプリ

サイドバーでページを切り替え、各画面を表示する。
データ読み込み → ルール適用 → 画面描画 の流れで動作する。
"""

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

# --- 画面モジュール ---
from views.page_patient_list import render_patient_list
from views.page_detail import render_detail
from views.page_output import render_output
from views.page_upload import render_upload
from views.page_source_viewer import render_source_viewer


# =============================================================================
# ページ設定
# =============================================================================

st.set_page_config(
    page_title="ORBIT - 手術算定支援",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# CSSスタイリング
# =============================================================================

st.markdown("""
<style>
    /* ヘッダーのグラデーション */
    .stApp > header {
        background: linear-gradient(90deg, #1a5276, #2e86c1);
    }

    /* サイドバーのスタイル */
    [data-testid="stSidebar"] {
        background-color: #f8f9fa;
    }

    /* テーブルのスタイル */
    .stDataFrame {
        font-size: 14px;
    }

    /* 算定明細: st.html のホバーパネルが列の overflow で切れにくくする */
    [data-testid="column"] {
        overflow: visible !important;
    }

</style>
""", unsafe_allow_html=True)


# =============================================================================
# データの読み込み（キャッシュ済み）
# =============================================================================

# サイドバーにデータ再読み込みボタン
with st.sidebar:
    if st.button("🔄 データ再読み込み"):
        st.cache_data.clear()
        for k in list(st.session_state.keys()):
            if k.startswith("box2_") or k.startswith("version_"):
                del st.session_state[k]
        st.rerun()

# Fabricからデータを読み込む
header_df = load_header()
masui_time_df = load_masui_time()
kensa_df = load_kensa()
drugs_df = load_drugs()

star_items_df = load_star_items()
kiji_df = load_kiji()

# マスターデータの読み込み
seishoku_master = load_seishoku_master()
aline_master = load_aline_master()  # Aラインは保留（マスター保持のみ）


# =============================================================================
# 算定ルールの適用
# =============================================================================

# 麻酔時間の合算
masui_processed = apply_masui_rules(masui_time_df)

# 検査データの整形
kensa_processed = apply_kensa_rules(kensa_df)

# 薬剤データの変換（生食コード変換含む）
drugs_processed = apply_drug_rules(drugs_df, seishoku_master)

# ナビ判定（ヘッダー + 臨工記事）
navi_result = apply_navi_rules(header_df, kiji_df)




# =============================================================================
# サイドバー（ページ切り替え）
# =============================================================================

st.sidebar.title("🏥 ORBIT")
st.sidebar.caption("手術算定支援システム（プロトタイプ）")

# ページ選択（session_stateで管理）
page_options = ["アップロード", "患者一覧", "算定明細", "データ出力"]

# 現在のページを取得（デフォルトは「患者一覧」）
current_page = st.session_state.get("current_page", "患者一覧")

# サイドバーのラジオボタンでページ選択
selected_page = st.sidebar.radio(
    "メニュー",
    page_options,
    index=page_options.index(current_page) if current_page in page_options else 0,
)

# ページ遷移を反映
if selected_page != current_page:
    st.session_state["current_page"] = selected_page
    current_page = selected_page

# サイドバーに患者数サマリーを表示
st.sidebar.divider()
st.sidebar.metric("登録患者数", len(header_df))


# =============================================================================
# ページルーティング
# =============================================================================

# 元データ確認ページ（新タブで開かれた場合）
query_params = st.query_params
if query_params.get("page") == "source_viewer":
    render_source_viewer()
    st.stop()

if current_page == "患者一覧":
    # 画面1: 患者一覧
    render_patient_list(header_df, navi_df=navi_result)

elif current_page == "算定明細":
    # 画面2: 算定明細（編集・保存・確定）
    render_detail(
        header_df,
        masui_processed,
        kensa_processed,
        drugs_processed,
        star_items_df=star_items_df,
        navi_df=navi_result,
        masui_time_raw_df=masui_time_df,
    )

elif current_page == "データ出力":
    # 画面3: コピペ用出力・ダウンロード
    render_output(
        header_df,
        masui_processed,
        kensa_processed,
        drugs_processed,
        star_items_df=star_items_df,
        navi_df=navi_result,
    )

elif current_page == "アップロード":
    render_upload()
