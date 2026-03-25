# ORBIT 統合実装指示書（v2: Silver層最新構成反映）

プロジェクト名: ORBIT（オービット）
作成日: 2026/03/25
技術スタック: Streamlit + Microsoft Fabric + Azure App Service

---

## 変更履歴

- Phase1指示書から統合: テーブル構成が2→6に変更（クロス結合問題のため独立出力に変更）
- orsys結合完了: ナビゲーション加算判定を実装スコープに追加
- ★コスト項目（orsys_star_items）を算定明細の表示・編集対象に追加
- Phase2（Fabric接続・アップロード・デプロイ）を統合

---

## 全体アーキテクチャ

```
[Fabric Lakehouse] orbit_lakehouse
  ├── Bronze層: Notebookで生成（構築済み）
  ├── Silver層: Dataflow Gen2で生成（構築済み・出力済み）
  │   ├── silver_masui_kensa_header    ← 患者基本情報 + orsys結合済み
  │   ├── silver_masui_kensa_kensa     ← 検査コード + 回数
  │   ├── silver_masui_kensa_masui_time← 麻酔時間（コードなし行は削除済み）
  │   ├── silver_yakuzai_drugs         ← 薬剤コード + 請求量
  │   ├── silver_orsys_star_items      ← ★コスト項目（1項目1行）
  │   └── silver_kiji_n_pn_head        ← ナビ判定用（臨床工学技士記事）
  ├── edit_history テーブル（新規作成）
  └── patient_status テーブル（新規作成）

[Streamlit アプリ]（Azure App Service上）
  ├── 読み取り: pyodbc + SQL エンドポイント（CSV fallback付き）
  ├── 書き戻し: Fabric REST API → Notebook トリガー
  └── 認証: Azure AD サービスプリンシパル（権限確認済み）
```

---

## ファイル構成

```
orbit_app/
├── app.py                     # メインアプリ（サイドバー4ページ切替）
├── data_loader.py             # データ読み込み（Fabric SQL接続）
├── fabric_connection.py       # Fabric接続（認証・SQL・OneLake・REST API）
├── state_manager.py           # 箱1/箱2/箱3の3層データ管理
├── views/
│   ├── __init__.py
│   ├── page_upload.py         # 画面0: PDF/CSVアップロード
│   ├── page_patient_list.py   # 画面1: 患者一覧
│   ├── page_detail.py         # 画面2: 算定明細（編集・保存・確定）
│   └── page_output.py         # 画面3: コピペ出力・ダウンロード
├── rules/
│   ├── __init__.py
│   ├── masui_rules.py         # 麻酔時間の合算ルール
│   ├── kensa_rules.py         # 検査データのルール
│   ├── drug_rules.py          # 薬剤データのルール（マスター参照含む）
│   └── navi_rules.py          # ナビゲーション加算判定
├── masters/
│   ├── seishoku_master.csv    # 生食課金コード変換マスター
│   └── aline_master.csv       # Aライン追加課金マスター
├── .env                       # 認証情報（gitignore対象）
├── startup.sh                 # App Service起動スクリプト
├── requirements.txt
└── .gitignore
```

---

## Silver層テーブル構成（6テーブル）

### 重要: なぜ6テーブルなのか

当初は全テーブルをmasui_kensa_headerに結合する計画だったが、
1手術:多行のテーブル（kensa, masui_time, drugs等）を同時に結合すると
クロス結合（直積）になり行数が爆発するため、各テーブルを独立出力に変更した。

### テーブル一覧と結合キー

全テーブル共通の結合キー: `患者ID`（整数）+ `手術日_統一`（YYYY/MM/DD文字列）
※ kiji_n_pn_headのみ `記載日_統一` を使い、手術日との「同日」判定で結合

| # | テーブル名 | 粒度 | 主な列 |
|---|-----------|------|--------|
| 1 | silver_masui_kensa_header | 1手術=1行 | 患者ID, 患者氏名, 手術日_統一, 確定術式, 確定病名, 診療科, 手術時間_合計, 麻酔時間_合計, ライン情報, 確定術式_申込, 動脈ライン準備, 申込使用機器 |
| 2 | silver_masui_kensa_kensa | 1検査項目=1行 | 患者ID, 手術日_統一, コード, 名称, 回数, 単位 |
| 3 | silver_masui_kensa_masui_time | 1麻酔区分=1行 | 患者ID, 手術日_統一, 開始, 終了, 合計, コード, 名称 |
| 4 | silver_yakuzai_drugs | 1薬剤=1行 | 患者ID, 手術日_統一, カテゴリ, 名称, 医事コード, 請求量, 請求単位 |
| 5 | silver_orsys_star_items | 1★項目=1行 | 患者ID, 手術日_統一, ★項目 |
| 6 | silver_kiji_n_pn_head | 1記事=1行 | 患者ID, 記載日_統一, その他記事情報 |

