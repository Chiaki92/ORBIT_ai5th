"""
ORBIT（オービット）- 手術コスト算定支援システム プロトタイプ
==========================================================
事務スタッフ向けのデモ用プロトタイプアプリです。
実際のテストデータ（CSV）を使って、以下のワークフローを体験できます：
  1. 患者一覧・ステータス確認
  2. 患者ごとの算定明細の確認・編集
  3. 確定データの出力（CSV/Excel）

起動方法:
  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import os
import io
import json
import time
from datetime import datetime
from pathlib import Path


# ============================================================
# 変更履歴の永続化（JSONファイルに保存）
# ============================================================
# アプリと同じフォルダに state.json を作り、変更履歴とステータスを保存する。
# ブラウザを閉じても・Streamlitを再起動しても、データが残る。
# 本番では Fabric の Gold層テーブルへの書き戻しに置き換わる。

STATE_FILE = Path(os.path.dirname(__file__)) / "state.json"


def load_persisted_state():
    """
    state.json が存在すれば読み込み、なければ空の状態を返す。
    """
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # ファイルが壊れていたら空で始める
            return {}
    return {}


def save_persisted_state(patient_statuses, change_log, upload_history, data_edits=None):
    """
    現在の状態を state.json に書き出す。
    """
    data = {
        "patient_statuses": patient_statuses,
        "change_log": change_log,
        "upload_history": upload_history,
        "data_edits": data_edits or {},
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_change_log(action, detail, patient_id="", patient_name="",
                   surgery_name="", department="", tab="",
                   item_name="", code="", changed_column="",
                   old_value="", new_value=""):
    """
    変更履歴に1件追加して、state.json にも保存する。
    action: 操作の種類（例: '確定', '確定取消', 'セル編集', 'PDFアップロード'）
    detail: 具体的な内容（例: '請求量 1→2 に変更'）
    セル編集時のみ追加項目（術式〜変更後）に値が入る。それ以外は空文字。
    """
    entry = {
        "日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "患者ID": patient_id,
        "患者氏名": patient_name,
        "操作": action,
        "詳細": detail,
        "術式": surgery_name,
        "診療科": department,
        "タブ": tab,
        "項目名": item_name,
        "コード": code,
        "変更列": changed_column,
        "変更前": old_value,
        "変更後": new_value,
    }
    st.session_state.change_log.append(entry)
    # JSON に永続保存
    save_persisted_state(
        st.session_state.patient_statuses,
        st.session_state.change_log,
        st.session_state.upload_history,
        st.session_state.get("data_edits", {}),
    )


def detect_and_log_edits(before_df, after_df, patient_id, patient_name,
                         surgery_name, department, tab,
                         item_name_col, code_col):
    """
    編集前と編集後のDataFrameを比較し、差分をchange_logに記録する。
    """
    for row_idx in range(len(before_df)):
        for col in before_df.columns:
            old_val = str(before_df.iloc[row_idx][col])
            new_val = str(after_df.iloc[row_idx][col])

            if old_val != new_val:
                item_name = str(before_df.iloc[row_idx][item_name_col])
                code_val = str(before_df.iloc[row_idx][code_col])

                add_change_log(
                    action="セル編集",
                    detail=f"{col} {old_val}→{new_val}",
                    patient_id=patient_id,
                    patient_name=patient_name,
                    surgery_name=surgery_name,
                    department=department,
                    tab=tab,
                    item_name=item_name,
                    code=code_val,
                    changed_column=col,
                    old_value=old_val,
                    new_value=new_val,
                )

# ============================================================
# ページの基本設定
# ============================================================
st.set_page_config(
    page_title="ORBIT - 手術コスト算定支援",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# カスタムCSS: 見た目を整える
# ============================================================
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
    }
    .main-header h1 { color: white; margin: 0; font-size: 1.6rem; }
    .main-header p { color: #b0c8e8; margin: 0.3rem 0 0 0; font-size: 0.9rem; }
    section[data-testid="stSidebar"] { background-color: #f0f4f8; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# データ読み込み関数
# ============================================================
@st.cache_data  # データをキャッシュして高速化
def load_data():
    """
    CSVファイルを読み込んで、各テーブルをDataFrameとして返す。
    dataフォルダからCSVを読み込む（本番ではFabricのDeltaテーブルから読む想定）。
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data")

    # --- 麻酔・検査レポート系 ---
    header = pd.read_csv(os.path.join(data_dir, "masui_kensa_header.csv"), encoding="utf-8-sig")
    masui_time = pd.read_csv(os.path.join(data_dir, "masui_kensa_masui_time.csv"), encoding="utf-8-sig")
    kensa = pd.read_csv(os.path.join(data_dir, "masui_kensa_kensa.csv"), encoding="utf-8-sig")
    keika = pd.read_csv(os.path.join(data_dir, "masui_kensa_keika.csv"), encoding="utf-8-sig")

    # --- 使用薬剤レポート系 ---
    yakuzai_header = pd.read_csv(os.path.join(data_dir, "yakuzai_header.csv"), encoding="utf-8-sig")
    drugs = pd.read_csv(os.path.join(data_dir, "yakuzai_drugs.csv"), encoding="utf-8-sig")

    return header, masui_time, kensa, keika, yakuzai_header, drugs


def normalize_surgery_date(date_str):
    """
    手術日のフォーマットを統一する。
    麻酔・検査系: '2026/01/01(木)' → '2026/01/01'
    薬剤系: '2026/01/01' → そのまま
    """
    if pd.isna(date_str):
        return date_str
    return str(date_str).split("(")[0].strip()


# ============================================================
# セッションステート初期化
# （Streamlitは毎回スクリプトが再実行されるので、状態はここで保持する）
# （初回起動時に state.json から復元し、以後はセッション内で保持する）
# ============================================================
if "initialized" not in st.session_state:
    # --- 初回のみ: state.json から復元を試みる ---
    persisted = load_persisted_state()

    st.session_state.patient_statuses = persisted.get("patient_statuses", {})
    st.session_state.change_log = persisted.get("change_log", [])
    st.session_state.upload_history = persisted.get("upload_history", [])
    st.session_state.data_edits = persisted.get("data_edits", {})
    st.session_state.selected_patient = None
    st.session_state.initialized = True  # 初期化済みフラグ

