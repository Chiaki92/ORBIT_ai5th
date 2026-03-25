"""
page_upload.py — 画面0: データアップロード

PDF（使用薬剤レポート・麻酔検査レポート）とCSV（電カルデータ）を
Fabric LakehouseのFiles/raw/フォルダにアップロードし、
Notebook・Dataflow Gen2の実行をトリガーしてデータパイプラインを起動する。

rawフォルダの構成:
  raw/yakuzai/      — 使用薬剤レポート（PDF）
  raw/masui_kensa/  — 麻酔検査レポート（PDF）
  raw/orsys/        — ORSYS特殊検索（CSV）
  raw/karte_kiji/   — 記事データ（CSV）
"""

import os
import streamlit as st

from fabric_connection import (
    upload_file_to_onelake,
    trigger_notebook,
    trigger_dataflow,
    wait_for_job,
    is_fabric_available,
)


def render_upload():
    """
    アップロード画面を描画する。

    処理フロー:
      1. 4つのファイル選択ウィジェットを表示（種類別）
      2. 「アップロード実行」ボタンで処理を開始
      3. OneLakeの各サブフォルダにファイルをアップロード
      4. 使用薬剤Notebook実行（NOTEBOOK_YAKUZAI_ID）
      5. 麻酔検査Notebook実行（NOTEBOOK_MASUI_KENSA_ID）
      6. CSV取り込みNotebook実行（NOTEBOOK_CSV_IMPORT_ID）
      7. Dataflow Gen2実行 → 完了メッセージを表示
    """
    st.header("📎 データアップロード")

    # --- Fabric接続の環境変数チェック ---
    if not is_fabric_available():
        st.error(
            "Fabric接続の環境変数が設定されていません。"
            ".envファイルを確認してください。"
        )
        return

    # --- アップロード機能に必要な環境変数のチェック ---
    missing_keys = []
    for key in [
        "FABRIC_WORKSPACE_ID",
        "FABRIC_LAKEHOUSE_ID",
        "NOTEBOOK_YAKUZAI_ID",
        "NOTEBOOK_MASUI_KENSA_ID",
        "NOTEBOOK_CSV_IMPORT_ID",
        "DATAFLOW_ID",
    ]:
        if not os.environ.get(key):
            missing_keys.append(key)

    if missing_keys:
        st.warning(
            "アップロード機能に必要な環境変数が未設定です: "
            + ", ".join(missing_keys)
        )

    # =============================================
    # PDFアップロードセクション
    # =============================================
    st.subheader("■ PDFアップロード")

    # ① 使用薬剤レポート → raw/yakuzai/
    yakuzai_files = st.file_uploader(
        "使用薬剤レポート（PDF）",
        type=["pdf"],
        accept_multiple_files=True,
        key="uploader_yakuzai",
        help="使用薬剤レポートのPDFファイルを選択してください。複数ファイル選択可。",
    )

    # ② 麻酔検査レポート → raw/masui_kensa/
    masui_kensa_files = st.file_uploader(
        "麻酔検査レポート（PDF）",
        type=["pdf"],
        accept_multiple_files=True,
        key="uploader_masui_kensa",
        help="麻酔検査レポートのPDFファイルを選択してください。複数ファイル選択可。",
    )

    st.divider()

    # =============================================
    # CSVアップロードセクション
    # =============================================
    st.subheader("■ CSVアップロード（電カルデータ）")

    # ③ ORSYS特殊検索 → raw/orsys/
    orsys_files = st.file_uploader(
        "ORSYS特殊検索（CSV）",
        type=["csv"],
        accept_multiple_files=True,
        key="uploader_orsys",
        help="ORSYS特殊検索のCSVファイルを選択してください。複数ファイル選択可。",
    )

    # ④ 記事データ → raw/karte_kiji/
    karte_kiji_files = st.file_uploader(
        "記事データ（CSV）",
        type=["csv"],
        accept_multiple_files=True,
        key="uploader_karte_kiji",
        help="記事データのCSVファイルを選択してください。複数ファイル選択可。",
    )

    st.divider()

    # =============================================
    # ファイル選択状況の表示
    # =============================================

    # アップロードするファイルのリストを作成（サブフォルダ名とセットで管理）
    # 形式: [(ファイルオブジェクト, サブフォルダ名), ...]
    upload_items = []
    if yakuzai_files:
        for f in yakuzai_files:
            upload_items.append((f, "yakuzai"))
    if masui_kensa_files:
        for f in masui_kensa_files:
            upload_items.append((f, "masui_kensa"))
    if orsys_files:
        for f in orsys_files:
            upload_items.append((f, "orsys"))
    if karte_kiji_files:
        for f in karte_kiji_files:
            upload_items.append((f, "karte_kiji"))

    has_files = len(upload_items) > 0
    has_yakuzai = bool(yakuzai_files)
    has_masui_kensa = bool(masui_kensa_files)
    has_csv = bool(orsys_files or karte_kiji_files)

    # 選択済みファイル数を表示
    if has_files:
        st.info(f"合計 {len(upload_items)} 件のファイルが選択されています。")
    else:
        st.caption("アップロードするファイルを選択してください。")

    # =============================================
    # アップロード実行ボタン
    # =============================================
    upload_clicked = st.button(
        "アップロード実行",
        type="primary",
        disabled=(not has_files),
    )

    if not upload_clicked:
        return

    # --- ボタンが押されたら処理を実行 ---
    _run_upload_pipeline(upload_items, has_yakuzai, has_masui_kensa, has_csv)