---

## データ読み込み（data_loader.py）

fabric_connection.py の read_table() を使って、Fabric SQLエンドポイントからデータを取得する。

### 関数一覧

```python
def load_header() -> pd.DataFrame:
    """silver_masui_kensa_header を取得"""

def load_masui_time() -> pd.DataFrame:
    """silver_masui_kensa_masui_time を取得"""

def load_kensa() -> pd.DataFrame:
    """silver_masui_kensa_kensa を取得"""

def load_drugs() -> pd.DataFrame:
    """silver_yakuzai_drugs を取得"""

def load_star_items() -> pd.DataFrame:
    """silver_orsys_star_items を取得"""

def load_kiji() -> pd.DataFrame:
    """silver_kiji_n_pn_head を取得"""
```

### 前処理

Fabric Silverテーブルは正規化済み（患者ID整数変換、手術日統一、コードなし行削除）のため、
data_loader側での前処理は不要。read_table() の結果をそのまま返す。

---

## 算定ルール（rules/）

### masui_rules.py: 麻酔時間の合算

**入力**: silver_masui_kensa_masui_time（コードなし行は削除済み）
**処理**:
1. 同一患者＋同一コードでグループ化し、合計時間を合算
   - 合計列の時刻文字列（例: `12:52`）をパースして分単位に変換→合算→再フォーマット
2. 「麻酔困難」（コード492600）と「その他」（コード492700）は同一患者に同時発生しない。同一コード同士の合算のみ
3. 深夜加算判定用に「麻酔開始時間」を算出
   - 全コードの中で最も早い「開始」時刻を抽出（1手術に1つ）

**出力**: 患者ごとに以下の列を持つDataFrame:
- 患者ID, 手術日_統一, 名称, コード, 合計時間, 麻酔開始時間

### kensa_rules.py: 検査データ

**入力**: silver_masui_kensa_kensa
**処理**:
1. コードと回数をそのまま使用
2. 回数がNaN/空の場合は `1` として扱う
3. コードは整数として扱う

**出力**: 患者ID, 手術日_統一, 名称, コード, 回数

### drug_rules.py: 薬剤データ

**入力**: silver_yakuzai_drugs + マスターCSV 2つ
**処理**:
1. 基本: 医事コード＋請求量をそのまま使う
2. 生食の課金コード変換:
   - 名称に「希釈」「溶解」「生理食塩」を含む場合にマスター照合
   - seishoku_master.csv 参照:
     ```csv
     使用量上限ml,課金コード
     20,302123
     50,302124
     100,302125
     250,300911
     500,305410
     1000,302131
     ```
   - 1000ml超は「要手入力」フラグを立てる
3. Aライン追加課金:
   - aline_master.csv の3薬剤:
     ```csv
     薬剤名,課金コード,使用量
     ラクトリンゲル,304590,1
     ヘパNa,341091,0.15
     ヘパロック,307830,1
     ```
   - 判定データ: headerの「動脈ライン準備」列（値: シングル/三連/nan）
   - nan以外 → Aライン使用あり、が基本ロジック
   - ただし「シングル」と「三連」で追加薬剤・数量が変わるか藤原先生に確認中
   - 確認が取れるまで保留。マスター保持のみ、自動追加は実装しない
   - ※ 藤原先生から回答があればこの部分を「実装」に切り替える
4. 術後鎮痛薬の区分移動:
   - カテゴリ列が「術後鎮痛薬」の行を識別
   - 出力時にリスト末尾に移動し、コードの先頭に `/33+` を付与
   - 例: `302124+1,` → `/33+302124+1,`

### navi_rules.py: ナビゲーション加算判定

**入力**:
- silver_masui_kensa_header の「申込使用機器」列（orsys由来、結合済み）
- silver_kiji_n_pn_head（独立テーブル）

**処理**:
1. headerの「申込使用機器」欄に「ナビ」の文字列が含まれるかチェック
2. kiji_n_pn_headに同日（手術日_統一 = 記載日_統一）の臨床工学技士の記事があるかチェック
3. 両方YESの場合 → ナビゲーション算定対象フラグ = TRUE
4. 注意: 心臓血管外科のトラブル記録は誤検知のもと
   - 「申込使用機器」欄に「ナビ」がない場合は、臨工の記事があってもフラグはFALSE

