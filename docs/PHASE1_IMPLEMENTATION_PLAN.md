# ORBIT Phase 1 実装計画: Fabric読み取り + ★項目 + ナビ判定 + UI更新

作成日: 2026/03/25
元指示書: ORBIT_統合実装指示書_v2.md

---

## 進捗チェックリスト

> **他のClaudeCodeセッションへ:** このチェックリストを見て、完了済みのステップをスキップし、未完了のステップから再開してください。完了したら該当行の `[ ]` を `[x]` に変更してください。

### Step 1: パッケージ初期化（依存なし）
- [x] `rules/__init__.py` 作成（docstringのみ）
- [x] `views/__init__.py` 作成（docstringのみ）

### Step 2: 依存パッケージ（依存なし）
- [x] `requirements.txt` に pyodbc, msal, requests, python-dotenv を追加
- [x] `pip install -r requirements.txt` で依存インストール確認

### Step 3: Fabric接続モジュール（依存なし）
- [x] `fabric_connection.py` 新規作成
- [x] `_get_env_or_raise(key)` 実装
- [x] `get_sql_token()` 実装（MSAL + スコープ: database.windows.net）
- [x] `_get_connection()` 実装（pyodbc + ODBC Driver 18 + トークン注入）
- [x] `read_table(table_name)` 実装
- [x] `is_fabric_available()` 実装
- [ ] 単体テスト: Fabricからテーブルを1つ読み込めることを確認（※Fabric環境が必要）

### Step 4: データローダー更新（Step 3に依存）
- [x] `_try_fabric_or_csv()` ヘルパー関数を追加
- [x] 列名マッピング実装（`手術日_統一` → `手術日`）
- [x] `load_header()` をFabric/CSVデュアルモードに変更
- [x] `load_masui_time()` をFabric/CSVデュアルモードに変更
- [x] `load_kensa()` をFabric/CSVデュアルモードに変更
- [x] `load_drugs()` をFabric/CSVデュアルモードに変更
- [x] `load_star_items()` 新規追加（Fabricのみ、空DF返却フォールバック）
- [x] `load_kiji()` 新規追加（Fabricのみ、空DF返却フォールバック）
- [x] フォールバック動作確認: Fabric未接続時にCSVで動作すること

### Step 5: ナビゲーション判定ルール（依存なし）
- [x] `rules/navi_rules.py` 新規作成
- [x] `_check_equipment(header_row)` 実装（「申込使用機器」に「ナビ」が含まれるか）
- [x] `_check_clinical_engineer(patient_id, surgery_date, kiji_df)` 実装（同日の臨工記事チェック）
- [x] `apply_navi_rules(header_df, kiji_df)` 実装（両条件を統合）
- [x] 空DataFrame入力時に「判定不可」を返すことを確認

### Step 6: state_manager.py 更新（依存なし）
- [x] `build_box1()` のシグネチャに `star_items_df=None, navi_df=None` を追加
- [x] ★項目の行生成ロジックを追加（区分="★項目"、コード=""、数量=★項目テキスト）
- [x] ナビ行の生成ロジックを追加（区分="ナビ"、数量=対象/非対象/判定不可）
- [x] 既存の引数のみで呼び出した場合の後方互換性を確認

### Step 7: page_detail.py 更新（Step 5, 6に依存）
- [x] `render_detail()` のシグネチャに `star_items_df=None, navi_df=None` を追加
- [x] 患者情報ヘッダーにナビ判定結果を表示（「データ未連携」→実際の値）
- [x] Silver追加フィールド表示を追加（確定術式_申込、動脈ライン準備、申込使用機器）
- [x] `build_box1()` 呼び出しに `star_items_df, navi_df` を追加
- [x] ナビ行の入力をselectbox（対象/非対象/判定不可）に変更
- [x] 項目追加の区分選択肢に「★項目」「ナビ」を追加

### Step 8: page_patient_list.py 更新（依存なし）
- [x] `render_patient_list()` のシグネチャに `navi_df=None` を追加
- [x] ナビバッジHTML定数を追加（対象=緑、非対象=グレー、判定不可=黄）
- [x] 各患者行にナビフラグ列を追加
- [x] カラムレイアウトを8列に拡張

### Step 9: page_output.py 更新（Step 6に依存）
- [x] `render_output()` のシグネチャに `star_items_df=None, navi_df=None` を追加
- [x] `_build_output_text()` で★項目/ナビ行をスキップするよう変更
- [x] `_build_download_df()` の `build_box1()` 呼び出しに star_items_df, navi_df を追加
- [x] `render_output()` 内の `build_box1()` 呼び出しも同様に更新