def _run_upload_pipeline(
    upload_items: list,
    has_yakuzai: bool,
    has_masui_kensa: bool,
    has_csv: bool,
):
    """
    アップロードパイプラインを実行する。

    ステップ:
      1. 全ファイルをOneLake raw/{subfolder}/ にアップロード
      2. 使用薬剤Notebook実行 → 完了待機（薬剤PDFがある場合）
      3. 麻酔検査Notebook実行 → 完了待機（麻酔検査PDFがある場合）
      4. CSV取り込みNotebook実行 → 完了待機（CSVがある場合）
      5. Dataflow Gen2実行 → 完了待機

    引数:
      upload_items:     [(ファイルオブジェクト, サブフォルダ名), ...] のリスト
      has_yakuzai:      使用薬剤PDFが含まれているか
      has_masui_kensa:  麻酔検査PDFが含まれているか
      has_csv:          CSVファイルが含まれているか
    """
    # --- 環境変数の事前取得（エラーを早期に検出するため） ---
    yakuzai_notebook_id = os.environ.get("NOTEBOOK_YAKUZAI_ID")
    masui_kensa_notebook_id = os.environ.get("NOTEBOOK_MASUI_KENSA_ID")
    csv_notebook_id = os.environ.get("NOTEBOOK_CSV_IMPORT_ID")
    dataflow_id = os.environ.get("DATAFLOW_ID")

    total_files = len(upload_items)

    # st.status() で処理状況を表示するコンテナを作成
    with st.status("アップロード処理を実行中...", expanded=True) as status:

        # =============================================
        # Step 1: ファイルをOneLakeにアップロード
        # =============================================
        st.write("**Step 1/5: ファイルをOneLakeにアップロード中...**")

        uploaded_count = 0
        try:
            for file_obj, subfolder in upload_items:
                # ファイルの中身をバイト列として読み取る
                file_bytes = file_obj.read()
                # OneLakeの raw/{subfolder}/ にアップロード
                upload_file_to_onelake(file_bytes, file_obj.name, subfolder)
                uploaded_count += 1
                st.write(
                    f"  ✅ {file_obj.name} → raw/{subfolder}/ "
                    f"（{len(file_bytes):,} bytes）"
                )
        except Exception as e:
            st.error(f"ファイルアップロードに失敗しました: {e}")
            status.update(label="アップロード処理に失敗しました", state="error")
            return

        st.write(f"**ファイルアップロード完了（{uploaded_count}/{total_files}件）**")

        # =============================================
        # Step 2: 使用薬剤Notebook実行
        # =============================================
        if has_yakuzai and yakuzai_notebook_id:
            st.write("**Step 2/5: 使用薬剤Notebookを実行中...（1〜2分かかります）**")
            try:
                location_url = trigger_notebook(yakuzai_notebook_id)
                wait_for_job(location_url, timeout_seconds=600)
                st.write("  ✅ 使用薬剤の解析が完了しました")
            except TimeoutError:
                st.error("使用薬剤Notebookがタイムアウトしました。Fabricポータルで状態を確認してください。")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
            except Exception as e:
                st.error(f"使用薬剤Notebookの実行に失敗しました: {e}")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
        else:
            st.write("**Step 2/5: 使用薬剤Notebook — スキップ（該当ファイルなし）**")

        # =============================================
        # Step 3: 麻酔検査Notebook実行
        # =============================================
        if has_masui_kensa and masui_kensa_notebook_id:
            st.write("**Step 3/5: 麻酔検査Notebookを実行中...（1〜2分かかります）**")
            try:
                location_url = trigger_notebook(masui_kensa_notebook_id)
                wait_for_job(location_url, timeout_seconds=600)
                st.write("  ✅ 麻酔検査の解析が完了しました")
            except TimeoutError:
                st.error("麻酔検査Notebookがタイムアウトしました。Fabricポータルで状態を確認してください。")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
            except Exception as e:
                st.error(f"麻酔検査Notebookの実行に失敗しました: {e}")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
        else:
            st.write("**Step 3/5: 麻酔検査Notebook — スキップ（該当ファイルなし）**")

        # =============================================
        # Step 4: CSV取り込みNotebook実行
        # =============================================
        if has_csv and csv_notebook_id:
            st.write("**Step 4/5: CSV取り込みNotebookを実行中...**")
            try:
                location_url = trigger_notebook(csv_notebook_id)
                wait_for_job(location_url, timeout_seconds=600)
                st.write("  ✅ CSV取り込みが完了しました")
            except TimeoutError:
                st.error("CSV取り込みがタイムアウトしました。Fabricポータルで状態を確認してください。")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
            except Exception as e:
                st.error(f"CSV取り込みに失敗しました: {e}")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
        else:
            st.write("**Step 4/5: CSV取り込み — スキップ（CSVファイルなし）**")

        # =============================================
        # Step 5: Dataflow Gen2実行（テーブル結合処理）
        # =============================================
        if dataflow_id:
            st.write("**Step 5/5: Dataflow Gen2を実行中（データ結合処理）...（2〜3分かかります）**")
            try:
                location_url = trigger_dataflow(dataflow_id)
                wait_for_job(location_url, timeout_seconds=600)
                st.write("  ✅ データ結合が完了しました")
            except TimeoutError:
                st.error("Dataflow実行がタイムアウトしました。Fabricポータルで状態を確認してください。")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
            except Exception as e:
                st.error(f"Dataflow実行に失敗しました: {e}")
                status.update(label="アップロード処理に失敗しました", state="error")
                return
        else:
            st.write("**Step 5/5: Dataflow — スキップ（DATAFLOW_ID未設定）**")

        # =============================================
        # 完了
        # =============================================
        status.update(label="全ての処理が完了しました", state="complete")

    # 成功メッセージを表示（st.status()の外に表示される）
    st.success(
        "全ての処理が完了しました。"
        "サイドバーの「🔄 データ再読み込み」ボタンを押して、"
        "「患者一覧」画面で最新データを確認してください。"
    )
    st.balloons()
