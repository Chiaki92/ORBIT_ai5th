# ORBIT Streamlitアプリ構築指示書（Claude Code用）

## 目的

この資料は、Claude CodeがGitHub上の既存コードを参照しながらORBITのStreamlitアプリを構築するための指示書です。

---

## 1. やりたいこと（全体像）

Gold層のExcel算定シート出力（Fabric Notebook）は完成済み。そのデータを**Streamlitアプリ上で表示・編集・コピペ出力**できるUIを構築する。

### アプリの3つの機能

| # | 機能 | 詳細 |
|---|---|---|
| ① | PDFアップロード→Lakehouse格納 | Streamlit `file_uploader` → OneLake API or Lakehouse Files/raw フォルダへ書き込み |
| ② | パイプライン実行ボタン | Fabric REST API経由でData Pipelineをトリガー |
| ③ | 算定結果の表示・編集・コピペ出力 | Gold層のExcel相当のデータを患者別に表示。薬剤は追加・修正・削除可能。貼り付けコードをワンクリックコピー |

---

## 2. GitHub上の既存コード

リポジトリ: `ORBIT_ai5th`（GitHub Private）

### 既存ファイル構成（参照すべきもの）

```
ORBIT_ai5th/
├── app.py                    ← 旧プロトタイプ（参考コード）
├── requirements.txt
├── data/                     ← テスト用CSVデータ
│   ├── masui_kensa_header_2.csv
│   ├── masui_kensa_masui_time_2.csv
│   ├── masui_kensa_kensa_2.csv
│   ├── masui_kensa_keika_2.csv
│   ├── yakuzai_header_2.csv
│   └── yakuzai_drugs_2.csv
└── .streamlit/
    └── config.toml
```

### 既存app.pyから引き継ぐパターン

1. **データ読み込み**: `@st.cache_data` + pyodbcでFabric上のGold層テーブルを直接読み込み
2. **患者選択**: サイドバーで患者一覧→選択→メインにデータ表示
3. **タブ構成**: 麻酔時間・検査・薬剤のタブ切り替え
4. **data_editor**: `st.data_editor` でテーブル編集（num_rows="fixed" or "dynamic"）
5. **変更履歴**: `st.session_state.change_log` に操作ログを蓄積→JSON永続化
6. **ステータス管理**: 患者ごとの「確認待ち」「確定済み」ステータス

---

## 3. 算定シートのデータ構造（Gold層Excel出力）

患者ごとに1シート。各シートのセクション構成：

### セクション1: 基本情報（行1〜8）— 全項目を漏れなく出すこと

```
行1: タイトル「ORBIT 手術薬剤コスト算定シート ／ {患者氏名} （ID: {患者ID}）」
行2: ▍基本情報
行3: 患者ID | 患者氏名 | 性別 | 年齢 | 生年月日
行4: 手術日 | 診療科 | 手術室 | 病棟 | 予定区分
行5: 確定術式
行6: 確定病名
行7: 手術時間（範囲＋合計） | 麻酔時間（範囲＋合計） | 入院外来 | 感染症 | 感染症有無
行8: 最初の麻酔開始時間（麻酔検査レポートより） | 麻酔科医 | 術者
```

※ 行8の「最初の麻酔開始時間」は深夜加算判定の根拠となる重要項目。必ず表示すること。
※ 感染症情報（行7の感染症・感染症有無）も省略しないこと。

### セクション2: 判定項目（行9〜12）

```
Aライン判定: あり/なし + 根拠テキスト
ナビゲーション判定: 対象/非対象 + 根拠テキスト
```

### セクション3: 麻酔時間（行13〜）

| 麻酔種別 | コード | 合計 | 時間帯 |
|---|---|---|---|
| 閉鎖循環式全身麻酔５（その他） | 492700 | 12:52 | 08:38～21:30 |

→ 貼り付けコード生成: `492700+12:52,`

### セクション4: 薬剤コスト（カテゴリ別）

カテゴリ: ■麻酔薬 / ■術後鎮痛薬 / ■注射薬 / ■その他薬剤 / ■Aライン / ■orsysリマークスより抽出

