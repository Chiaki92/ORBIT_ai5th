"""
drug_rules.py — 薬剤データのルール（マスター参照含む）

入力: yakuzai_drugs.csv のデータ + マスターCSV
処理:
  1. 医事コードの「X」プレフィックスを除去
  2. 生食の課金コード変換（seishoku_master.csv を参照）
  3. 術後鎮痛薬の識別（出力時に /33+ を付与するためのフラグ）
  4. Aライン追加課金は保留（マスターデータとして保持のみ）
出力: 患者ごとに コード・請求量 を持つDataFrame
"""

import pandas as pd


def _strip_x_prefix(code) -> str:
    """
    医事コードの先頭にある「X」を除去する。

    例:
      "X540000" → "540000"
      "302124"  → "302124"
      "登録なし" → "登録なし"（変換対象外なのでそのまま）
    """
    if pd.isna(code):
        return ""
    s = str(code).strip()
    if s.upper().startswith("X"):
        s = s[1:]
    return s


def _convert_seishoku_code(amount_ml, df_master: pd.DataFrame) -> str:
    """
    使用量(ml)に応じた生食の課金コードを返す。

    マスターCSVの「使用量上限ml」を昇順に走査し、
    使用量がその上限以下であれば対応する課金コードを返す。
    1000mlを超える場合は「要手入力」を返す。

    引数:
      amount_ml: 使用量（ml）
      df_master: seishoku_master.csv のDataFrame

    戻り値:
      課金コード文字列（例: "302124"）または "要手入力"
    """
    try:
        amount = float(amount_ml)
    except (ValueError, TypeError):
        return "要手入力"

    # マスターを使用量上限の昇順でソート
    master_sorted = df_master.sort_values("使用量上限ml")

    # 使用量に対応するコードを探す
    for _, row in master_sorted.iterrows():
        if amount <= row["使用量上限ml"]:
            return str(int(row["課金コード"]))

    # 1000ml超の場合は手入力が必要
    return "要手入力"


def apply_drug_rules(
    df_drugs: pd.DataFrame,
    df_seishoku_master: pd.DataFrame,
) -> pd.DataFrame:
    """
    薬剤データに算定ルールを適用する。

    処理の流れ:
      1. 医事コードのXプレフィックスを除去
      2. 生食の課金コード変換（希釈・溶解用生理食塩水 → マスター照合）
      3. 術後鎮痛薬に「術後鎮痛薬」フラグを付与（出力時 /33+ 用）

    引数:
      df_drugs: load_drugs()で取得したDataFrame
      df_seishoku_master: load_seishoku_master()で取得したDataFrame

    戻り値:
      DataFrame（列: 患者ID, 手術日, カテゴリ, 名称, コード, 請求量, 請求単位, 術後鎮痛薬フラグ, 生食課金コード）
    """
    # データのコピーを作成（元データを変更しないため）
    df = df_drugs.copy()
    df["生食課金コード"] = ""

    # --- ステップ1: 医事コードのXプレフィックスを除去 ---
    df["コード"] = df["医事コード"].apply(_strip_x_prefix)

    # --- ステップ2: 生食の課金コード変換 ---
    # 名称に「希釈」「溶解」「生理食塩」を含み、かつコードが「登録なし」の行が対象
    def is_seishoku_target(row) -> bool:
        """生食コード変換の対象かどうかを判定する"""
        name = str(row["名称"]) if pd.notna(row["名称"]) else ""
        code = str(row["コード"]) if pd.notna(row["コード"]) else ""
        # 名称に特定キーワードが含まれ、かつコードが「登録なし」
        keywords = ["希釈", "溶解", "生理食塩"]
        has_keyword = any(kw in name for kw in keywords)
        is_unregistered = code == "登録なし"
        return has_keyword and is_unregistered

    # 対象行のコードをマスター参照で置き換える
    for idx, row in df.iterrows():
        if is_seishoku_target(row):
            # 請求量（ml）に応じた課金コードを取得
            new_code = _convert_seishoku_code(row["請求量"], df_seishoku_master)
            df.at[idx, "コード"] = new_code
            df.at[idx, "生食課金コード"] = new_code

    # --- ステップ3: 術後鎮痛薬フラグ ---
    # カテゴリが「術後鎮痛薬」の行にフラグを立てる
    # 出力画面でコード先頭に /33+ を付与するために使用
    df["術後鎮痛薬フラグ"] = df["カテゴリ"] == "術後鎮痛薬"

    # --- ステップ4: 必要な列だけ選択して返す ---
    result = df[
        [
            "患者ID",
            "手術日",
            "カテゴリ",
            "名称",
            "コード",
            "請求量",
            "請求単位",
            "術後鎮痛薬フラグ",
            "生食課金コード",
        ]
    ].copy()

    return result