### Step 10: app.py 更新（全Stepに依存）
- [x] `from data_loader import load_star_items, load_kiji` を追加
- [x] `from rules.navi_rules import apply_navi_rules` を追加
- [x] `star_items_df = load_star_items()` を追加
- [x] `kiji_df = load_kiji()` を追加
- [x] `navi_result = apply_navi_rules(header_df, kiji_df)` を追加
- [x] Fabricフォールバック警告バナーを追加
- [x] サイドバーに「データ再読み込み」ボタンを追加
- [x] ページ選択肢に「アップロード」（Phase 2プレースホルダー）を追加
- [x] `render_patient_list(header_df, navi_df=navi_result)` に更新
- [x] `render_detail(...)` に `star_items_df, navi_df=navi_result` を追加
- [x] `render_output(...)` に `star_items_df, navi_df=navi_result` を追加

### 検証（全Step完了後）
- [x] CSVフォールバックテスト: .env空でアプリ起動、既存機能が動作
- [ ] Fabric接続テスト: 正しい.envで6テーブル読み込み（※Fabric環境が必要）
- [x] ★項目表示テスト: 算定明細に★項目が表示される
- [x] ナビ判定テスト: 対象/非対象が正しく判定される
- [x] 出力テスト: コピペ出力に★/ナビが含まれない、CSV/Excelには含まれる
- [x] 編集テスト: ★/ナビ行の編集・保存・リセットが動作する

---

## Context

ORBIT（手術算定支援システム）は現在CSVベースのプロトタイプとして動作している。v2指示書では6つのSilverテーブル（Fabric Lakehouse上）への接続、★コスト項目の表示、ナビゲーション加算判定の追加が求められている。★項目とナビ判定用のデータはFabricにしかないため、Phase 1にFabric SQL読み取り接続を含める。

**Phase 1の範囲:**
- Fabric SQL読み取り接続（fabric_connection.py）
- data_loader.pyのFabric/CSVデュアルモード化
- ★項目の箱1統合・画面表示
- ナビゲーション加算判定（navi_rules.py）
- 全画面のUI更新
- アップロード画面のプレースホルダー

**Phase 2（今回は対象外）:** アップロード画面、Fabric書き戻し、Azure App Serviceデプロイ

**Aライン追加課金:** 藤原先生からの回答待ち。マスター保持のみで自動追加は実装しない

---

## 実装順序（依存関係順）

```
Step 1: rules/__init__.py, views/__init__.py（依存なし）
Step 2: requirements.txt 更新（依存なし）
Step 3: fabric_connection.py 新規作成（依存なし）
Step 4: data_loader.py 更新（Step 3に依存）
Step 5: rules/navi_rules.py 新規作成（依存なし）
Step 6: state_manager.py 更新（依存なし）
Step 7: views/page_detail.py 更新（Step 5, 6に依存）
Step 8: views/page_patient_list.py 更新（依存なし）
Step 9: views/page_output.py 更新（Step 6に依存）
Step 10: app.py 更新（全Stepに依存）
```

---

## Step 1: `rules/__init__.py` / `views/__init__.py`（新規）

空のパッケージ初期化ファイル。docstringのみ。

---

## Step 2: `requirements.txt`（更新）

追加する依存:
```
pyodbc>=5.1.0
msal>=1.28.0
requests>=2.31.0
python-dotenv>=1.0.0
```

---

## Step 3: `fabric_connection.py`（新規 〜120行）

Fabric SQL接続の全機能を集約するモジュール。

**関数一覧:**
- `_get_env_or_raise(key)` — 環境変数取得（未設定時エラー）
- `get_sql_token()` — MSAL経由でSQLトークン取得（スコープ: `https://database.windows.net/.default`）
- `_get_connection()` — pyodbc接続作成（ODBC Driver 18 + トークン注入）
- `read_table(table_name)` — `SELECT * FROM {table_name}` → DataFrame
- `is_fabric_available()` — 環境変数の存在チェック（接続テストはしない）

**トークン注入パターン:**
```python
token_bytes = token.encode("UTF-16-LE")
token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
SQL_COPT_SS_ACCESS_TOKEN = 1256
conn = pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})
```

**必要な環境変数:** FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET, FABRIC_SQL_ENDPOINT

---

## Step 4: `data_loader.py`（更新 〜280行）