**出力**: 患者ごとに以下:
- 患者ID, 手術日_統一, ナビフラグ（TRUE/FALSE）, 判定理由

### star_items の扱い

**入力**: silver_orsys_star_items
**処理**: 特別な加工は不要。★項目をそのまま算定明細に表示
**箱1への統合**: 区分=「★項目」として他の区分（麻酔・検査・薬剤）と同列に表示

---

## データの3層構造（state_manager.py）

### 箱1: システム算定値

ルール適用後のデータを統一フォーマットに変換:

```python
{
    "row_id": "masui_001",           # 一意のID（区分_連番）
    "区分": "麻酔",                   # 麻酔 / 検査 / 薬剤 / ★項目 / ナビ
    "項目名": "閉鎖循環式全身麻酔５（その他）",
    "コード": "492700",
    "数量": "12:52",
    "単位": "時間",
}
```

区分ごとの数量・単位の対応:
- 麻酔: 数量=合計時間（HH:MM形式）、単位=時間
- 検査: 数量=回数（整数）、単位=回
- 薬剤: 数量=請求量、単位=請求単位
- ★項目: 数量=★項目の文字列全体（例: `★局所麻酔[1%Eキシロカイン][20]ml`）、単位=なし
- ナビ: 数量=「対象」or「非対象」or「判定不可」、単位=なし

### 箱2: 作業台（session_state内）

箱1に3列追加:
```python
{
    "row_id": "masui_001",
    "区分": "麻酔",
    "項目名": "閉鎖循環式全身麻酔５（その他）",
    "コード": "492700",
    "システム値": "12:52",
    "現在値": "12:52",
    "単位": "時間",
    "状態": "未変更",   # 未変更 / 修正済み / 削除 / 追加
}
```

### 箱3a: edit_history

「保存」ボタン押下時に差分を記録:
```json
{
    "processing_round": 1,
    "患者ID": "10000000",
    "手術日": "2026/01/01",
    "コード": "673400",
    "項目名": "血液ガス",
    "システム値": "6",
    "変更後の値": "4",
    "アクション": "修正",
    "保存日時": "2026-03-25T10:15:00",
    "バージョン": 1
}
```
- リセット操作も「アクション=リセット」として記録

### 箱3b: patient_status

```json
{
    "processing_round": 1,
    "患者ID": "10000000",
    "手術日": "2026/01/01",
    "ステータス": "確認待ち",
    "最終更新日時": "2026-03-25T10:00:00",
    "バージョン": 0
}
```

ステータス遷移: 確認待ち → 保存済み → 確定済み → （訂正PDF時）要再確認

---

## 画面仕様（4画面）

### 画面0: データアップロード（page_upload.py）

**アップロード対象**:
- PDF: 使用薬剤レポート、麻酔検査レポート
- CSV: 電カルデータ（orsys_special_search、kiji_n_pn_head等）

**画面レイアウト**:
```
■ PDFアップロード
  [ドラッグ＆ドロップ / 選択]（複数可）

■ CSVアップロード（電カルデータ）
  [ドラッグ＆ドロップ / 選択]（複数可）

[アップロード実行]

■ 処理状況
  ✅ ファイル送信完了
  ⏳ PDF解析中...
  ⬜ データ結合
  ⬜ 完了
```

**処理フロー**:
1. st.file_uploaderでファイル取得
2. OneLake APIでFabricのraw/フォルダに送信
3. REST APIでPDF解析Notebookを実行（pdfplumber）
4. CSVがあればCSV取り込みNotebookも実行
5. REST APIでDataflow Gen2（df_orbit_join）を実行
6. 完了メッセージ表示

### 画面1: 患者一覧（page_patient_list.py）

**表示**:
- 列: 患者ID、患者氏名、手術日、診療科、術式、ナビフラグ、ステータス
- ステータスバッジ: 確認待ち（黄）/保存済み（青）/確定済み（緑）/要再確認（赤）
- ナビフラグ: 「対象」の場合はバッジ表示
- 患者行クリック → 画面2に遷移

### 画面2: 算定明細（page_detail.py）

