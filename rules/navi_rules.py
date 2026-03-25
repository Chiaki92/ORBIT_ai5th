"""
navi_rules.py — ナビゲーション加算判定ルール

ナビゲーション加算の算定対象かどうかを判定する。
判定条件:
  1. headerの「申込使用機器」列に「ナビ」の文字列が含まれるか
  2. kiji_n_pn_headに同日の臨床工学技士の記事があるか
  3. 両方YESの場合 → 「対象」、それ以外 → 「非対象」、データ不足 → 「判定不可」

注意:
  心臓血管外科のトラブル記録は誤検知のもと。
  「申込使用機器」に「ナビ」がなければ、臨工の記事があってもフラグはFALSE。
"""

import pandas as pd


def _check_equipment(header_row: pd.Series) -> bool | None:
    """
    headerの「申込使用機器」列に「ナビ」が含まれるかチェックする。

    引数:
      header_row: header DataFrameの1行（pd.Series）

    戻り値:
      True: 「ナビ」が含まれる
      False: 「ナビ」が含まれない
      None: 列が存在しないか値がNaN（判定不可）
    """
    # 「申込使用機器」列が存在するかチェック
    if "申込使用機器" not in header_row.index:
        return None

    value = header_row["申込使用機器"]

    # NaN/空の場合は判定不可
    if pd.isna(value) or str(value).strip() == "":
        return False

    # 「ナビ」が含まれるかチェック
    return "ナビ" in str(value)


def _check_clinical_engineer(patient_id: int, surgery_date: str, kiji_df: pd.DataFrame) -> bool | None:
    """
    同日（手術日 = 記載日_統一）に臨床工学技士の記事があるかチェックする。

    引数:
      patient_id: 患者ID
      surgery_date: 手術日（YYYY/MM/DD形式）
      kiji_df: load_kiji() の出力（silver_kiji_n_pn_head）

    戻り値:
      True: 同日の臨工記事がある
      False: 同日の臨工記事がない
      None: kiji_dfが空またはデータ不足（判定不可）
    """
    # kiji_dfが空の場合（Fabric未接続時など）は判定不可
    if kiji_df is None or kiji_df.empty:
        return None

    # 患者IDでフィルタ
    patient_kiji = kiji_df[kiji_df["患者ID"] == patient_id]
    if patient_kiji.empty:
        return False

    # 日付の正規化（文字列比較で一致を確認）
    # Fabricの「記載日_統一」とheaderの「手術日」を比較
    date_col = "記載日_統一" if "記載日_統一" in kiji_df.columns else "手術日"

    try:
        # 日付フォーマットを正規化して比較
        surgery_dt = pd.to_datetime(surgery_date, errors="coerce")
        patient_kiji = patient_kiji.copy()
        patient_kiji["_date_normalized"] = pd.to_datetime(patient_kiji[date_col], errors="coerce")

        # 同日のレコードがあればTrue
        same_day = patient_kiji[patient_kiji["_date_normalized"] == surgery_dt]
        return not same_day.empty
    except Exception:
        return None


def apply_navi_rules(header_df: pd.DataFrame, kiji_df: pd.DataFrame) -> pd.DataFrame:
    """
    全患者に対してナビゲーション加算判定を実行する。

    判定ロジック:
      - 両方YES（機器にナビ + 臨工記事あり）→ 「対象」
      - 機器にナビなし → 「非対象」
      - データ不足（列なし、kiji空）→ 「判定不可」

    引数:
      header_df: load_header() の出力（患者基本情報）
      kiji_df: load_kiji() の出力（臨床工学技士記事）

    戻り値:
      DataFrame（列: 患者ID, 手術日, ナビフラグ, 判定理由）
    """
    results = []

    for _, row in header_df.iterrows():
        patient_id = row["患者ID"]
        surgery_date = row["手術日"]

        # --- 条件1: 申込使用機器に「ナビ」が含まれるか ---
        equip_result = _check_equipment(row)

        # --- 条件2: 同日の臨工記事があるか ---
        engineer_result = _check_clinical_engineer(patient_id, surgery_date, kiji_df)

        # --- 判定ロジック ---
        if equip_result is None:
            # 「申込使用機器」列がない（CSV環境など）→ 判定不可
            navi_flag = "判定不可"
            reason = "申込使用機器データなし"
        elif not equip_result:
            # 機器に「ナビ」なし → 非対象
            navi_flag = "非対象"
            reason = "申込機器にナビなし"
        elif engineer_result is None:
            # 機器に「ナビ」あり、だが臨工記事データなし → 判定不可
            navi_flag = "判定不可"
            reason = "臨工記事データなし（申込機器にナビあり）"
        elif engineer_result:
            # 両方YES → 対象
            navi_flag = "対象"
            reason = "申込機器にナビあり＋臨工記事あり"
        else:
            # 機器に「ナビ」あるが臨工記事なし → 非対象
            navi_flag = "非対象"
            reason = "臨工記事なし（申込機器にナビあり）"

        results.append({
            "患者ID": patient_id,
            "手術日": surgery_date,
            "ナビフラグ": navi_flag,
            "判定理由": reason,
        })

    return pd.DataFrame(results)