### 新規関数
- `_try_fabric_or_csv(table_name, csv_filename)` — Fabric優先、失敗時CSV。Fabricデータの`手術日_統一`→`手術日`にリネーム
- `load_star_items()` — `silver_orsys_star_items`（Fabricのみ、CSV無し。未接続時は空DataFrame返却）
- `load_kiji()` — `silver_kiji_n_pn_head`（Fabricのみ、同上）

### 既存関数の変更
各`load_*`関数を `_try_fabric_or_csv()` 経由に変更:

| 関数 | Fabricテーブル名 | CSVファイル名 |
|------|-----------------|--------------|
| load_header() | silver_masui_kensa_header | masui_kensa_header.csv |
| load_masui_time() | silver_masui_kensa_masui_time | masui_kensa_masui_time.csv |
| load_kensa() | silver_masui_kensa_kensa | masui_kensa_kensa.csv |
| load_drugs() | silver_yakuzai_drugs | yakuzai_drugs.csv |
| load_keika() | （変更なし、CSVのまま） | masui_kensa_keika.csv |

### 列名マッピング
Fabricの`手術日_統一` → 下流コード互換のため `手術日` にリネーム（_try_fabric_or_csv内で処理）

### フォールバック動作
Fabric接続失敗時に `st.session_state["_fabric_fallback"] = True` をセット → app.pyで警告バナー表示

---

## Step 5: `rules/navi_rules.py`（新規 〜90行）

### 判定ロジック
1. `_check_equipment(header_row)` — headerの「申込使用機器」列に「ナビ」文字列が含まれるか
2. `_check_clinical_engineer(patient_id, surgery_date, kiji_df)` — 同日（手術日 = 記載日_統一）に臨床工学技士の記事があるか
3. `apply_navi_rules(header_df, kiji_df)` — 両方YES→「対象」、それ以外→「非対象」、データ不足→「判定不可」

### 出力
DataFrame（列: 患者ID, 手術日, ナビフラグ, 判定理由）

### 注意点
- 「申込使用機器」列がない場合（CSV環境）→「判定不可」
- kiji_dfが空の場合（Fabric未接続）→「判定不可」
- 日付フォーマット正規化: `pd.to_datetime()` で比較

---

## Step 6: `state_manager.py`（更新）

### build_box1() のシグネチャ変更
```python
def build_box1(
    patient_id, masui_df, kensa_df, drugs_df,
    star_items_df=None,  # 新規
    navi_df=None,         # 新規
) -> list:
```

### 追加される行生成ロジック

**★項目（術後鎮痛薬の後に追加）:**
```python
{
    "row_id": "star_001",
    "区分": "★項目",
    "項目名": "★局所麻酔[1%Eキシロカイン][20]ml",  # ★項目テキスト
    "コード": "",          # コードなし
    "数量": "★局所麻酔[1%Eキシロカイン][20]ml",  # テキスト全体
    "単位": "",
}
```

**ナビ（最後に追加）:**
```python
{
    "row_id": "navi_001",
    "区分": "ナビ",
    "項目名": "ナビゲーション加算（判定理由）",
    "コード": "",
    "数量": "対象",        # or "非対象" or "判定不可"
    "単位": "",
}
```

---

## Step 7: `views/page_detail.py`（更新）

### render_detail() シグネチャ変更
```python
def render_detail(header_df, masui_df, kensa_df, drugs_df,
                  star_items_df=None, navi_df=None):
```

### 変更箇所

1. **患者情報ヘッダー拡張**（現在の119行目付近）:
   - ナビ判定: 「データ未連携」→ 実際の判定結果を表示
   - Silver追加フィールド表示: 確定術式_申込、動脈ライン準備、申込使用機器（存在時のみ）

2. **build_box1() 呼び出し**（現在の124行目）:
   - `star_items_df=star_items_df, navi_df=navi_df` を追加

3. **ナビ行の入力UI**:
   - 区分=="ナビ"の場合: `text_input` の代わりに `selectbox`（対象/非対象/判定不可）

4. **項目追加の区分選択肢**:
   - `["麻酔", "検査", "薬剤"]` → `["麻酔", "検査", "薬剤", "★項目", "ナビ"]`

---

## Step 8: `views/page_patient_list.py`（更新）

### render_patient_list() シグネチャ変更
```python
def render_patient_list(header_df, navi_df=None):
```