| 薬品名 | 課金コード | 使用量 | 単位 | 生食課金コード | 貼り付けコード |
|---|---|---|---|---|---|
| 酸素 | 540000 | 599.4 | L | | 540000+599.4, |
| 生理食塩液 ▲（50mL/本） | 302124 | 1 | 瓶 | | /33+302124+1, |

※ 術後鎮痛薬カテゴリの先頭行は `/33+` プレフィックス付き

### セクション5: 検査（行末尾）

| 項目 | コード | 回数 | 単位 |
|---|---|---|---|
| 経皮的動脈血酸素飽和度監視 | 670651 | | |
| 血液ガス | 673400 | 6 | 回 |

---

## 4. 薬剤セクションの編集要件（★重要）

### 4.1 できること

| 操作 | 対象 | 説明 |
|---|---|---|
| **使用量の修正** | 既存行 | 使用量セルを直接編集。貼り付けコードが自動再生成される |
| **行の追加** | 薬剤テーブル | 新しい薬剤行を追加できる（薬品名・課金コード・使用量を入力） |
| **行の削除** | 既存行 | 不要な薬剤行を削除できる |

### 4.2 編集のデータ永続化

- 編集内容は **state.json** に保存（既存app.pyのパターンを踏襲）
- 変更履歴（change_log）に以下を記録:
  - 操作種別: `セル編集` / `行追加` / `行削除`
  - 患者ID, 患者氏名, 術式, 診療科
  - 項目名, コード, 変更列, 変更前, 変更後

### 4.3 実装方法（st.data_editor）

```python
# 薬剤タブ: 追加・削除可能
edited_drugs = st.data_editor(
    display_drugs,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",  # ← "dynamic" で行の追加・削除が可能
    key=f"drugs_{current_pid}",
    column_config={
        "薬品名": st.column_config.TextColumn("薬品名", width="large"),
        "課金コード": st.column_config.TextColumn("課金コード", width="small"),
        "使用量": st.column_config.NumberColumn("使用量", width="small"),
        "単位": st.column_config.TextColumn("単位", width="small"),
        "貼り付けコード": st.column_config.TextColumn("貼り付けコード", width="medium", disabled=True),
    },
)
```

### 4.4 差分検知パターン（既存コードから引き継ぎ）

```python
def detect_and_log_edits(before_df, after_df, patient_id, patient_name, 
                         surgery_name, department, tab, item_name_col, code_col):
    """
    before_df（前回スナップショット）と after_df（編集後）を比較し、
    差分があればchange_logに記録する。
    """
    # 行数の変化を検出（追加 or 削除）
    if len(after_df) > len(before_df):
        # 行が追加された
        new_rows = after_df.iloc[len(before_df):]
        for _, row in new_rows.iterrows():
            add_change_log(
                action="行追加",
                detail=f"{row[item_name_col]} を追加",
                patient_id=patient_id,
                patient_name=patient_name,
                # ... 他のフィールド
            )
    elif len(after_df) < len(before_df):
        # 行が削除された
        # ...

    # セル値の変化を検出
    common_len = min(len(before_df), len(after_df))
    for row_idx in range(common_len):
        for col in after_df.columns:
            old_val = str(before_df.iloc[row_idx][col])
            new_val = str(after_df.iloc[row_idx][col])
            if old_val != new_val:
                add_change_log(
                    action="セル編集",
                    detail=f"{col} {old_val}→{new_val}",
                    # ...
                )

# スナップショットで重複記録を防止
snapshot_key = f"snapshot_drugs_{current_pid}"
if snapshot_key not in st.session_state:
    st.session_state[snapshot_key] = display_drugs.copy()

detect_and_log_edits(
    before_df=st.session_state[snapshot_key],
    after_df=edited_drugs,
    # ...
)
st.session_state[snapshot_key] = edited_drugs.copy()
```

---

## 5. コピペ用コード出力

### 5.1 貼り付けコードの生成ルール