**表示レイアウト**:
```
┌───────────────────────────────────────────────────────┐
│ ← 一覧に戻る                                          │
│                                                       │
│ テスト太郎（10000000）  2026/01/01  耳鼻科              │
│ 術式: 咽頭喉頭頸部食道切除                               │
│ ステータス: 確認待ち                                     │
│ 麻酔開始時間: 08:38                                     │
│ ナビゲーション: 対象 ✅ （申込機器に「ナビ」+ 臨工記事あり）│
├───────┬──────────────────┬──────────┬────────┬──────────┤
│ 区分   │ 項目名            │ システム値│ 現在値  │ 操作      │
├───────┼──────────────────┼──────────┼────────┼──────────┤
│ 麻酔   │ 全身麻酔5（その他）│ 12:52    │ 12:52  │           │
│ 検査   │ 血液ガス          │ 6        │ [編集可]│ [戻す]    │
│ 薬剤   │ 酸素              │ 599.4    │ 599.4  │           │
│ ★項目 │ ★局所麻酔[...]    │ あり     │ あり   │           │
│ ナビ   │ ナビゲーション加算  │ 対象     │ 対象   │           │
├───────┴──────────────────┴──────────┴────────┴──────────┤
│ [＋ 項目を追加]  [全てリセット]  [保存]  [確定]           │
└───────────────────────────────────────────────────────┘
```

**ボタン動作**:

| ボタン | 動作 |
|--------|------|
| 修正（セル編集） | 箱2の該当行の「現在値」を更新。状態を「修正済み」に |
| 削除 | 箱2の該当行の状態を「削除」に。取り消し線表示 |
| 項目を追加 | 箱2に新しい行を追加。状態は「追加」 |
| 元に戻す（1行） | 箱2のその行を箱1のシステム値に戻す。状態を「未変更」に |
| 全てリセット | 箱2の全行を箱1に戻す。追加した行は削除 |
| 保存 | 楽観ロックチェック → 差分をedit_historyに書き込み → ステータスを「保存済み」に |
| 確定 | 未保存変更があれば警告。保存済みならステータスを「確定済み」に |

**楽観ロック**: 保存時にバージョン不一致なら「他で先に保存されています。再読み込みしてください。」

**未保存警告**: 変更がある状態でページ離脱・ブラウザ閉じ時に警告（全操作対象）

### 画面3: 出力（page_output.py）

**コピペ用出力**（患者ごと）:
```
■ テスト太郎（10000000）2026/01/01
492700+12:52,
670651+1,
500646+1,
673400+6,
540000+599.4,
237594+148.44,
...
/33+302124+1,     ← 術後鎮痛薬は末尾に/33+付き
```

- st.code で表示（コピーボタン付き）
- CSV / Excel ダウンロードボタン
- 出力対象選択: 確定済みのみ / 全患者

---

## Fabric接続（fabric_connection.py）

### 認証

```python
from msal import ConfidentialClientApplication

def get_sql_token() -> str:
    """SQL接続用トークン（スコープ: database.windows.net）"""

def get_fabric_token() -> str:
    """REST API / OneLake用トークン（スコープ: api.fabric.microsoft.com）"""
```

### 読み取り（pyodbc）

```python
import pyodbc, struct

def read_table(table_name: str) -> pd.DataFrame:
    """FabricのSilverテーブルをSQLで読み込んでDataFrameで返す"""
```

### ファイルアップロード（OneLake API）

```python
def upload_file_to_onelake(file_bytes: bytes, filename: str) -> bool:
    """ファイルをFabric LakehouseのFiles/rawフォルダにアップロード"""
```

### Notebook/Dataflow実行トリガー（REST API）

```python
def trigger_notebook(notebook_id: str, parameters: dict = None) -> str:
    """Fabric Notebookを実行。Locationヘッダーを返す"""

def trigger_dataflow(dataflow_id: str) -> str:
    """Dataflow Gen2を実行"""

def wait_for_job(job_location_url: str, timeout_seconds: int = 300) -> bool:
    """ジョブ完了を5秒間隔でポーリング"""
```

### 書き戻し（Notebook経由）

```python
def save_changes(patient_id, surgery_date, processing_round, changes, expected_version) -> bool:
    """保存ボタン: edit_historyに差分書き込み + patient_status更新"""

def confirm_patient(patient_id, surgery_date, processing_round, expected_version) -> bool:
    """確定ボタン: patient_statusを確定済みに"""
```

---

## 書き戻し用Notebook（Fabric上に手動作成: nb_orbit_writeback）

### テーブル作成SQL