### 変更箇所
- ナビバッジHTML定数を追加（対象=緑、非対象=グレー、判定不可=黄）
- 各患者行にナビフラグ列を追加
- カラムレイアウトを8列に拡張:
  `[患者ID, 氏名, 手術日, 診療科, 術式, ナビ, ステータス, 詳細ボタン]`

---

## Step 9: `views/page_output.py`（更新）

### 変更箇所

1. **render_output() シグネチャ変更:**
   ```python
   def render_output(header_df, masui_df, kensa_df, drugs_df,
                     star_items_df=None, navi_df=None):
   ```

2. **build_box1() 呼び出しの更新:** star_items_df, navi_df を渡す

3. **_build_output_text() の更新:** ★項目とナビ行はコピペ出力からスキップ（コードがないため `code+qty,` 形式に合わない）

4. **_build_download_df() の更新:** build_box1()にstar_items_df, navi_dfを渡す（CSV/Excelには含める）

---

## Step 10: `app.py`（更新）

### 変更箇所

1. **import追加:**
   - `from data_loader import load_star_items, load_kiji`
   - `from rules.navi_rules import apply_navi_rules`

2. **データ読み込み追加:**
   ```python
   star_items_df = load_star_items()
   kiji_df = load_kiji()
   ```

3. **ルール適用追加:**
   ```python
   navi_result = apply_navi_rules(header_df, kiji_df)
   ```

4. **Fabricフォールバック警告:**
   ```python
   if st.session_state.get("_fabric_fallback", False):
       st.warning("⚠️ Fabricに接続できないため、ローカルCSVデータを使用しています。")
   ```

5. **サイドバーにデータ再読み込みボタン追加**

6. **ページ選択肢に「アップロード」追加（Phase 2プレースホルダー）**

7. **各画面呼び出しにstar_items_df, navi_resultを渡す**

---

## 変更ファイル一覧

| ファイル | 操作 | 概要 |
|---------|------|------|
| rules/__init__.py | 新規 | 空パッケージ |
| views/__init__.py | 新規 | 空パッケージ |
| requirements.txt | 更新 | pyodbc, msal, requests, python-dotenv追加 |
| fabric_connection.py | 新規 | Fabric SQL接続モジュール（〜120行） |
| data_loader.py | 更新 | Fabric/CSVデュアルモード + 2関数追加 |
| rules/navi_rules.py | 新規 | ナビゲーション判定ルール（〜90行） |
| state_manager.py | 更新 | build_box1()に★項目/ナビ追加 |
| views/page_detail.py | 更新 | ヘッダー拡張、ナビ表示、★項目対応 |
| views/page_patient_list.py | 更新 | ナビフラグ列追加 |
| views/page_output.py | 更新 | ★/ナビスキップ、シグネチャ変更 |
| app.py | 更新 | 新データ読み込み・ルール適用・画面接続 |

---

## 検証方法

1. **CSVフォールバックテスト:** .envのFabric認証情報を空にし、アプリが従来通りCSVで動作することを確認。★項目/ナビは「判定不可」表示
2. **Fabric接続テスト:** 正しい.envでFabricから6テーブルを読み込めることを確認
3. **★項目表示テスト:** 算定明細画面に★項目が区分「★項目」として表示されることを確認
4. **ナビ判定テスト:** 「申込使用機器」に「ナビ」が含まれる患者で判定が正しく動作することを確認
5. **出力テスト:** コピペ出力に★項目/ナビが含まれないこと、CSV/Excelには含まれることを確認
6. **編集テスト:** ★項目/ナビ行の編集・保存・リセットが正常に動作することを確認

---

## 参考: 元指示書との対応表

| 元指示書セクション | Phase 1対応 | Phase 2対応 |
|---|---|---|
| Silver層テーブル構成（6テーブル） | data_loader.pyで全6テーブル対応 | - |
| データ読み込み（data_loader.py） | Fabric/CSVデュアルモード化 | - |
| 算定ルール（rules/） | navi_rules.py追加 | - |
| データの3層構造（state_manager.py） | ★項目/ナビの箱1統合 | Fabric書き戻し |
| 画面0: アップロード | プレースホルダーのみ | 完全実装 |
| 画面1: 患者一覧 | ナビフラグ追加 | - |
| 画面2: 算定明細 | ★項目/ナビ表示・編集 | - |
| 画面3: 出力 | ★/ナビスキップ対応 | - |
| Fabric接続 | SQL読み取りのみ | アップロード・Notebook実行・書き戻し |
| Azure App Service デプロイ | - | startup.sh + デプロイ |