```python
def generate_paste_code(row):
    """
    課金コード + 使用量 の貼り付け用文字列を生成する。
    """
    code = row.get("課金コード", "")
    amount = row.get("使用量", "")
    
    if pd.isna(code) or str(code).strip() == "" or str(code) == "—":
        return ""  # コード未設定の場合は空
    
    # 術後鎮痛薬カテゴリの先頭行は /33+ プレフィックス
    prefix = ""
    if row.get("_is_first_postop", False):
        prefix = "/33+"
    
    return f"{prefix}{code}+{amount},"
```

### 5.2 全コードコピー機能

Streamlitの `st.code` や `st.text_area` では使いにくいため、**カスタムHTMLコンポーネント**でクリップボードコピーボタンを実装する:

```python
import streamlit.components.v1 as components

def render_copy_button(codes_text):
    """
    全コードをワンクリックでクリップボードにコピーするHTMLボタンを表示。
    """
    html = f"""
    <div style="background:#1E293B; padding:10px 16px; border-radius:6px; 
                display:flex; align-items:center; gap:12px;">
        <code style="flex:1; color:#94A3B8; font-size:12px; 
                     white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            {codes_text[:80]}...
        </code>
        <button onclick="navigator.clipboard.writeText(`{codes_text}`).then(()=>{{
            this.textContent='✓ コピー済み'; 
            setTimeout(()=>this.textContent='📋 全コードをコピー', 1500);
        }})" style="background:#10B981; color:white; border:none; padding:6px 14px;
                    border-radius:4px; cursor:pointer; font-size:12px; font-weight:600;
                    white-space:nowrap;">
            📋 全コードをコピー
        </button>
    </div>
    """
    components.html(html, height=50)
```

### 5.3 個別行コピー

各行の貼り付けコードをクリックでコピーする場合も `components.html` で実装可能。ただし、Streamlitの `st.data_editor` 内ではカスタムHTMLが使えないため、テーブルの外に「コピペ用一覧」セクションを別途設ける。

---

## 6. Fabric接続方式（構築済み・そのまま使う）

pyodbc + サービスプリンシパル認証で接続確認済み。既存の接続コード・`.env` をそのまま使うこと。新規構築は不要。

### 読み取り: pyodbc（SQL エンドポイント）— 既存コード流用

```python
import pyodbc
import streamlit as st

@st.cache_data(ttl=60)  # 60秒キャッシュ（頻繁な再読み込みを防ぐ）
def load_silver_header():
    """Fabric上のSilver層ヘッダーテーブルを読み込む"""
    conn = pyodbc.connect(conn_str)
    df = pd.read_sql("SELECT * FROM silver_masui_kensa_header", conn)
    conn.close()
    return df
```

### パイプライン実行: REST API — 既存コード流用

```python
def trigger_pipeline(workspace_id, pipeline_id, access_token):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items/{pipeline_id}/jobs/instances?jobType=Pipeline"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post(url, headers=headers)
    return response.status_code
```

### 接続情報

`.env` ファイルに格納済み。GitHubリポジトリ上の既存 `.env` を参照すること。

---

## 7. 画面構成（UIモック準拠）

### サイドバー（モバイル対応: ハンバーガーメニュー）

```
┌─────────────────────┐
│ ORBIT               │
│ 手術薬剤コスト算定    │
├─────────────────────┤
│ 📂 PDFアップロード    │
│ [ドラッグ&ドロップ]   │
│  📄 masui_xxx.pdf    │
│  📄 yakuzai_xxx.pdf  │
├─────────────────────┤
│ ▶ パイプライン実行    │
│ ● 完了 — 5件(12秒)  │
├─────────────────────┤
│ 患者一覧(2026/01/01) │
│ ● テスト太郎 [確認済] │
│ ○ 山田テスト [確認待] │
│ ○ テスト三郎 [確認待] │
│ ○ テスト次郎 [確認待] │
│ ○ テスト花子 [確認待] │
└─────────────────────┘
```

### メイン画面