# data_edits が未初期化の場合（旧バージョンの state.json からの移行時）
if "data_edits" not in st.session_state:
    st.session_state.data_edits = {}

# ============================================================
# データの読み込みと前処理
# ============================================================
header, masui_time, kensa, keika, yakuzai_header, drugs = load_data()

# --- 手術日を統一フォーマットに変換 ---
header["手術日_正規化"] = header["手術日"].apply(normalize_surgery_date)
masui_time["手術日_正規化"] = masui_time["手術日"].apply(normalize_surgery_date)
kensa["手術日_正規化"] = kensa["手術日"].apply(normalize_surgery_date)
keika["手術日_正規化"] = keika["手術日"].apply(normalize_surgery_date)
drugs["手術日_正規化"] = drugs["手術日"].astype(str).str.strip()
yakuzai_header["手術日_正規化"] = yakuzai_header["手術日"].astype(str).str.strip()

# --- 患者IDを文字列に統一（ゼロ埋め8桁） ---
for df in [header, masui_time, kensa, keika, drugs, yakuzai_header]:
    df["患者ID_正規化"] = df["患者ID"].astype(str).str.zfill(8)

# --- state.json にデータがなかった場合のみ: CSVの患者で初期化 ---
if not st.session_state.patient_statuses:
    for _, row in header.iterrows():
        pid = row["患者ID_正規化"]
        st.session_state.patient_statuses[pid] = "確認待ち"
    # 初期状態も保存しておく
    save_persisted_state(
        st.session_state.patient_statuses,
        st.session_state.change_log,
        st.session_state.upload_history,
        st.session_state.get("data_edits", {}),
    )


