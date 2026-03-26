"""
state_manager.py — 箱2（作業台）・箱3（保存/確定）の管理

このファイルがデータの変更管理の中核。
箱1（システム算定値）、箱2（作業台）、箱3（保存履歴・ステータス）を管理する。

箱1: ルール適用後の不変データ（システムが計算した値）
箱2: ユーザーが編集中のデータ（session_stateに保持）
箱3a: 保存された編集履歴（edit_history.json）
箱3b: 患者ステータス（patient_status.json）
"""

import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from rules.masui_rules import masui_segments_by_code

# =============================================================================
# ファイルパスの設定
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_STORAGE_DIR = os.path.join(BASE_DIR, "local_storage")

# ローカル保存先のパス
EDIT_HISTORY_PATH = os.path.join(LOCAL_STORAGE_DIR, "edit_history.json")
PATIENT_STATUS_PATH = os.path.join(LOCAL_STORAGE_DIR, "patient_status.json")

# 処理回数（現在は固定値。将来的には動的に管理）
PROCESSING_ROUND = 1


# =============================================================================
# ローカルストレージのヘルパー関数
# =============================================================================

def _ensure_storage_dir():
    """local_storage ディレクトリがなければ作成する"""
    os.makedirs(LOCAL_STORAGE_DIR, exist_ok=True)


