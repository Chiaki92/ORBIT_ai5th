"""
data_loader.py — データ読み込み（Fabric SQL）

Fabricテーブルからデータを読み込む。
関数のインターフェース（引数・戻り値）は変えないこと。
"""

import os
import logging

import pandas as pd
import streamlit as st

from fabric_connection import read_table

logger = logging.getLogger(__name__)

# =============================================================================
# マスターデータのパス設定
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MASTERS_DIR = os.path.join(BASE_DIR, "masters")


# =============================================================================
# 前処理用のヘルパー関数
# =============================================================================

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
    if pd.isna(val):
        return ""
    s = str(val)
    # 曜日が括弧付きで含まれる場合、括弧より前の部分だけ取り出す
    if "(" in s:
        s = s.split("(")[0]
    if "（" in s:
        s = s.split("（")[0]
    return s.strip()


def _common_preprocess(df: pd.DataFrame) -> pd.DataFrame:
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


# =============================================================================
# Fabric読み込みヘルパー
# =============================================================================

def _read_from_fabric(table_name: str) -> pd.DataFrame:
    """
    Fabricテーブルからデータを読み込み、共通前処理を適用する。
    列名 `手術日_統一` は下流互換のため `手術日` にリネームする。
    """
    df = read_table(table_name)
    if "手術日_統一" in df.columns and "手術日" not in df.columns:
        df = df.rename(columns={"手術日_統一": "手術日"})
    df = _common_preprocess(df)
    return df


# =============================================================================
# データ読み込み関数
# =============================================================================

@st.cache_data
def load_header() -> pd.DataFrame:
    """患者基本情報を取得する（1手術=1行）。"""
    return _read_from_fabric("silver_masui_kensa_header")


@st.cache_data
def load_masui_time() -> pd.DataFrame:
    """麻酔時間データを取得する。"""
    return _read_from_fabric("silver_masui_kensa_masui_time")


@st.cache_data
def load_kensa() -> pd.DataFrame:
    """検査データを取得する。"""
    return _read_from_fabric("silver_masui_kensa_kensa")


@st.cache_data
def load_drugs() -> pd.DataFrame:
    """薬剤データを取得する。"""
    return _read_from_fabric("silver_yakuzai_drugs")


@st.cache_data
def load_star_items() -> pd.DataFrame:
    """★コスト項目（silver_orsys_star_items）を取得する。"""
    return _read_from_fabric("silver_orsys_star_items")


@st.cache_data
def load_kiji() -> pd.DataFrame:
    """ナビ判定用（silver_kiji_n_pn_head）を取得する。"""
    df = read_table("silver_kiji_n_pn_head")
    if "患者ID" in df.columns:
        df["患者ID"] = df["患者ID"].apply(normalize_patient_id)
    return df


@st.cache_data
def load_seishoku_master() -> pd.DataFrame:
    """生食課金コード変換マスターを取得する。"""
    path = os.path.join(MASTERS_DIR, "seishoku_master.csv")
    df = pd.read_csv(path, encoding="utf-8-sig")
    return df


@st.cache_data
def load_aline_master() -> pd.DataFrame:
    """Aライン追加課金マスターを取得する。"""
    path = os.path.join(MASTERS_DIR, "aline_master.csv")
    df = pd.read_csv(path, encoding="utf-8-sig")
    return df
