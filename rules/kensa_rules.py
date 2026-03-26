"""
kensa_rules.py — 検査データのルール

入力: masui_kensa_kensa.csv のデータ（data_loader.load_kensa()の戻り値）
処理:
  1. コードと回数をそのまま使用
  2. 回数がNaN/空の場合は 1 として扱う
  3. コードは整数として扱う（小数点なし）
出力: 患者ごとに コード・名称・回数 を持つDataFrame
"""

import pandas as pd


def apply_kensa_rules(df_kensa: pd.DataFrame) -> pd.DataFrame:
    """
    検査データに算定ルールを適用する。

    処理の流れ:
      1. 回数が空の場合は1で埋める（1回実施を意味する）
      2. コードを整数に変換する（小数点が付かないようにする）

    引数:
      df_kensa: load_kensa()で取得したDataFrame

    戻り値:
      DataFrame（列: 患者ID, 手術日, 名称, コード, 回数）
    """
    # データのコピーを作成（元データを変更しないため）
    df = df_kensa.copy()

    # --- ステップ1: 回数がNaN/空の場合は1で埋める ---
    df["回数"] = df["回数"].fillna(1)

    # 空文字やNaNを安全に処理してから整数変換
    df["回数"] = pd.to_numeric(df["回数"], errors="coerce").fillna(0).astype(int)

    # --- ステップ2: コードを整数に変換 ---
    # pandasがCSV読み込み時にfloat（例: 670651.0）にすることがあるので整数化
    df["コード"] = df["コード"].apply(lambda x: int(float(x)) if pd.notna(x) else 0)

    # --- ステップ3: 必要な列だけ選択して返す ---
    base_cols = ["患者ID", "手術日", "名称", "コード", "回数"]
    # 元データ確認用カラムがあれば追加
    extra_cols = [c for c in ["ファイル名", "元データ_ページ番号", "元データ_行番号", "元データ_サブフォルダ",
                              "元データ_bbox_x", "元データ_bbox_y", "元データ_bbox_w", "元データ_bbox_h"]
                  if c in df.columns]
    result = df[base_cols + extra_cols].copy()

    return result
