"""
masui_rules.py — 麻酔時間の合算ルール

入力: masui_kensa_masui_time.csv のデータ（data_loader.load_masui_time()の戻り値）
処理:
  1. コード列がNaN/空の行を削除（コスト算定対象外）
  2. 同一患者＋同一コードでグループ化し、合計時間を合算
  3. 各患者の麻酔開始時間（全コードの中で最も早い開始時刻）を算出
出力: 患者ごとに コード・合計時間・麻酔開始時間 を持つDataFrame
"""

import pandas as pd


def _parse_time_to_minutes(time_str) -> int:
    """
    時刻文字列（H:MM や HH:MM）を分単位の整数に変換する。

    例:
      "12:52" → 772分
      "2:00"  → 120分
      "0:19"  → 19分
    """
    if pd.isna(time_str) or str(time_str).strip() == "":
        return 0
    parts = str(time_str).strip().split(":")
    if len(parts) != 2:
        return 0
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        return hours * 60 + minutes
    except ValueError:
        return 0


def _minutes_to_time_str(total_minutes: int) -> str:
    """
    分単位の整数を時刻文字列に変換する。

    例:
      772分 → "12:52"
      120分 → "2:00"
      19分  → "0:19"
    """
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}:{minutes:02d}"


def _fmt_masui_cell(val) -> str:
    """表示用にセル値を文字列化する（欠損は '-'）。"""
    if pd.isna(val):
        return "-"
    s = str(val).strip()
    return s if s else "-"


def masui_segments_by_code(
    df_masui_time: pd.DataFrame | None,
    patient_id: int,
    surgery_date,
) -> dict[str, list[dict[str, str]]]:
    """
    算定対象（コードあり）の元行ごとに、開始・終了・合計をコード別にまとめる。

    apply_masui_rules と同じコード正規化・コードなし行除外を行う。
    同一患者・同一手術日・同一コードで複数行ある場合（合算元）はすべて返す。

    戻り値:
      コード → [{"開始", "終了", "合計"}, ...]
    """
    if df_masui_time is None or df_masui_time.empty:
        return {}

    df = df_masui_time.copy()
    df = df[df["患者ID"] == patient_id]
    if surgery_date is not None and "手術日" in df.columns:
        df = df[df["手術日"].astype(str) == str(surgery_date)]

    df = df.dropna(subset=["コード"])
    df = df[df["コード"].astype(str).str.strip() != ""]
    df["コード"] = df["コード"].apply(
        lambda x: str(int(float(x))) if pd.notna(x) else ""
    )

    out: dict[str, list[dict[str, str]]] = {}
    for _, row in df.iterrows():
        code = str(row["コード"])
        if not code:
            continue
        seg = {
            "開始": _fmt_masui_cell(row.get("開始")),
            "終了": _fmt_masui_cell(row.get("終了")),
            "合計": _fmt_masui_cell(row.get("合計")),
        }
        out.setdefault(code, []).append(seg)
    return out


def apply_masui_rules(df_masui_time: pd.DataFrame) -> pd.DataFrame:
    """
    麻酔時間データに算定ルールを適用する。

    処理の流れ:
      1. コードがない行（全時間の最初〜最後を示すだけの行）を除外
      2. 同一患者・同一コードの合計時間を合算（分単位で計算→時間文字列に戻す）
      3. 各患者の最も早い「開始」時刻を麻酔開始時間として抽出

    引数:
      df_masui_time: load_masui_time()で取得したDataFrame

    戻り値:
      DataFrame（列: 患者ID, 手術日, 名称, コード, 合計時間, 麻酔開始時間）
    """
    # データのコピーを作成（元データを変更しないため）
    df = df_masui_time.copy()

    # --- ステップ1: コードがNaN/空の行を削除 ---
    # コードなし行は「全時間の最初〜最後を示すだけのもの」で算定対象外
    df = df.dropna(subset=["コード"])
    df = df[df["コード"].astype(str).str.strip() != ""]

    # コードを文字列に統一（floatで読み込まれた場合に整数→文字列に変換）
    df["コード"] = df["コード"].apply(lambda x: str(int(float(x))) if pd.notna(x) else "")

    # --- ステップ2: 麻酔開始時間の算出 ---
    # 各患者の全コードの中で最も早い「開始」時刻を抽出
    # （途中でコードが変わっても、手術全体の最初の開始時間を使う）
    start_times = (
        df.groupby(["患者ID", "手術日"])["開始"]
        .min()
        .reset_index()
        .rename(columns={"開始": "麻酔開始時間"})
    )

    # --- ステップ3: 同一患者＋同一コードで合計時間を合算 ---
    # 合計列の時刻文字列を分単位に変換
    df["合計_分"] = df["合計"].apply(_parse_time_to_minutes)

    # グループ化して合算
    agg_dict = {
        "名称": ("名称", "first"),       # 同一コードの名称は同じなので先頭を取る
        "合計_分": ("合計_分", "sum"),     # 分単位で合算
    }
    # 元データ確認用: ファイル名があれば先頭を保持
    if "ファイル名" in df.columns:
        agg_dict["ファイル名"] = ("ファイル名", "first")
    grouped = (
        df.groupby(["患者ID", "手術日", "コード"])
        .agg(**agg_dict)
        .reset_index()
    )

    # 分単位を時間文字列に変換
    grouped["合計時間"] = grouped["合計_分"].apply(_minutes_to_time_str)

    # 不要な列を削除
    grouped = grouped.drop(columns=["合計_分"])

    # --- ステップ4: 麻酔開始時間をマージ ---
    result = grouped.merge(start_times, on=["患者ID", "手術日"], how="left")

    # 列の並び順を整理して返す
    result = result[["患者ID", "手術日", "名称", "コード", "合計時間", "麻酔開始時間"]]

    return result