def _load_json(path: str) -> dict:
    """JSONファイルを読み込む。ファイルがなければ空の辞書を返す"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: str, data: dict):
    """JSONファイルに書き込む"""
    _ensure_storage_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# =============================================================================
# 元データ確認用ヘルパー
# =============================================================================

# サブフォルダとファイル拡張子の対応
_SUBFOLDER_MAP = {
    "masui_kensa": "masui_kensa",
    "yakuzai": "yakuzai",
    "orsys": "orsys",
    "karte_kiji": "karte_kiji",
}


def _build_source_entry(row, label: str, subfolder: str) -> dict | None:
    """
    DataFrameの行から元データ確認用のソースエントリを構築する。
    ファイル名がない場合はNoneを返す。
    """
    file_name = ""
    if hasattr(row, "get"):
        file_name = row.get("ファイル名", "")
    elif isinstance(row, pd.Series) and "ファイル名" in row.index:
        file_name = row["ファイル名"]

    if pd.isna(file_name) or str(file_name).strip() == "":
        return None

    entry = {
        "label": label,
        "file": str(file_name),
        "subfolder": subfolder,
    }
    # フェーズ2用: ページ番号・行番号・bbox座標があれば追加
    for col, key in [
        ("元データ_ページ番号", "page"),
        ("元データ_行番号", "row_num"),
    ]:
        val = row.get(col) if hasattr(row, "get") else (row[col] if col in row.index else None)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            entry[key] = int(val)
    for col in ["元データ_bbox_x", "元データ_bbox_y", "元データ_bbox_w", "元データ_bbox_h"]:
        val = row.get(col) if hasattr(row, "get") else (row[col] if col in row.index else None)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            if "bbox" not in entry:
                entry["bbox"] = {}
            short_key = col.split("_")[-1]  # x, y, w, h
            entry["bbox"][short_key] = float(val)

    return entry


# =============================================================================
# 箱1: システム算定値の構築
# =============================================================================

def build_box1(
    patient_id: int,
    masui_df: pd.DataFrame,
    kensa_df: pd.DataFrame,
    drugs_df: pd.DataFrame,
    star_items_df: pd.DataFrame | None = None,
    navi_df: pd.DataFrame | None = None,
    surgery_date: str | None = None,
    masui_time_raw_df: pd.DataFrame | None = None,
) -> list:
    """
    ルール適用後のデータを統一フォーマット（箱1）に変換する。

    全項目を以下の形式に統一:
      - row_id: 一意のID（区分+連番）
      - 区分: 麻酔 / 検査 / 薬剤
      - 項目名: 名称
      - コード: 算定コード
      - 数量: 時間 or 回数 or 請求量
      - 単位: 時間 / 回 / 各薬剤の単位

    引数:
      patient_id: 対象患者のID
      masui_df: apply_masui_rules() の出力
      kensa_df: apply_kensa_rules() の出力
      drugs_df: apply_drug_rules() の出力

    戻り値:
      箱1のデータ（辞書のリスト）
    """
    rows = []
    counter = 1

    # --- 麻酔データ ---
    patient_masui = masui_df[masui_df["患者ID"] == patient_id]
    if surgery_date is not None and "手術日" in patient_masui.columns:
        patient_masui = patient_masui[
            patient_masui["手術日"].astype(str) == str(surgery_date)
        ]

    masui_segments = (
        masui_segments_by_code(masui_time_raw_df, patient_id, surgery_date)
        if masui_time_raw_df is not None
        else {}
    )

    for _, row in patient_masui.iterrows():
        code = str(row["コード"])
        seg_list = masui_segments.get(code, [])
        masui_row = {
            "row_id": f"masui_{counter:03d}",
            "区分": "麻酔",
            "項目名": row["名称"],
            "コード": code,
            "数量": str(row["合計時間"]),
            "単位": "時間",
            "生食課金コード": "",
        }
        if seg_list:
            masui_row["麻酔時間内訳"] = seg_list
        # 元データ確認用
        src = _build_source_entry(row, "麻酔検査レポート(PDF)", "masui_kensa")
        masui_row["_sources"] = [src] if src else []
        rows.append(masui_row)
        counter += 1

    # --- 検査データ ---
    patient_kensa = kensa_df[kensa_df["患者ID"] == patient_id]
    counter = 1
    for _, row in patient_kensa.iterrows():
        src = _build_source_entry(row, "麻酔検査レポート(PDF)", "masui_kensa")
        rows.append({
            "row_id": f"kensa_{counter:03d}",
            "区分": "検査",
            "項目名": row["名称"],
            "コード": str(row["コード"]),
            "数量": str(row["回数"]),
            "単位": "回",
            "生食課金コード": "",
            "_sources": [src] if src else [],
        })
        counter += 1

    # --- 薬剤データ（術後鎮痛薬以外） ---
    patient_drugs = drugs_df[drugs_df["患者ID"] == patient_id]
    # 術後鎮痛薬以外を先に処理
    non_postop = patient_drugs[~patient_drugs["術後鎮痛薬フラグ"]]
    counter = 1
    for _, row in non_postop.iterrows():
        seishoku = ""
        if "生食課金コード" in row.index and pd.notna(row.get("生食課金コード")):
            seishoku = str(row["生食課金コード"]).strip()
        src = _build_source_entry(row, "使用薬剤レポート(PDF)", "yakuzai")
        rows.append({
            "row_id": f"drug_{counter:03d}",
            "区分": "薬剤",
            "項目名": row["名称"],
            "コード": str(row["コード"]),
            "数量": str(row["請求量"]),
            "単位": str(row["請求単位"]) if pd.notna(row["請求単位"]) else "",
            "生食課金コード": seishoku,
            "_sources": [src] if src else [],
        })
        counter += 1

    # --- 薬剤データ（術後鎮痛薬）→ リスト末尾に配置 ---
    postop = patient_drugs[patient_drugs["術後鎮痛薬フラグ"]]
    for _, row in postop.iterrows():
        seishoku = ""
        if "生食課金コード" in row.index and pd.notna(row.get("生食課金コード")):
            seishoku = str(row["生食課金コード"]).strip()
        src = _build_source_entry(row, "使用薬剤レポート(PDF)", "yakuzai")
        rows.append({
            "row_id": f"drug_{counter:03d}",
            "区分": "薬剤（術後鎮痛）",
            "項目名": row["名称"],
            "コード": str(row["コード"]),
            "数量": str(row["請求量"]),
            "単位": str(row["請求単位"]) if pd.notna(row["請求単位"]) else "",
            "生食課金コード": seishoku,
            "_sources": [src] if src else [],
        })
        counter += 1

    # --- ★項目（術後鎮痛薬の後に追加） ---
    if star_items_df is not None and not star_items_df.empty:
        resolved_date = surgery_date or st.session_state.get("selected_surgery_date")
        df = star_items_df[star_items_df["患者ID"] == patient_id] if "患者ID" in star_items_df.columns else star_items_df.iloc[0:0]
        if resolved_date and "手術日" in df.columns:
            df = df[df["手術日"] == resolved_date]

        item_col = "★項目" if "★項目" in df.columns else None
        if item_col:
            for idx, (_, srow) in enumerate(df.iterrows(), start=1):
                text = srow.get(item_col, "")
                if pd.isna(text) or str(text).strip() == "":
                    continue
                text = str(text)
                src = _build_source_entry(srow, "ORSYSデータ(CSV)", "orsys")
                rows.append({
                    "row_id": f"star_{idx:03d}",
                    "区分": "★項目",
                    "項目名": text,
                    "コード": "",
                    "数量": text,
                    "単位": "",
                    "生食課金コード": "",
                    "_sources": [src] if src else [],
                })

    # --- ナビ（最後に追加） ---
    navi_flag = "判定不可"
    reason = ""
    navi_sources = []
    if navi_df is not None and not navi_df.empty:
        resolved_date = surgery_date or st.session_state.get("selected_surgery_date")
        df = navi_df[navi_df["患者ID"] == patient_id] if "患者ID" in navi_df.columns else navi_df.iloc[0:0]
        if resolved_date and "手術日" in df.columns:
            df = df[df["手術日"] == resolved_date]
        if not df.empty:
            first = df.iloc[0]
            navi_flag = str(first.get("ナビフラグ", navi_flag))
            reason = str(first.get("判定理由", "")) if pd.notna(first.get("判定理由", "")) else ""
            # ナビは2つのソース: header(PDF) + kiji(CSV)
            header_file = first.get("_header_file", "")
            if header_file and str(header_file).strip():
                navi_sources.append({
                    "label": "機器情報(PDF)",
                    "file": str(header_file),
                    "subfolder": "masui_kensa",
                })
            kiji_file = first.get("_kiji_file", "")
            if kiji_file and str(kiji_file).strip():
                navi_sources.append({
                    "label": "記事データ(CSV)",
                    "file": str(kiji_file),
                    "subfolder": "karte_kiji",
                })

    item_name = "ナビゲーション加算"
    if reason:
        item_name = f"ナビゲーション加算（{reason}）"
    rows.append({
        "row_id": "navi_001",
        "区分": "ナビ",
        "項目名": item_name,
        "コード": "",
        "数量": navi_flag,
        "単位": "",
        "生食課金コード": "",
        "_sources": navi_sources,
    })

    return rows


# =============================================================================
# 箱2: 作業台（session_state）
# =============================================================================

def init_box2(patient_id: int, box1_rows: list):
    """
    箱1のデータをもとに箱2（作業台）をsession_stateに初期化する。

    箱2は箱1のコピーに「システム値」「現在値」「状態」の3列を追加したもの。
    すでに初期化済みの場合は何もしない（編集中のデータを保護するため）。

    引数:
      patient_id: 対象患者のID
      box1_rows: build_box1() の戻り値
    """
    key = f"box2_{patient_id}"

    # すでに初期化済みなら何もしない
    if key in st.session_state:
        return

    # 箱1をコピーして箱2を作成
    box2_rows = []
    for row in box1_rows:
        box2_row = row.copy()
        box2_row["システム値"] = row["数量"]   # 箱1の値をそのままコピー
        box2_row["現在値"] = row["数量"]       # 初期状態ではシステム値と同じ
        box2_row["システムコード"] = str(row["コード"])  # 課金コードの基準（薬剤の手入力用）
        box2_row["状態"] = "未変更"            # 初期状態
        box2_rows.append(box2_row)

    st.session_state[key] = box2_rows


def get_box2(patient_id: int) -> list:
    """
    箱2のデータを取得する。

    引数:
      patient_id: 対象患者のID

    戻り値:
      箱2のデータ（辞書のリスト）。未初期化の場合は空リスト
    """
    key = f"box2_{patient_id}"
    return st.session_state.get(key, [])


def update_box2(patient_id: int, updated_rows: list):
    """
    箱2のデータを更新する。

    引数:
      patient_id: 対象患者のID
      updated_rows: 更新後のデータ（辞書のリスト）
    """
    key = f"box2_{patient_id}"
    st.session_state[key] = updated_rows


def reset_box2(patient_id: int, box1_rows: list):
    """
    箱2を箱1の状態にリセットする（全ての編集を取り消す）。

    引数:
      patient_id: 対象患者のID
      box1_rows: build_box1() の戻り値
    """
    key = f"box2_{patient_id}"
    # キーを削除して再初期化
    if key in st.session_state:
        del st.session_state[key]
    init_box2(patient_id, box1_rows)


def has_unsaved_changes(patient_id: int) -> bool:
    """
    箱2に未保存の変更があるかどうかを判定する。
    状態が「未変更」でない行が1つでもあれば True を返す。

    引数:
      patient_id: 対象患者のID

    戻り値:
      未保存の変更がある場合 True
    """
    box2 = get_box2(patient_id)
    for row in box2:
        if row["状態"] != "未変更":
            return True
    return False


# =============================================================================
# 箱3a: 編集履歴（edit_history.json）
# =============================================================================

def _load_edit_history() -> dict:
    """編集履歴JSONを読み込む"""
    data = _load_json(EDIT_HISTORY_PATH)
    if "records" not in data:
        data["records"] = []
    return data


def _save_edit_history(data: dict):
    """編集履歴JSONを保存する"""
    _save_json(EDIT_HISTORY_PATH, data)


# =============================================================================
# 箱3b: 患者ステータス（patient_status.json）
# =============================================================================

def _load_patient_statuses() -> dict:
    """患者ステータスJSONを読み込む"""
    data = _load_json(PATIENT_STATUS_PATH)
    if "statuses" not in data:
        data["statuses"] = []
    return data


def _save_patient_statuses(data: dict):
    """患者ステータスJSONを保存する"""
    _save_json(PATIENT_STATUS_PATH, data)


def _find_patient_status(statuses: list, patient_id: int, surgery_date: str) -> dict | None:
    """
    ステータスリストから該当患者のステータスを探す。

    引数:
      statuses: ステータスのリスト
      patient_id: 患者ID
      surgery_date: 手術日

    戻り値:
      該当するステータス辞書。見つからなければ None
    """
    for s in statuses:
        if s["患者ID"] == patient_id and s["手術日"] == surgery_date:
            return s
    return None


def get_patient_status(patient_id: int, surgery_date: str) -> dict:
    """
    患者のステータス情報を取得する。
    JSONに存在しない場合は「確認待ち」のデフォルト値を返す。

    引数:
      patient_id: 患者ID
      surgery_date: 手術日

    戻り値:
      ステータス辞書（ステータス, バージョン, 最終更新日時, processing_round）
    """
    data = _load_patient_statuses()
    found = _find_patient_status(data["statuses"], patient_id, surgery_date)
    if found:
        return found
    # デフォルト値（JSONに未登録の患者）
    return {
        "processing_round": PROCESSING_ROUND,
        "患者ID": patient_id,
        "手術日": surgery_date,
        "ステータス": "確認待ち",
        "最終更新日時": "",
        "バージョン": 0,
    }


def get_all_patient_statuses() -> list:
    """全患者のステータス情報をリストで返す"""
    data = _load_patient_statuses()
    return data["statuses"]


def save_edits(patient_id: int, surgery_date: str, box1_rows: list, expected_version: int) -> tuple:
    """
    箱2の変更をedit_history.jsonに保存し、ステータスを「保存済み」に更新する。
    楽観ロック: 保存前にバージョンをチェックし、不一致なら保存を拒否する。

    引数:
      patient_id: 患者ID
      surgery_date: 手術日
      box1_rows: 箱1のデータ（比較用）
      expected_version: 画面を開いた時点のバージョン

    戻り値:
      (成功フラグ, メッセージ)
    """
    # --- 楽観ロックチェック ---
    current_status = get_patient_status(patient_id, surgery_date)
    if current_status["バージョン"] != expected_version:
        return False, "他で先に保存されています。ページを再読み込みしてください。"

    # --- 箱2のデータを取得 ---
    box2 = get_box2(patient_id)
    if not box2:
        return False, "保存するデータがありません。"

    # --- 差分を記録 ---
    now = datetime.now().isoformat()
    new_version = expected_version + 1
    edit_records = []

    for row in box2:
        # 状態が「未変更」の行は記録しない
        if row["状態"] == "未変更":
            continue

        record = {
            "processing_round": PROCESSING_ROUND,
            "患者ID": patient_id,
            "手術日": surgery_date,
            "コード": row["コード"],
            "システムコード": row.get("システムコード", row["コード"]),
            "項目名": row["項目名"],
            "システム値": row["システム値"],
            "変更後の値": row["現在値"],
            "アクション": row["状態"],  # 修正済み / 削除 / 追加
            "保存日時": now,
            "バージョン": new_version,
        }
        edit_records.append(record)

    # --- edit_history.json に追記 ---
    history = _load_edit_history()
    history["records"].extend(edit_records)
    _save_edit_history(history)

    # --- patient_status.json を更新 ---
    status_data = _load_patient_statuses()
    found = _find_patient_status(status_data["statuses"], patient_id, surgery_date)
    if found:
        found["ステータス"] = "保存済み"
        found["バージョン"] = new_version
        found["最終更新日時"] = now
    else:
        status_data["statuses"].append({
            "processing_round": PROCESSING_ROUND,
            "患者ID": patient_id,
            "手術日": surgery_date,
            "ステータス": "保存済み",
            "最終更新日時": now,
            "バージョン": new_version,
        })
    _save_patient_statuses(status_data)

    return True, "保存しました"


def confirm_patient(patient_id: int, surgery_date: str) -> tuple:
    """
    患者のステータスを「確定済み」に更新する。

    引数:
      patient_id: 患者ID
      surgery_date: 手術日

    戻り値:
      (成功フラグ, メッセージ)
    """
    status_data = _load_patient_statuses()
    found = _find_patient_status(status_data["statuses"], patient_id, surgery_date)
    now = datetime.now().isoformat()

    if found:
        found["ステータス"] = "確定済み"
        found["最終更新日時"] = now
    else:
        status_data["statuses"].append({
            "processing_round": PROCESSING_ROUND,
            "患者ID": patient_id,
            "手術日": surgery_date,
            "ステータス": "確定済み",
            "最終更新日時": now,
            "バージョン": 0,
        })
    _save_patient_statuses(status_data)

    return True, "確定しました"