```
テスト太郎  ID:10000000 / 2026/01/01     [Excel出力] [確定]

▼ 基本情報
  患者ID: 10000000  氏名: テスト太郎  性別: 男  年齢: 61歳  生年月日: 1964/08/01
  手術日: 2026/01/01  診療科: 耳鼻科/形成外科/外科  手術室: 318  病棟: ３－１０  予定区分: 予定
  確定術式: 咽頭喉頭頸部食道切除
  確定病名: 下咽頭癌(20055085)
  手術時間: 09:38～20:52(11時間14分)  麻酔時間: 08:38～21:30(12時間52分)
  入院外来: 入院  感染症: 感染症EG/K2  感染症有無: なし
  最初の麻酔開始時間: 08:38  麻酔科医: 佐々木敬則  術者: 玉木久信,Ｓ２奥山槻一,...

▼ 判定項目
  Aライン判定: あり — 根拠テキスト
  ナビゲーション判定: 非対象 — 根拠テキスト

▼ 麻酔時間
  [テーブル: 麻酔種別 | コード | 合計 | 時間帯 | 貼り付けコード]

▼ 薬剤コスト  ✎ 編集可能
  [テーブル: 薬品名 | 課金コード | 使用量 | 単位 | 貼り付けコード]
  [＋ 薬剤を追加]
  ┌──────────────────────────────────────────────┐
  │ 540000+599.4, 237594+148.44, ...  [📋 全コピー] │
  └──────────────────────────────────────────────┘

▼ 検査
  [テーブル: 項目 | コード | 回数 | 単位]

[Excel出力] [確定]
```

---

## 8. ファイル構成（新規作成するもの）

```
ORBIT_ai5th/
├── app.py                    ← メインアプリ（書き換え）
├── requirements.txt          ← 更新
├── .env                      ← Fabric接続情報（Git管理外）
├── state.json                ← 変更履歴・ステータスの永続化
├── data/                     ← 旧テスト用CSV（参考用に残す。アプリでは使わない）
└── .streamlit/
    └── config.toml
```

### requirements.txt

```
streamlit>=1.30
pandas
openpyxl
pyodbc
azure-identity
python-dotenv
requests
```

---

## 9. 実装の優先順位

| 優先度 | 機能 | 工数目安 |
|---|---|---|
| P0 | Fabric接続でデータ読み込み（既存コード流用） | 15min |
| P0 | 算定データ表示（患者選択→全セクション表示） | 1h |
| P0 | 薬剤の編集（追加・修正・削除）+ 変更履歴 | 1h |
| P0 | 貼り付けコードのコピペUI | 30min |
| P1 | PDFアップロード画面 | 30min |
| P1 | パイプライン実行ボタン（既存REST APIコード流用） | 30min |
| P2 | Excel出力ボタン | 30min |

P0を先に完成させ、動作確認後にP1・P2を追加する。

---

## 10. 注意事項

1. **Excelの全項目を出すこと**: Gold層Excelに含まれる項目は1つも省略しない。特に「最初の麻酔開始時間（麻酔検査レポートより）」「感染症」「感染症有無」「術者」「麻酔科医」を落とさないこと。Silver層のCSVに含まれる「看護師_器械」「看護師_外回り」もデータとして存在するなら表示する。
2. **患者IDの正規化**: 整数変換（先頭ゼロ除去）。ゼロ埋めはしない。
2. **手術日フォーマット**: `2026/01/01` に統一（曜日なし）。
3. **麻酔時間の合算**: 同一患者＋同一コードの行は合計時間を合算。合算前の詳細（開始・終了）は展開表示。
4. **検査の回数ブランク**: 回数がブランクの場合は1として扱う。
5. **術後鎮痛薬**: 先頭行の貼り付けコードに `/33+` プレフィックスを付与。
6. **コメントは日本語で詳細に**: プログラミング初心者が読むため、コードのコメントは丁寧に書く。
7. **既存のデータ構造を変えない**: CSVのカラム名やデータ型は既存のまま使う。

---

## 11. UIモックファイル

UIデザインのモック（HTML）を別途用意しています。`orbit_mock.html` を参照してください。このモックの見た目・構成を可能な限りStreamlitで再現してください。Streamlitの制約で完全再現が難しい部分（コピペボタンなど）は `st.components.v1.html` で対応してください。
