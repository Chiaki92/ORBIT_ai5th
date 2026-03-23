# ORBIT プロトタイプ — 起動手順

## 事前準備（初回のみ）

```bash
# 1. Pythonがインストールされていることを確認（3.9以上）
python --version

# 2. 必要なライブラリをインストール
pip install -r requirements.txt
```

## 起動方法

```bash
# orbit_prototype フォルダで実行
streamlit run app.py
```

ブラウザが自動で開きます（http://localhost:8501）

## フォルダ構成

```
orbit_prototype/
├── app.py                           ← メインアプリ
├── requirements.txt                 ← 必要ライブラリ
├── README.md                        ← このファイル
└── data/                            ← テストデータ（CSV）
    ├── masui_kensa_header_2.csv     ← 患者基本情報
    ├── masui_kensa_masui_time_2.csv ← 麻酔時間
    ├── masui_kensa_kensa_2.csv      ← 検査項目
    ├── masui_kensa_keika_2.csv      ← 経過記録
    ├── yakuzai_header_2.csv         ← 薬剤ヘッダー
    └── yakuzai_drugs_2.csv          ← 使用薬剤詳細
```

## 画面構成

1. **📋 患者一覧** — 手術患者のステータスを一覧表示
2. **📊 算定明細** — 患者ごとの麻酔・検査・薬剤データを確認・編集
3. **📤 データ出力** — 確定済みデータをCSV/Excelで出力（コピペ用形式にも対応）