# ============================================================
# サイドバー: ナビゲーション
# ============================================================
with st.sidebar:
    st.markdown("### 🏥 ORBIT")
    st.markdown("手術コスト算定支援システム")
    st.markdown("---")

    # ページ選択
    page = st.radio(
        "メニュー",
        ["📂 PDFアップロード", "📋 患者一覧", "📊 算定明細", "📤 データ出力", "🕐 変更履歴"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    # ステータスの集計
    statuses = list(st.session_state.patient_statuses.values())
    st.markdown("#### ステータス集計")
    st.markdown(f"🟡 確認待ち: **{statuses.count('確認待ち')}件**")
    st.markdown(f"🟢 確定済み: **{statuses.count('確定済み')}件**")

    # アップロード件数
    upload_count = len(st.session_state.upload_history)
    if upload_count > 0:
        st.markdown(f"📂 アップロード済み: **{upload_count}件**")

    # 変更履歴件数
    log_count = len(st.session_state.change_log)
    if log_count > 0:
        st.markdown(f"🕐 変更履歴: **{log_count}件**")

    st.markdown("---")
    st.caption("プロトタイプ v0.1")
    st.caption(f"データ: テスト患者 {len(header)}名")


# ============================================================
# ページ0: PDFアップロード（方針B: Fabricへの送信シミュレーション）
# ============================================================
if page == "📂 PDFアップロード":

    st.markdown("""
    <div class="main-header">
        <h1>📂 PDFアップロード</h1>
        <p>手術部門システムから出力されたPDFをアップロードします。
           アップロードされたPDFは Fabric Lakehouse に送信され、自動で解析処理が実行されます。</p>
    </div>
    """, unsafe_allow_html=True)

    # --- 対応PDFの種類を説明 ---
    st.markdown("#### アップロード対象のPDF")
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.info("""
        **📄 使用薬剤レポート**
        - ファイル名例: `02使用薬剤レポート_01_耳鼻ロング.pdf`
        - 内容: 薬剤の一覧（カテゴリ・投与量・請求量）
        - 患者基本情報（氏名・ID・術式等）も含む
        """)
    with col_info2:
        st.info("""
        **📄 麻酔・検査レポート**
        - ファイル名例: `03麻酔検査レポート_01_耳鼻ロング.pdf`
        - 内容: 麻酔時間・検査項目・経過記録
        - 麻酔コード・検査コードも含む
        """)

    st.markdown("---")

    # --- アップロードエリア ---
    st.markdown("#### PDFファイルをアップロード")
    uploaded_files = st.file_uploader(
        "PDFファイルをドラッグ＆ドロップ、またはクリックして選択",
        type=["pdf"],
        accept_multiple_files=True,  # 複数ファイルOK
        help="使用薬剤レポートまたは麻酔・検査レポートのPDFを選択してください",
        key="pdf_uploader",
    )

    # --- アップロードされたファイルの処理 ---
    if uploaded_files:
        st.markdown("---")
        st.markdown(f"#### アップロードされたファイル（{len(uploaded_files)}件）")

        for uploaded_file in uploaded_files:
            fname = uploaded_file.name
            file_size_kb = len(uploaded_file.getvalue()) / 1024

            # ファイル名からレポート種別を自動判定
            if "薬剤" in fname or "yakuzai" in fname.lower():
                report_type = "使用薬剤レポート"
                report_icon = "💊"
            elif "麻酔" in fname or "検査" in fname or "masui" in fname.lower():
                report_type = "麻酔・検査レポート"
                report_icon = "💉"
            else:
                report_type = "種別不明"
                report_icon = "📄"

            # --- ファイルごとの表示 ---
            with st.expander(f"{report_icon} {fname}（{file_size_kb:.1f} KB）— {report_type}", expanded=True):

                # ファイル情報
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    st.markdown(f"**ファイル名**: {fname}")
                with col_f2:
                    st.markdown(f"**サイズ**: {file_size_kb:.1f} KB")
                with col_f3:
                    st.markdown(f"**種別**: {report_type}")

                # 「Fabricに送信」ボタン
                # すでにアップロード済みかチェック
                already_uploaded = fname in [h["ファイル名"] for h in st.session_state.upload_history]

                if already_uploaded:
                    st.success("✅ アップロード済み — Fabric で処理完了")
                else:
                    if st.button(f"📤 Fabric に送信する", key=f"send_{fname}", use_container_width=True):

                        # ---- 送信→処理のシミュレーション ----
                        # 実際は OneLake API or OneDrive → Power Automate でFabricに転送される
                        progress = st.progress(0, text="Fabric Lakehouse に送信中...")
                        time.sleep(0.5)
                        progress.progress(30, text="raw フォルダに保存完了")
                        time.sleep(0.5)
                        progress.progress(50, text="Notebook トリガー実行中（Bronze層: PDF解析）...")
                        time.sleep(0.7)
                        progress.progress(70, text="Silver層: データ構造化・テーブル結合...")
                        time.sleep(0.5)
                        progress.progress(90, text="Gold層: 算定ルール適用中...")
                        time.sleep(0.5)
                        progress.progress(100, text="✅ 処理完了 → ステータス: 確認待ち")

                        # アップロード履歴に記録
                        st.session_state.upload_history.append({
                            "ファイル名": fname,
                            "種別": report_type,
                            "サイズ": f"{file_size_kb:.1f} KB",
                            "送信日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "ステータス": "処理完了",
                        })

                        # 変更履歴にも記録
                        add_change_log(
                            action="PDFアップロード",
                            detail=f"{fname}（{report_type}, {file_size_kb:.1f}KB）を Fabric に送信",
                        )

                        st.success(f"🎉 **{fname}** の処理が完了しました。「📋 患者一覧」で確認できます。")
                        st.rerun()  # 画面更新して「アップロード済み」表示に切り替え

    # --- アップロード履歴テーブル ---
    st.markdown("---")
    st.markdown("#### 📜 アップロード履歴")

    if st.session_state.upload_history:
        df_upload = pd.DataFrame(st.session_state.upload_history)
        st.dataframe(df_upload, use_container_width=True, hide_index=True)
    else:
        st.caption("まだアップロードされたファイルはありません")

    # --- 本番との違い ---
    with st.expander("ℹ️ プロトタイプと本番環境の違い", expanded=False):
        st.markdown("""
        | 項目 | プロトタイプ（今の画面） | 本番環境 |
        |------|------------------------|----------|
        | **PDF保存先** | ローカルPC | Fabric Lakehouse（raw フォルダ） |
        | **送信方法** | ボタンクリックでシミュレーション | OneLake API or OneDrive + Power Automate |
        | **解析処理** | ステータス表示のみ | Fabric Notebook が実際に pdfplumber で解析 |
        | **処理結果** | 既存テストデータを表示 | アップロードしたPDFから抽出したデータを表示 |
        | **認証** | なし | Azure AD（病院職員のみ） |
        """)


# ============================================================
# ページ1: 患者一覧
# ============================================================
elif page == "📋 患者一覧":

    st.markdown("""
    <div class="main-header">
        <h1>📋 患者一覧・ステータス管理</h1>
        <p>手術患者のコスト算定状況を一覧で確認できます</p>
    </div>
    """, unsafe_allow_html=True)

    # --- サマリーカード ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("総患者数", f"{len(header)}名")
    with col2:
        st.metric("確認待ち", f"{statuses.count('確認待ち')}件")
    with col3:
        st.metric("確定済み", f"{statuses.count('確定済み')}件")
    with col4:
        st.metric("薬剤レコード", f"{len(drugs)}件")

    st.markdown("---")

    # --- フィルター ---
    status_filter = st.selectbox(
        "ステータス絞り込み",
        ["すべて", "確認待ち", "確定済み"],
    )

    # --- 患者一覧テーブルを作成 ---
    patient_list = []
    for _, row in header.iterrows():
        pid = row["患者ID_正規化"]
        status = st.session_state.patient_statuses.get(pid, "確認待ち")

        # 各患者の件数を集計
        drug_count = len(drugs[drugs["患者ID_正規化"] == pid])
        kensa_count = len(kensa[kensa["患者ID_正規化"] == pid])
        masui_count = len(masui_time[
            (masui_time["患者ID_正規化"] == pid) & (masui_time["コード"].notna())
        ])

        patient_list.append({
            "患者ID": pid,
            "患者氏名": row["患者氏名"],
            "手術日": row["手術日_正規化"],
            "診療科": str(row["診療科"]).replace("\n", "・"),
            "確定術式": row["確定術式"],
            "区分": row["予定区分"],
            "麻酔": masui_count,
            "検査": kensa_count,
            "薬剤": drug_count,
            "ステータス": status,
        })

    df_patients = pd.DataFrame(patient_list)

    # フィルター適用
    if status_filter != "すべて":
        df_patients = df_patients[df_patients["ステータス"] == status_filter]

    # テーブル表示
    st.dataframe(
        df_patients,
        use_container_width=True,
        hide_index=True,
        height=280,
    )

    # --- 患者選択 → 明細画面へ ---
    st.markdown("---")
    st.markdown("#### 算定明細を確認する患者を選択")

    patient_options = {
        f"{row['患者氏名']}（{row['患者ID']}）- {row['確定術式'][:20]}": row["患者ID"]
        for _, row in df_patients.iterrows()
    }

    if patient_options:
        selected_label = st.selectbox("患者を選択", list(patient_options.keys()))
        selected_pid = patient_options[selected_label]

        if st.button("🔍 算定明細を表示", type="primary", use_container_width=True):
            st.session_state.selected_patient = selected_pid
            st.info("💡 左メニューの「📊 算定明細」を選択してください")


# ============================================================
# ページ2: 算定明細
# ============================================================
elif page == "📊 算定明細":

    st.markdown("""
    <div class="main-header">
        <h1>📊 算定明細</h1>
        <p>患者ごとのコスト算定結果を確認・編集できます。内容を確認して「確定」ボタンを押してください。</p>
    </div>
    """, unsafe_allow_html=True)

    # --- 患者選択 ---
    patient_options_detail = {}
    for _, row in header.iterrows():
        pid = row["患者ID_正規化"]
        status = st.session_state.patient_statuses.get(pid, "確認待ち")
        label = f"{row['患者氏名']}（{pid}）[{status}]"
        patient_options_detail[label] = pid

    # セッションに保存された患者を初期値にする
    default_idx = 0
    if st.session_state.selected_patient:
        for i, (label, pid) in enumerate(patient_options_detail.items()):
            if pid == st.session_state.selected_patient:
                default_idx = i
                break

    selected_label = st.selectbox("患者を選択", list(patient_options_detail.keys()), index=default_idx)
    current_pid = patient_options_detail[selected_label]
    st.session_state.selected_patient = current_pid

    # --- 患者基本情報 ---
    patient_header = header[header["患者ID_正規化"] == current_pid].iloc[0]

    st.markdown("#### 📋 患者基本情報")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"**患者ID**: {current_pid}")
        st.markdown(f"**氏名**: {patient_header['患者氏名']}")
    with col2:
        st.markdown(f"**手術日**: {patient_header['手術日_正規化']}")
        st.markdown(f"**診療科**: {str(patient_header['診療科']).replace(chr(10), '・')}")
    with col3:
        st.markdown(f"**術式**: {patient_header['確定術式']}")
        st.markdown(f"**区分**: {patient_header['予定区分']} / {patient_header['入院外来']}")
    with col4:
        st.markdown(f"**年齢**: {patient_header['年齢']}歳 / {patient_header['性別']}")
        st.markdown(f"**手術時間**: {patient_header['手術時間_合計']}")

    # ステータス表示
    current_status = st.session_state.patient_statuses.get(current_pid, "確認待ち")
    if current_status == "確認待ち":
        st.warning(f"⚠️ ステータス: {current_status}")
    elif current_status == "確定済み":
        st.success(f"✅ ステータス: {current_status}")

    st.markdown("---")

    # --- タブで切り替え ---
    tab1, tab2, tab3, tab4 = st.tabs([
        "💉 麻酔時間・コード",
        "🔬 検査項目",
        "💊 使用薬剤",
        "📜 経過記録",
    ])

    # タブ1: 麻酔時間
    with tab1:
        st.markdown("##### 麻酔時間・算定コード")
        patient_masui = masui_time[masui_time["患者ID_正規化"] == current_pid].copy()

        if len(patient_masui) > 0:
            display_masui = patient_masui[["名称", "コード", "開始", "終了", "合計"]].copy().reset_index(drop=True)
            display_masui["コード"] = display_masui["コード"].apply(
                lambda x: str(int(x)) if pd.notna(x) else "（なし）"
            )
            display_masui["算定対象"] = display_masui["コード"].apply(
                lambda x: "✅ 対象" if x != "（なし）" else "❌ 対象外"
            )

            # 保存済み編集があればそれを使う
            edits_key_masui = f"{current_pid}_masui"
            if edits_key_masui in st.session_state.data_edits:
                base_masui = pd.DataFrame(st.session_state.data_edits[edits_key_masui])
            else:
                base_masui = display_masui.copy()

            edited_masui = st.data_editor(
                base_masui, use_container_width=True, hide_index=True,
                num_rows="fixed", key=f"masui_{current_pid}",
            )

            # 未保存の変更があれば保存ボタンを表示
            widget_state_masui = st.session_state.get(f"masui_{current_pid}", {})
            if widget_state_masui.get("edited_rows"):
                if st.button("💾 麻酔データの変更を保存", key=f"save_masui_{current_pid}"):
                    detect_and_log_edits(
                        before_df=base_masui,
                        after_df=edited_masui,
                        patient_id=current_pid,
                        patient_name=patient_header["患者氏名"],
                        surgery_name=patient_header["確定術式"],
                        department=str(patient_header["診療科"]).replace("\n", "・"),
                        tab="麻酔",
                        item_name_col="名称",
                        code_col="コード",
                    )
                    st.session_state.data_edits[edits_key_masui] = edited_masui.to_dict("records")
                    save_persisted_state(
                        st.session_state.patient_statuses,
                        st.session_state.change_log,
                        st.session_state.upload_history,
                        st.session_state.data_edits,
                    )
                    del st.session_state[f"masui_{current_pid}"]
                    st.success("麻酔データの変更を保存しました")
                    st.rerun()

            valid_masui = patient_masui[patient_masui["コード"].notna()]
            st.caption(f"算定対象: {len(valid_masui)}件 / 全{len(patient_masui)}件")
        else:
            st.info("麻酔時間データがありません")

    # タブ2: 検査項目
    with tab2:
        st.markdown("##### 検査項目一覧")
        patient_kensa = kensa[kensa["患者ID_正規化"] == current_pid].copy()

        if len(patient_kensa) > 0:
            display_kensa = patient_kensa[["名称", "コード", "回数", "単位"]].copy().reset_index(drop=True)
            display_kensa["コード"] = display_kensa["コード"].astype(str)
            display_kensa["回数"] = display_kensa["回数"].apply(
                lambda x: f"{int(x)}回" if pd.notna(x) else "—"
            )

            # 保存済み編集があればそれを使う
            edits_key_kensa = f"{current_pid}_kensa"
            if edits_key_kensa in st.session_state.data_edits:
                base_kensa = pd.DataFrame(st.session_state.data_edits[edits_key_kensa])
            else:
                base_kensa = display_kensa.copy()

            edited_kensa = st.data_editor(
                base_kensa, use_container_width=True, hide_index=True,
                num_rows="fixed", key=f"kensa_{current_pid}",
            )

            # 未保存の変更があれば保存ボタンを表示
            widget_state_kensa = st.session_state.get(f"kensa_{current_pid}", {})
            if widget_state_kensa.get("edited_rows"):
                if st.button("💾 検査データの変更を保存", key=f"save_kensa_{current_pid}"):
                    detect_and_log_edits(
                        before_df=base_kensa,
                        after_df=edited_kensa,
                        patient_id=current_pid,
                        patient_name=patient_header["患者氏名"],
                        surgery_name=patient_header["確定術式"],
                        department=str(patient_header["診療科"]).replace("\n", "・"),
                        tab="検査",
                        item_name_col="名称",
                        code_col="コード",
                    )
                    st.session_state.data_edits[edits_key_kensa] = edited_kensa.to_dict("records")
                    save_persisted_state(
                        st.session_state.patient_statuses,
                        st.session_state.change_log,
                        st.session_state.upload_history,
                        st.session_state.data_edits,
                    )
                    del st.session_state[f"kensa_{current_pid}"]
                    st.success("検査データの変更を保存しました")
                    st.rerun()

            st.caption(f"検査項目: {len(patient_kensa)}件")
        else:
            st.info("検査データがありません")

    # タブ3: 使用薬剤
    with tab3:
        st.markdown("##### 使用薬剤一覧")
        patient_drugs = drugs[drugs["患者ID_正規化"] == current_pid].copy()

        if len(patient_drugs) > 0:
            display_drugs = patient_drugs[[
                "カテゴリ", "名称", "医事コード", "請求量", "請求単位"
            ]].copy().reset_index(drop=True)

            # 保存済み編集があればそれを使う
            edits_key_drugs = f"{current_pid}_drugs"
            if edits_key_drugs in st.session_state.data_edits:
                base_drugs = pd.DataFrame(st.session_state.data_edits[edits_key_drugs])
            else:
                base_drugs = display_drugs.copy()

            edited_drugs = st.data_editor(
                base_drugs, use_container_width=True, hide_index=True,
                num_rows="fixed", key=f"drugs_{current_pid}",
            )

            # 未保存の変更があれば保存ボタンを表示
            widget_state_drugs = st.session_state.get(f"drugs_{current_pid}", {})
            if widget_state_drugs.get("edited_rows"):
                if st.button("💾 薬剤データの変更を保存", key=f"save_drugs_{current_pid}"):
                    detect_and_log_edits(
                        before_df=base_drugs,
                        after_df=edited_drugs,
                        patient_id=current_pid,
                        patient_name=patient_header["患者氏名"],
                        surgery_name=patient_header["確定術式"],
                        department=str(patient_header["診療科"]).replace("\n", "・"),
                        tab="薬剤",
                        item_name_col="名称",
                        code_col="医事コード",
                    )
                    st.session_state.data_edits[edits_key_drugs] = edited_drugs.to_dict("records")
                    save_persisted_state(
                        st.session_state.patient_statuses,
                        st.session_state.change_log,
                        st.session_state.upload_history,
                        st.session_state.data_edits,
                    )
                    del st.session_state[f"drugs_{current_pid}"]
                    st.success("薬剤データの変更を保存しました")
                    st.rerun()

            # カテゴリ別集計
            cat_summary = patient_drugs.groupby("カテゴリ").size()
            st.caption(f"薬剤項目: {len(patient_drugs)}件（{', '.join(f'{k}:{v}' for k, v in cat_summary.items())}）")
        else:
            st.info("薬剤データがありません")

    # タブ4: 経過記録（参考）
    with tab4:
        st.markdown("##### 経過記録（参考情報）")
        patient_keika = keika[keika["患者ID_正規化"] == current_pid].copy()

        if len(patient_keika) > 0:
            st.dataframe(
                patient_keika[["時刻", "イベント"]],
                use_container_width=True, hide_index=True, height=400,
            )
            st.caption(f"イベント数: {len(patient_keika)}件")
        else:
            st.info("経過記録がありません")

    # --- 確定・取消ボタン ---
    st.markdown("---")
    col_btn1, col_btn2, _ = st.columns([2, 1, 1])

    with col_btn1:
        if current_status != "確定済み":
            if st.button("✅ この患者のコスト算定を確定する", type="primary", use_container_width=True):
                st.session_state.patient_statuses[current_pid] = "確定済み"
                add_change_log(
                    action="確定",
                    detail="コスト算定を確定",
                    patient_id=current_pid,
                    patient_name=patient_header["患者氏名"],
                )
                st.success(f"✅ {patient_header['患者氏名']}さんのコスト算定を確定しました")
                st.rerun()
        else:
            st.success("✅ この患者は確定済みです")

    with col_btn2:
        if current_status == "確定済み":
            if st.button("🔄 確定を取り消す", use_container_width=True):
                st.session_state.patient_statuses[current_pid] = "確認待ち"
                add_change_log(
                    action="確定取消",
                    detail="確定を取り消し → 確認待ちに戻す",
                    patient_id=current_pid,
                    patient_name=patient_header["患者氏名"],
                )
                st.rerun()

    # --- この患者の変更履歴 ---
    patient_logs = [
        e for e in st.session_state.change_log if e["患者ID"] == current_pid
    ]
    if patient_logs:
        st.markdown("---")
        st.markdown(f"#### 🕐 この患者の変更履歴（{len(patient_logs)}件）")
        st.dataframe(
            pd.DataFrame(reversed(patient_logs)),
            use_container_width=True, hide_index=True, height=200,
            column_config={
                "日時": st.column_config.TextColumn("日時", width="medium"),
                "操作": st.column_config.TextColumn("操作", width="small"),
                "詳細": st.column_config.TextColumn("詳細", width="large"),
                "患者ID": None,  # 同じ患者なので非表示
                "患者氏名": None,
            },
        )

    # --- この患者のデータ修正をリセット ---
    has_edits = any(
        k.startswith(f"{current_pid}_") for k in st.session_state.data_edits
    )
    if has_edits:
        st.markdown("---")
        with st.expander("⚠️ この患者のデータ修正をリセット", expanded=False):
            st.markdown("保存した編集内容をすべて取り消し、元のCSVデータに戻します。ステータス（確定/確認待ち）は変更されません。")
            if st.button("🔄 編集内容をリセット", key=f"reset_{current_pid}", use_container_width=True):
                # この患者の編集データを削除
                keys_to_remove = [
                    k for k in st.session_state.data_edits
                    if k.startswith(f"{current_pid}_")
                ]
                for k in keys_to_remove:
                    del st.session_state.data_edits[k]
                # data_editor のウィジェット状態もクリア
                for suffix in ["masui", "kensa", "drugs"]:
                    wkey = f"{suffix}_{current_pid}"
                    if wkey in st.session_state:
                        del st.session_state[wkey]
                add_change_log(
                    action="編集リセット",
                    detail="データ修正をリセット（元のCSVデータに戻す）",
                    patient_id=current_pid,
                    patient_name=patient_header["患者氏名"],
                )
                st.success(f"{patient_header['患者氏名']}さんの編集内容をリセットしました")
                st.rerun()


# ============================================================
# ページ3: データ出力
# ============================================================
elif page == "📤 データ出力":

    st.markdown("""
    <div class="main-header">
        <h1>📤 データ出力</h1>
        <p>確定済みの算定データをCSVまたはExcel形式で出力します。既存コストシステムへ貼り付けて使用できます。</p>
    </div>
    """, unsafe_allow_html=True)

    # --- 確定済み患者 ---
    confirmed_pids = [
        pid for pid, status in st.session_state.patient_statuses.items()
        if status == "確定済み"
    ]

    st.markdown("#### 確定済み患者")
    if confirmed_pids:
        for pid in confirmed_pids:
            p = header[header["患者ID_正規化"] == pid].iloc[0]
            st.markdown(f"✅ **{p['患者氏名']}**（{pid}）— {p['確定術式']}")
    else:
        st.warning("確定済みの患者がいません。算定明細画面で確認・確定してください。")

    st.markdown("---")

    # --- 出力設定 ---
    col1, col2 = st.columns(2)
    with col1:
        output_scope = st.radio("出力対象", ["確定済みのみ", "全患者"])
    with col2:
        output_format = st.radio("出力形式", ["CSV", "Excel（.xlsx）"])

    target_pids = confirmed_pids if output_scope == "確定済みのみ" else list(st.session_state.patient_statuses.keys())

    if target_pids:
        st.markdown("---")
        st.markdown("#### 出力プレビュー — コピペ用形式（コード, 数量）")

        # --- 患者ごとにコピペ用のデータを表示 ---
        for pid in target_pids:
            p = header[header["患者ID_正規化"] == pid].iloc[0]
            st.markdown(f"##### {p['患者氏名']}（{pid}）")

            copy_lines = []

            # 麻酔コード（編集済みデータがあればそれを使用）
            masui_edits_key = f"{pid}_masui"
            if masui_edits_key in st.session_state.get("data_edits", {}):
                for r in st.session_state.data_edits[masui_edits_key]:
                    if r.get("コード") and str(r["コード"]) != "（なし）":
                        copy_lines.append(f"{r['コード']}, {r['合計']}")
            else:
                p_masui = masui_time[
                    (masui_time["患者ID_正規化"] == pid) & (masui_time["コード"].notna())
                ]
                for _, r in p_masui.iterrows():
                    copy_lines.append(f"{int(r['コード'])}, {r['合計']}")

            # 検査コード（編集済みデータがあればそれを使用）
            kensa_edits_key = f"{pid}_kensa"
            if kensa_edits_key in st.session_state.get("data_edits", {}):
                for r in st.session_state.data_edits[kensa_edits_key]:
                    copy_lines.append(f"{r['コード']}, {r['回数']}")
            else:
                p_kensa = kensa[kensa["患者ID_正規化"] == pid]
                for _, r in p_kensa.iterrows():
                    qty = str(int(r["回数"])) if pd.notna(r["回数"]) else "1"
                    copy_lines.append(f"{r['コード']}, {qty}")

            # 薬剤コード（編集済みデータがあればそれを使用）
            drugs_edits_key = f"{pid}_drugs"
            if drugs_edits_key in st.session_state.get("data_edits", {}):
                for r in st.session_state.data_edits[drugs_edits_key]:
                    copy_lines.append(f"{r['医事コード']}, {r['請求量']}")
            else:
                p_drugs = drugs[drugs["患者ID_正規化"] == pid]
                for _, r in p_drugs.iterrows():
                    copy_lines.append(f"{r['医事コード']}, {r['請求量']}")

            # テキストエリアで表示（コピーしやすいように）
            st.text_area(
                f"コピペ用（{p['患者氏名']}）",
                "\n".join(copy_lines),
                height=150,
                key=f"copy_{pid}",
            )

        # --- ダウンロード用の全データ作成 ---
        st.markdown("---")
        st.markdown("#### ファイルダウンロード")

        all_rows = []
        for pid in target_pids:
            p = header[header["患者ID_正規化"] == pid].iloc[0]
            name = p["患者氏名"]
            sdate = p["手術日_正規化"]

            # 麻酔（編集済みデータがあればそれを使用）
            masui_ek = f"{pid}_masui"
            if masui_ek in st.session_state.get("data_edits", {}):
                for r in st.session_state.data_edits[masui_ek]:
                    if r.get("コード") and str(r["コード"]) != "（なし）":
                        all_rows.append({
                            "患者ID": pid, "患者氏名": name, "手術日": sdate,
                            "区分": "麻酔", "項目名": r["名称"],
                            "コード": str(r["コード"]), "数量": r["合計"], "単位": "時間",
                        })
            else:
                for _, r in masui_time[
                    (masui_time["患者ID_正規化"] == pid) & (masui_time["コード"].notna())
                ].iterrows():
                    all_rows.append({
                        "患者ID": pid, "患者氏名": name, "手術日": sdate,
                        "区分": "麻酔", "項目名": r["名称"],
                        "コード": str(int(r["コード"])), "数量": r["合計"], "単位": "時間",
                    })

            # 検査（編集済みデータがあればそれを使用）
            kensa_ek = f"{pid}_kensa"
            if kensa_ek in st.session_state.get("data_edits", {}):
                for r in st.session_state.data_edits[kensa_ek]:
                    all_rows.append({
                        "患者ID": pid, "患者氏名": name, "手術日": sdate,
                        "区分": "検査", "項目名": r["名称"],
                        "コード": str(r["コード"]),
                        "数量": str(r["回数"]),
                        "単位": str(r.get("単位", "")),
                    })
            else:
                for _, r in kensa[kensa["患者ID_正規化"] == pid].iterrows():
                    all_rows.append({
                        "患者ID": pid, "患者氏名": name, "手術日": sdate,
                        "区分": "検査", "項目名": r["名称"],
                        "コード": str(r["コード"]),
                        "数量": str(int(r["回数"])) if pd.notna(r["回数"]) else "1",
                        "単位": str(r.get("単位", "")),
                    })

            # 薬剤（編集済みデータがあればそれを使用）
            drugs_ek = f"{pid}_drugs"
            if drugs_ek in st.session_state.get("data_edits", {}):
                for r in st.session_state.data_edits[drugs_ek]:
                    all_rows.append({
                        "患者ID": pid, "患者氏名": name, "手術日": sdate,
                        "区分": f"薬剤（{r['カテゴリ']}）", "項目名": r["名称"],
                        "コード": str(r["医事コード"]),
                        "数量": str(r["請求量"]), "単位": str(r["請求単位"]),
                    })
            else:
                for _, r in drugs[drugs["患者ID_正規化"] == pid].iterrows():
                    all_rows.append({
                        "患者ID": pid, "患者氏名": name, "手術日": sdate,
                        "区分": f"薬剤（{r['カテゴリ']}）", "項目名": r["名称"],
                        "コード": str(r["医事コード"]),
                        "数量": str(r["請求量"]), "単位": str(r["請求単位"]),
                    })

        df_output = pd.DataFrame(all_rows)

        col_dl1, col_dl2 = st.columns(2)

        with col_dl1:
            csv_buf = io.StringIO()
            df_output.to_csv(csv_buf, index=False, encoding="utf-8-sig")
            st.download_button(
                "📥 CSVダウンロード",
                data=csv_buf.getvalue().encode("utf-8-sig"),
                file_name=f"orbit_算定結果_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv", use_container_width=True,
            )

        with col_dl2:
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                df_output.to_excel(writer, index=False, sheet_name="算定結果")
            st.download_button(
                "📥 Excelダウンロード",
                data=excel_buf.getvalue(),
                file_name=f"orbit_算定結果_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # --- 操作履歴（直近5件を表示） ---
    if st.session_state.change_log:
        st.markdown("---")
        st.markdown("#### 直近の操作履歴")
        recent_logs = st.session_state.change_log[-5:]  # 直近5件
        st.dataframe(
            pd.DataFrame(reversed(recent_logs)),  # 新しい順
            use_container_width=True, hide_index=True,
        )
        st.caption("全履歴は「🕐 変更履歴」ページで確認できます")


# ============================================================
# ページ4: 変更履歴
# ============================================================
elif page == "🕐 変更履歴":

    st.markdown("""
    <div class="main-header">
        <h1>🕐 変更履歴</h1>
        <p>アプリ上で行った全ての操作（確定・取消・アップロード等）の履歴を確認できます。
           履歴は state.json に保存されるため、アプリを再起動しても残ります。</p>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.change_log:

        # --- セル編集ログの集計セクション ---
        cell_edits = [e for e in st.session_state.change_log if e.get("操作") == "セル編集"]

        if cell_edits:
            st.markdown("#### 📈 セル編集の集計分析")
            df_edits = pd.DataFrame(cell_edits)

            col_a1, col_a2 = st.columns(2)

            # 4-1. 修正が多いコード TOP5
            with col_a1:
                st.markdown("##### 修正が多いコード TOP5")
                top_codes = df_edits.groupby(["コード", "項目名"]).size().reset_index(name="修正回数")
                top_codes = top_codes.sort_values("修正回数", ascending=False).head(5)
                top_codes.insert(0, "順位", range(1, len(top_codes) + 1))
                st.dataframe(top_codes, use_container_width=True, hide_index=True)

            # 4-2. 術式別の修正率
            with col_a2:
                st.markdown("##### 術式別の修正率")
                confirmed_entries = [e for e in st.session_state.change_log if e.get("操作") == "確定"]
                if confirmed_entries:
                    # 術式ごとの確定回数
                    df_confirmed = pd.DataFrame(confirmed_entries)
                    # 確定ログには術式が空なので、患者IDから術式を引く
                    surgery_confirm_count = {}
                    for e in confirmed_entries:
                        pid = e.get("患者ID", "")
                        matched = header[header["患者ID_正規化"] == pid]
                        if len(matched) > 0:
                            sname = matched.iloc[0]["確定術式"]
                            surgery_confirm_count[sname] = surgery_confirm_count.get(sname, 0) + 1

                    # 術式ごとのセル編集回数
                    surgery_edit_count = df_edits.groupby("術式").size().to_dict()

                    surgery_stats = []
                    all_surgeries = set(list(surgery_confirm_count.keys()) + list(surgery_edit_count.keys()))
                    for sname in all_surgeries:
                        c_count = surgery_confirm_count.get(sname, 0)
                        e_count = surgery_edit_count.get(sname, 0)
                        rate = f"{e_count / c_count * 100:.0f}%" if c_count > 0 else "—"
                        surgery_stats.append({
                            "術式": sname,
                            "確定回数": c_count,
                            "修正回数": e_count,
                            "修正率": rate,
                        })
                    if surgery_stats:
                        st.dataframe(pd.DataFrame(surgery_stats), use_container_width=True, hide_index=True)
                    else:
                        st.caption("データが蓄積されると術式別修正率が表示されます")
                else:
                    st.caption("確定データが蓄積されると術式別修正率が表示されます")

            # 4-3. 修正パターン検出
            st.markdown("##### 修正パターン検出")
            pattern_group = df_edits.groupby(["コード", "項目名", "変更列", "変更前", "変更後"]).size().reset_index(name="件数")
            patterns = pattern_group[pattern_group["件数"] >= 2].sort_values("件数", ascending=False)

            if len(patterns) > 0:
                for _, p in patterns.iterrows():
                    # 同じコード・変更列の全件数を取得
                    same_code_col = df_edits[
                        (df_edits["コード"] == p["コード"]) & (df_edits["変更列"] == p["変更列"])
                    ]
                    total = len(same_code_col)
                    pct = p["件数"] / total * 100 if total > 0 else 0
                    st.info(
                        f"**パターン検出**: コード {p['コード']}（{p['項目名']}）の{p['変更列']}が "
                        f"{p['変更前']}→{p['変更後']} に修正されるケースが "
                        f"**{total}回中{p['件数']}回**（{pct:.0f}%）発生しています。\n\n"
                        f"→ ルールエンジンのデフォルト値の見直しを検討してください。"
                    )
            else:
                st.caption("同一パターンの修正が2回以上蓄積されるとここに表示されます")

            st.markdown("---")
        else:
            st.markdown("#### 📈 セル編集の集計分析")
            st.caption("セル編集データが蓄積されるとここにパターンが表示されます")
            st.markdown("---")

        # --- フィルター ---
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            # 操作種類でフィルタ
            all_actions = list(set(e["操作"] for e in st.session_state.change_log))
            action_filter = st.selectbox(
                "操作でフィルタ",
                ["すべて"] + sorted(all_actions),
            )
        with col_f2:
            # 患者でフィルタ
            all_patients = list(set(
                e["患者氏名"] for e in st.session_state.change_log if e["患者氏名"]
            ))
            patient_filter = st.selectbox(
                "患者でフィルタ",
                ["すべて"] + sorted(all_patients),
            )

        # フィルタ適用
        filtered_log = st.session_state.change_log.copy()
        if action_filter != "すべて":
            filtered_log = [e for e in filtered_log if e["操作"] == action_filter]
        if patient_filter != "すべて":
            filtered_log = [e for e in filtered_log if e["患者氏名"] == patient_filter]

        # 新しい順に表示
        st.markdown(f"#### 履歴一覧（{len(filtered_log)}件）")
        df_log = pd.DataFrame(reversed(filtered_log))
        # 旧ログに追加カラムがない場合に備えて欠損値を空文字で埋める
        for col_name in ["術式", "診療科", "タブ", "項目名", "コード", "変更列", "変更前", "変更後"]:
            if col_name not in df_log.columns:
                df_log[col_name] = ""
        df_log = df_log.fillna("")
        st.dataframe(
            df_log,
            use_container_width=True,
            hide_index=True,
            column_config={
                "日時": st.column_config.TextColumn("日時", width="medium"),
                "患者ID": st.column_config.TextColumn("患者ID", width="small"),
                "患者氏名": st.column_config.TextColumn("患者氏名", width="small"),
                "操作": st.column_config.TextColumn("操作", width="small"),
                "詳細": st.column_config.TextColumn("詳細", width="large"),
                "術式": st.column_config.TextColumn("術式", width="medium"),
                "診療科": st.column_config.TextColumn("診療科", width="small"),
                "タブ": st.column_config.TextColumn("タブ", width="small"),
                "項目名": st.column_config.TextColumn("項目名", width="medium"),
                "コード": st.column_config.TextColumn("コード", width="small"),
                "変更列": st.column_config.TextColumn("変更列", width="small"),
                "変更前": st.column_config.TextColumn("変更前", width="small"),
                "変更後": st.column_config.TextColumn("変更後", width="small"),
            },
        )

        # --- 履歴クリアボタン ---
        st.markdown("---")
        with st.expander("⚠️ 履歴の管理", expanded=False):
            st.markdown("履歴をクリアすると、全ての変更記録が削除されます。ステータス（確定/確認待ち）はリセットされません。")
            if st.button("🗑️ 変更履歴をすべてクリア", type="secondary"):
                st.session_state.change_log = []
                save_persisted_state(
                    st.session_state.patient_statuses,
                    st.session_state.change_log,
                    st.session_state.upload_history,
                    st.session_state.get("data_edits", {}),
                )
                st.success("変更履歴をクリアしました")
                st.rerun()

            st.markdown("---")
            st.markdown("ステータスを含めて初期状態に戻す場合は、以下のボタンを押してください。")
            if st.button("🔄 全データを初期状態にリセット", type="secondary"):
                # state.json を削除
                if STATE_FILE.exists():
                    STATE_FILE.unlink()
                # セッションもクリア
                for key in ["patient_statuses", "change_log", "upload_history", "data_edits", "initialized"]:
                    if key in st.session_state:
                        del st.session_state[key]
                st.success("初期状態にリセットしました。ページを再読み込みします。")
                st.rerun()
    else:
        st.info("まだ変更履歴がありません。算定明細の確定やPDFアップロードを行うと、ここに記録されます。")

    # --- 保存先の説明 ---
    with st.expander("ℹ️ データの保存について", expanded=False):
        st.markdown(f"""
        **保存先**: `{STATE_FILE}`

        プロトタイプでは、以下のデータがこのJSONファイルに保存されます：
        - 患者ごとのステータス（確認待ち / 確定済み）
        - 全ての変更履歴（操作日時・内容・患者情報）
        - PDFアップロード履歴

        本番環境では、これらは Fabric の Delta テーブルに保存され、
        複数人が同じ状態を参照できるようになります。
        """)
