"""
data_loader.py — データ読み込み（Fabric SQL / Gold）
"""

import logging
import streamlit as st

from fabric_connection import read_table

logger = logging.getLogger(__name__)

def normalize_patient_id(val) -> int:
    """
    患者IDを整数に変換する（先頭ゼロを除去）。

    例:
      "01000001" → 1000001
      "10000000" → 10000000
      10000000.0 → 10000000
    """
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def normalize_surgery_date(val) -> str:
    """
    手術日から曜日を除去する。

    例:
      "2026/01/01(木)" → "2026/01/01"
      "2026/01/01"     → "2026/01/01"（そのまま）
    """
    if val is None:
        return ""
    s = str(val)
    # 曜日が括弧付きで含まれる場合、括弧より前の部分だけ取り出す
    if "(" in s:
        s = s.split("(")[0]
    if "（" in s:
        s = s.split("（")[0]
    return s.strip()


def _common_preprocess(df):
    """
    全テーブル共通の前処理を行う。
    1. 「取込日時」列があれば削除（「ファイル名」は元データ確認用に保持）
    2. 「患者ID」列を整数に変換
    3. 「手術日」列の曜日を除去
    """
    # 取込日時のみ削除（ファイル名は元データ確認機能で使用するため保持）
    drop_cols = ["取込日時"]
    existing_drop_cols = [c for c in drop_cols if c in df.columns]
    if existing_drop_cols:
        df = df.drop(columns=existing_drop_cols)

    # 患者IDを整数に変換
    if "患者ID" in df.columns:
        df["患者ID"] = df["患者ID"].apply(normalize_patient_id)

    # 手術日の曜日を除去
    if "手術日" in df.columns:
        df["手術日"] = df["手術日"].apply(normalize_surgery_date)

    return df


def _read_from_fabric(table_name: str):
    """
    Fabricテーブルからデータを読み込み、共通前処理を適用する。
    列名 `手術日_統一` は下流互換のため `手術日` にリネームする。
    """
    df = read_table(table_name)
    if "手術日_統一" in df.columns and "手術日" not in df.columns:
        df = df.rename(columns={"手術日_統一": "手術日"})
    df = _common_preprocess(df)
    return df


@st.cache_data
def load_surgery_summary():
    """患者一覧 + 判定結果（gold_surgery_summary）を取得する。"""
    df = _read_from_fabric("gold_surgery_summary")
    # 患者一覧は「患者ID + 手術日」を一意キーとして扱うため重複行を除外する
    if not df.empty and {"患者ID", "手術日"}.issubset(df.columns):
        df = df.drop_duplicates(subset=["患者ID", "手術日"], keep="first").reset_index(drop=True)
    return df


@st.cache_data
def load_drug_items():
    """薬剤 + 動脈ライン + ★項目（gold_drug_items）を取得する。"""
    return _read_from_fabric("gold_drug_items")


@st.cache_data
def load_anesthesia_times():
    """麻酔時間（合算済み + 時間帯 + 根拠）（gold_anesthesia_times）を取得する。"""
    return _read_from_fabric("gold_anesthesia_times")


@st.cache_data
def load_exam_items():
    """検査コード + 回数（gold_exam_items）を取得する。"""
    return _read_from_fabric("gold_exam_items")