```sql
CREATE TABLE IF NOT EXISTS edit_history (
    processing_round INT,
    patient_id STRING,
    surgery_date STRING,
    code STRING,
    item_name STRING,
    system_value STRING,
    changed_value STRING,
    action STRING,
    saved_at TIMESTAMP,
    version INT
) USING DELTA;

CREATE TABLE IF NOT EXISTS patient_status (
    processing_round INT,
    patient_id STRING,
    surgery_date STRING,
    status STRING,
    updated_at TIMESTAMP,
    version INT
) USING DELTA;
```

### パラメータ

- action: "save" / "confirm"
- patient_id, surgery_date, processing_round
- changes: JSON文字列（save時のみ）
- expected_version: 楽観ロック用

### 処理

save時: バージョンチェック → edit_historyにINSERT → patient_statusをMERGE（保存済み）
confirm時: patient_statusをMERGE（確定済み）

---

## Azure App Service デプロイ

### startup.sh

```bash
#!/bin/bash
apt-get update
apt-get install -y gnupg2 curl
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql18
streamlit run app.py --server.port 8000 --server.address 0.0.0.0
```

### requirements.txt

```
streamlit
pandas
pyodbc
msal
requests
python-dotenv
openpyxl
```

### 環境変数（.env テンプレート）

```
# === Azure AD 認証（値は.envに設定済み。ここには書かない） ===
FABRIC_TENANT_ID=
FABRIC_CLIENT_ID=
FABRIC_CLIENT_SECRET=
FABRIC_WORKSPACE_ID=52c1f5f2-b1b7-4ec0-a7c5-c82a6d1c5900
FABRIC_LAKEHOUSE_ID=3adc8e98-cc31-4363-adea-687e500165bf
FABRIC_SQL_ENDPOINT=

PDF_PARSE_NOTEBOOK_ID=
CSV_PARSE_NOTEBOOK_ID=
WRITEBACK_NOTEBOOK_ID=
DATAFLOW_ID=
```

---

## 手動作業チェックリスト

Claude Codeにこの指示書を渡す前に完了させること:

- [ ] Azure AD > アプリの登録 > orbit-streamlit-app 作成 → TENANT_ID, CLIENT_ID取得
- [ ] クライアントシークレット作成 → CLIENT_SECRET取得
- [ ] Fabricワークスペースにサービスプリンシパルを共同作成者として追加
- [ ] SQLエンドポイントURL確認 → SQL_ENDPOINT取得
- [ ] 書き戻し用Notebook（nb_orbit_writeback）をFabric上に作成 → WRITEBACK_NOTEBOOK_ID取得
- [ ] PDF解析Notebook / CSV取り込みNotebookのID確認
- [ ] Dataflow Gen2（df_orbit_join）のID確認 → DATAFLOW_ID取得
- [ ] .envファイルに全ての値を記入

---

## 決定済み仕様まとめ

### 変更修正の仕様

| 項目 | 決定内容 |
|------|----------|
| データの3層構造 | 箱1（システム算定値）→ 箱2（作業台）→ 箱3（保存・確定記録） |
| 「保存」と「確定」 | 別の操作 |
| リセットは何に戻す | 箱1（コンピュータの算定値）に戻す |
| リセット操作の記録 | 保存時にリセットの事実も記録する |
| 記録タイミング | 「保存」ボタン押下時にまとめて記録 |
| 未保存警告 | 全操作に対して、ページ離脱時に警告 |
| 訂正PDF | 過去の記録は残し、新しいprocessing_roundとして白紙再確認 |
| 同時編集対応 | 楽観ロック（バージョン番号で保存時にチェック） |
| 操作者の識別 | なし（ログイン機能なし） |

### 患者IDの正規化
- 整数変換（先頭ゼロ除去）。ゼロ埋めはしない

### 出力形式
- `コード+数量,` 形式
- 術後鎮痛薬は末尾に `/33+` 付き
- 患者ごとに1ブロック

---

## 注意事項

1. **コメントを詳細に入れること**: ユーザーはプログラミング初心者。全ての関数・処理ブロック・条件分岐にコメント
2. **日本語のUI**: 画面のテキスト・ボタン・エラーメッセージは全て日本語
3. **Aライン追加課金は保留**: 判定データ（動脈ライン準備列: シングル/三連/nan）は存在するが、シングルと三連で薬剤が変わるか藤原先生に確認中。回答後に実装に切り替え可能
4. **keika（経過記録）は画面に表示しない**: Silver層にも出力していない
5. **エラーハンドリング**: Fabric APIはtry-exceptで囲み、日本語エラーメッセージ表示
6. **タイムアウト表示**: Notebook実行中はスピナー+プログレスバーで待機中表示
