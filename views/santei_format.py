"""
算定項目の表示・貼り付けコード・CSV用の共通フォーマット。
"""

from __future__ import annotations


def kubun_section_label(kubun: str) -> str:
    """区分ごとの見出し（■ の右側のラベル）。"""
    m = {
        "麻酔": "麻酔",
        "検査": "検査",
        "薬剤": "薬剤",
        "薬剤（術後鎮痛）": "術後鎮痛薬",
        "Aライン": "Aライン",
        "★項目": "★項目",
        "ナビ": "ナビゲーション",
    }
    return m.get(kubun or "", kubun or "（未分類）")


def description_line(row: dict) -> str:
    """
    「貼り付け」列に相当する1行説明。
    項目名・課金コード・単位・現在の数量を並べ、帳票・CSVで意味が通じるようにする。
    """
    name = str(row.get("項目名", "") or "").strip()
    code = str(row.get("コード", "") or "").strip()
    unit = str(row.get("単位", "") or "").strip()
    qty = str(row.get("現在値", "") or "").strip()
    parts = [name]
    if code:
        parts.append(code)
    if unit:
        parts.append(unit)
    if qty:
        parts.append(qty)
    return " ".join(parts).strip() or "—"


def paste_code_line(row: dict) -> str:
    """
    コストシステム向けの「貼り付けコード」1行（コード+数量,）。
    ★項目・ナビはこの形式に含めない。
    """
    if row.get("状態") == "削除":
        return ""
    kubun = row.get("区分", "")
    if kubun in ("★項目", "ナビ"):
        return "—"
    code = str(row.get("コード", "") or "").strip()
    qty = str(row.get("現在値", "") or "").strip()
    if not code and not qty:
        return "—"
    # 術後鎮痛薬カテゴリの先頭行は /33+ プレフィックス
    if kubun == "薬剤（術後鎮痛）" and row.get("_is_first_postop", False):
        return f"/33+{code}+{qty},"
    return f"{code}+{qty},"


def seishoku_display(row: dict) -> str:
    """生食課金コード列の表示用文字列（空なら —）。"""
    v = row.get("生食課金コード")
    if v is None:
        return "—"
    s = str(v).strip()
    return s if s else "—"


def seishoku_csv_value(row: dict) -> str:
    """CSV用（空欄は空文字）。"""
    v = row.get("生食課金コード")
    if v is None:
        return ""
    return str(v).strip()
