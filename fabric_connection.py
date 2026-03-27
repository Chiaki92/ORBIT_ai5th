"""
fabric_connection.py — Microsoft Fabric接続モジュール

FabricのSQL読み取り、OneLakeファイルアップロード、
Notebook/Dataflow実行トリガーの機能を提供する。
認証にはAzure ADサービスプリンシパル（MSAL）を使用する。

必要な環境変数:
  FABRIC_TENANT_ID     — AzureテナントID
  FABRIC_CLIENT_ID     — アプリケーション（クライアント）ID
  FABRIC_CLIENT_SECRET — クライアントシークレット
  FABRIC_SQL_ENDPOINT  — Fabric SQLエンドポイントURL
  FABRIC_WORKSPACE_ID    — FabricワークスペースID（アップロード・ジョブ実行用）
  FABRIC_LAKEHOUSE_ID    — LakehouseのID（OneLakeファイルアップロード用）
  NOTEBOOK_YAKUZAI_ID    — 使用薬剤PDF解析NotebookのID
  NOTEBOOK_MASUI_KENSA_ID — 麻酔検査PDF解析NotebookのID
  NOTEBOOK_CSV_IMPORT_ID — CSV取り込みNotebookのID
  DATAFLOW_ID            — Dataflow Gen2のID
"""

import os
import struct
import time
import logging

import pandas as pd
import requests

# .envファイルから環境変数を読み込む（存在する場合のみ）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# 環境変数の取得
# =============================================================================

def _get_env_or_raise(key: str) -> str:
    """
    環境変数を取得する。未設定の場合はエラーを送出する。

    引数:
      key: 環境変数名

    戻り値:
      環境変数の値

    例外:
      EnvironmentError: 環境変数が未設定の場合
    """
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"環境変数 {key} が設定されていません。.envファイルを確認してください。")
    return value


# =============================================================================
# トークンの取得（MSAL認証）
# =============================================================================

def _get_token(scope: str) -> str:
    """
    MSAL（Microsoft Authentication Library）を使用して、
    指定されたスコープのアクセストークンを取得する汎用関数。

    この関数は内部で使われる共通処理。
    外部からは get_sql_token() / get_storage_token() / get_fabric_api_token() を使う。

    引数:
      scope: OAuthスコープ文字列
        - SQL用: "https://database.windows.net/.default"
        - OneLake用: "https://storage.azure.com/.default"
        - Fabric REST API用: "https://api.fabric.microsoft.com/.default"

    戻り値:
      アクセストークン文字列

    例外:
      RuntimeError: トークン取得に失敗した場合
    """
    from msal import ConfidentialClientApplication

    # 環境変数から認証情報を取得（AZURE_* を優先、FABRIC_* にフォールバック）
    tenant_id = os.environ.get("AZURE_TENANT_ID") or _get_env_or_raise("FABRIC_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID") or _get_env_or_raise("FABRIC_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET") or _get_env_or_raise("FABRIC_CLIENT_SECRET")

    # MSALクライアントの作成
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )

    # トークンの取得
    result = app.acquire_token_for_client(scopes=[scope])

    if "access_token" not in result:
        error_desc = result.get("error_description", "不明なエラー")
        raise RuntimeError(f"トークンの取得に失敗しました（スコープ: {scope}）: {error_desc}")

    return result["access_token"]


def get_sql_token() -> str:
    """
    SQL接続用のアクセストークンを取得する。
    スコープ: https://database.windows.net/.default

    戻り値:
      アクセストークン文字列
    """
    return _get_token("https://database.windows.net/.default")


def get_storage_token() -> str:
    """
    OneLakeファイルアップロード用のアクセストークンを取得する。
    スコープ: https://storage.azure.com/.default

    戻り値:
      アクセストークン文字列
    """
    return _get_token("https://storage.azure.com/.default")


def get_fabric_api_token() -> str:
    """
    Fabric REST API用のアクセストークンを取得する。
    Notebook実行やDataflow実行のトリガーに使用する。
    スコープ: https://api.fabric.microsoft.com/.default

    戻り値:
      アクセストークン文字列
    """
    return _get_token("https://api.fabric.microsoft.com/.default")


# =============================================================================
# pyodbc接続の作成
# =============================================================================

def _get_connection():
    """
    FabricのSQLエンドポイントにpyodbc接続を作成する。
    トークン注入パターンでAzure AD認証を行う。

    戻り値:
      pyodbc.Connection オブジェクト
    """
    import pyodbc

    # SQLエンドポイントのURLを取得
    sql_endpoint = _get_env_or_raise("FABRIC_SQL_ENDPOINT")

    # アクセストークンを取得
    token = get_sql_token()

    # トークンをUTF-16-LEにエンコードしてバイト構造体に変換
    # （pyodbcのAzure AD認証に必要なフォーマット）
    token_bytes = token.encode("UTF-16-LE")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    # pyodbcの接続文字列
    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={sql_endpoint};"
        f"Database=orbit_lakehouse;"
        f"Encrypt=Yes;"
        f"TrustServerCertificate=No;"
    )

    # SQL_COPT_SS_ACCESS_TOKEN: トークンを接続属性として注入
    SQL_COPT_SS_ACCESS_TOKEN = 1256
    conn = pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})

    return conn


# =============================================================================
# テーブル読み取り
# =============================================================================

def read_table(table_name: str) -> pd.DataFrame:
    """
    Fabricの指定テーブルからSELECT * でデータを取得し、DataFrameとして返す。

    引数:
      table_name: テーブル名（例: "silver_masui_kensa_header"）

    戻り値:
      テーブルの全行を含むDataFrame

    例外:
      各種接続・SQL実行エラー
    """
    conn = _get_connection()
    try:
        # テーブル名のサニタイズ（英数字・アンダースコアのみ許可）
        safe_name = "".join(c for c in table_name if c.isalnum() or c == "_")
        query = f"SELECT * FROM {safe_name}"
        df = pd.read_sql(query, conn)
        return df
    finally:
        conn.close()


# =============================================================================
# OneLakeファイルアップロード
# =============================================================================

def upload_file_to_onelake(file_bytes: bytes, filename: str, subfolder: str) -> bool:
    """
    ファイルをFabric LakehouseのFiles/raw/{subfolder}/にアップロードする。

    OneLakeはADLS Gen2互換APIを使用しており、以下の3ステップでアップロードする:
      1. PUT  ?resource=file            — 空のファイルを作成
      2. PATCH ?action=append&position=0 — ファイルの中身を書き込む
      3. PATCH ?action=flush&position=N  — 書き込みを確定する（Nはファイルサイズ）

    引数:
      file_bytes: アップロードするファイルの内容（バイト列）
      filename:   ファイル名（例: "report.pdf"）
      subfolder:  rawフォルダ内のサブフォルダ名
                  "yakuzai" / "masui_kensa" / "orsys" / "karte_kiji"

    戻り値:
      成功した場合 True

    例外:
      RuntimeError: アップロードに失敗した場合
    """
    # 環境変数からワークスペースIDとレイクハウスIDを取得
    workspace_id = _get_env_or_raise("FABRIC_WORKSPACE_ID")
    lakehouse_id = _get_env_or_raise("FABRIC_LAKEHOUSE_ID")

    # OneLake用のアクセストークンを取得
    token = get_storage_token()

    # アップロード先のURLを組み立てる
    # 例: https://onelake.dfs.fabric.microsoft.com/{workspace}/{lakehouse}/Files/raw/yakuzai/report.pdf
    base_url = "https://onelake.dfs.fabric.microsoft.com"
    path = f"/{workspace_id}/{lakehouse_id}/Files/raw/{subfolder}/{filename}"
    url = f"{base_url}{path}"

    headers = {"Authorization": f"Bearer {token}"}

    # --- ステップ1: 空のファイルを作成 ---
    resp1 = requests.put(f"{url}?resource=file", headers=headers)
    if resp1.status_code not in (200, 201):
        raise RuntimeError(
            f"OneLakeファイル作成に失敗しました（{filename}）: "
            f"ステータス {resp1.status_code}, {resp1.text}"
        )

    # --- ステップ2: ファイルの中身を書き込む ---
    resp2 = requests.patch(
        f"{url}?action=append&position=0",
        headers={**headers, "Content-Type": "application/octet-stream"},
        data=file_bytes,
    )
    if resp2.status_code not in (200, 202):
        raise RuntimeError(
            f"OneLakeファイル書き込みに失敗しました（{filename}）: "
            f"ステータス {resp2.status_code}, {resp2.text}"
        )

    # --- ステップ3: 書き込みを確定する ---
    content_length = len(file_bytes)
    resp3 = requests.patch(
        f"{url}?action=flush&position={content_length}",
        headers=headers,
    )
    if resp3.status_code not in (200,):
        raise RuntimeError(
            f"OneLakeファイル確定に失敗しました（{filename}）: "
            f"ステータス {resp3.status_code}, {resp3.text}"
        )

    logger.info(f"OneLakeにアップロード完了: raw/{subfolder}/{filename} ({content_length:,} bytes)")
    return True


def download_file_from_onelake(filename: str, subfolder: str, folder: str = "raw") -> bytes | None:
    """
    Fabric LakehouseのFiles/{folder}/{subfolder}/{filename}からファイルをダウンロードする。

    元データ確認機能で使用。アップロード済みのPDF/CSVを取得して
    ブラウザ上で表示するために使う。

    引数:
      filename:   ファイル名（例: "report.pdf"）
      subfolder:  folder配下のサブフォルダ名（未指定可）
      folder:     Files配下のフォルダ名（既定: "raw"）

    戻り値:
      ファイルの内容（バイト列）。取得に失敗した場合はNone。
    """
    try:
        workspace_id = _get_env_or_raise("FABRIC_WORKSPACE_ID")
        lakehouse_id = _get_env_or_raise("FABRIC_LAKEHOUSE_ID")
    except RuntimeError:
        logger.warning("Fabric環境変数が未設定のため、OneLakeからのダウンロードをスキップ")
        return None

    token = get_storage_token()

    base_url = "https://onelake.dfs.fabric.microsoft.com"
    normalized_folder = str(folder or "").strip().strip("/")
    normalized_subfolder = str(subfolder or "").strip().strip("/")
    path_parts = [p for p in (normalized_folder, normalized_subfolder) if p]
    joined_path = "/".join(path_parts)
    path = f"/{workspace_id}/{lakehouse_id}/Files/{joined_path}/{filename}"
    url = f"{base_url}{path}"

    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            logger.info(f"OneLakeからダウンロード完了: {joined_path}/{filename} ({len(resp.content):,} bytes)")
            return resp.content
        else:
            logger.warning(
                f"OneLakeからのダウンロードに失敗: {joined_path}/{filename} "
                f"ステータス {resp.status_code}"
            )
            return None
    except Exception as e:
        logger.error(f"OneLakeダウンロードエラー: {e}")
        return None


# =============================================================================
# Notebook実行トリガー
# =============================================================================

def trigger_notebook(notebook_id: str, parameters: dict | None = None) -> str:
    """
    Fabric Notebookの実行をトリガーする（非同期実行）。

    Fabric REST APIを使用してNotebookジョブを開始する。
    ジョブの完了を待つには、戻り値のURLを wait_for_job() に渡す。

    引数:
      notebook_id: 実行するNotebookのID（GUID文字列）
      parameters:  Notebookに渡すパラメータ（省略可）

    戻り値:
      ジョブ監視用のURL（Locationヘッダーの値）
      このURLを wait_for_job() に渡して完了を待つ

    例外:
      RuntimeError: トリガーに失敗した場合
    """
    workspace_id = _get_env_or_raise("FABRIC_WORKSPACE_ID")
    token = get_fabric_api_token()

    # Fabric REST APIのNotebook実行エンドポイント
    url = (
        f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
        f"/items/{notebook_id}/jobs/instances?jobType=RunNotebook"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # パラメータがある場合はリクエストボディに含める
    body = None
    if parameters:
        body = {"executionData": {"parameters": parameters}}

    resp = requests.post(url, headers=headers, json=body)

    # 202 Accepted = ジョブが正常に開始された
    if resp.status_code != 202:
        raise RuntimeError(
            f"Notebook実行のトリガーに失敗しました（ID: {notebook_id}）: "
            f"ステータス {resp.status_code}, {resp.text}"
        )

    # レスポンスのLocationヘッダーにジョブ監視URLが含まれる
    location = resp.headers.get("Location")
    if not location:
        raise RuntimeError(
            f"Notebook実行のレスポンスにLocationヘッダーがありません（ID: {notebook_id}）"
        )

    logger.info(f"Notebook実行をトリガーしました: {notebook_id}")
    return location


# =============================================================================
# Pipeline / Dataflow 実行トリガー
# =============================================================================

def trigger_pipeline(pipeline_id: str) -> str:
    """
    Fabric Pipeline の実行をトリガーする（非同期実行）。

    引数:
      pipeline_id: 実行するPipelineのID（GUID文字列）

    戻り値:
      ジョブ監視用のURL（Locationヘッダーの値）
    """
    workspace_id = _get_env_or_raise("FABRIC_WORKSPACE_ID")
    token = get_fabric_api_token()

    # Fabric Pipeline は jobType=Pipeline で実行
    url = (
        f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
        f"/items/{pipeline_id}/jobs/instances?jobType=Pipeline"
    )

    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(url, headers=headers)
    if resp.status_code != 202:
        raise RuntimeError(
            f"Pipeline実行のトリガーに失敗しました（ID: {pipeline_id}）: "
            f"ステータス {resp.status_code}, {resp.text}"
        )

    location = resp.headers.get("Location")
    if not location:
        raise RuntimeError(
            f"Pipeline実行のレスポンスにLocationヘッダーがありません（ID: {pipeline_id}）"
        )

    logger.info(f"Pipeline実行をトリガーしました: {pipeline_id}")
    return location

def trigger_dataflow(dataflow_id: str) -> str:
    """
    Dataflow Gen2の実行をトリガーする（非同期実行）。

    Fabric REST APIを使用してDataflowジョブを開始する。
    ジョブの完了を待つには、戻り値のURLを wait_for_job() に渡す。

    引数:
      dataflow_id: 実行するDataflowのID（GUID文字列）

    戻り値:
      ジョブ監視用のURL（Locationヘッダーの値）
      このURLを wait_for_job() に渡して完了を待つ

    例外:
      RuntimeError: トリガーに失敗した場合
    """
    workspace_id = _get_env_or_raise("FABRIC_WORKSPACE_ID")
    token = get_fabric_api_token()

    # Fabric REST APIのDataflow実行エンドポイント
    # Dataflow Gen2 は jobType=Refresh で実行する
    url = (
        f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
        f"/items/{dataflow_id}/jobs/instances?jobType=Refresh"
    )

    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.post(url, headers=headers)

    # 202 Accepted = ジョブが正常に開始された
    if resp.status_code != 202:
        raise RuntimeError(
            f"Dataflow実行のトリガーに失敗しました（ID: {dataflow_id}）: "
            f"ステータス {resp.status_code}, {resp.text}"
        )

    # レスポンスのLocationヘッダーにジョブ監視URLが含まれる
    location = resp.headers.get("Location")
    if not location:
        raise RuntimeError(
            f"Dataflow実行のレスポンスにLocationヘッダーがありません（ID: {dataflow_id}）"
        )

    logger.info(f"Dataflow実行をトリガーしました: {dataflow_id}")
    return location


# =============================================================================
# ジョブ完了待機（ポーリング）
# =============================================================================

def wait_for_job(job_location_url: str, timeout_seconds: int = 300) -> bool:
    """
    Fabricジョブの完了をポーリングで待機する。

    trigger_notebook() や trigger_dataflow() が返したジョブ監視URLに対して
    5秒間隔でGETリクエストを送り、ジョブの状態を確認する。

    引数:
      job_location_url: trigger_notebook/trigger_dataflow が返したURL
      timeout_seconds:  タイムアウト秒数（デフォルト300秒=5分）

    戻り値:
      ジョブが正常に完了した場合 True

    例外:
      RuntimeError:  ジョブが失敗またはキャンセルされた場合
      TimeoutError: 指定時間内に完了しなかった場合
    """
    token = get_fabric_api_token()
    headers = {"Authorization": f"Bearer {token}"}

    start_time = time.time()

    while True:
        # タイムアウトチェック
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise TimeoutError(
                f"ジョブがタイムアウトしました（{timeout_seconds}秒経過）。"
                "Fabricポータルでジョブの状態を確認してください。"
            )

        # ジョブのステータスを取得
        resp = requests.get(job_location_url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(
                f"ジョブステータスの取得に失敗しました: "
                f"ステータス {resp.status_code}, {resp.text}"
            )

        data = resp.json()
        status = data.get("status", "Unknown")

        # 完了した場合
        if status == "Completed":
            logger.info("ジョブが正常に完了しました")
            return True

        # 失敗またはキャンセルされた場合
        if status in ("Failed", "Cancelled"):
            failure_reason = data.get("failureReason", {}) or {}
            error_code = failure_reason.get("errorCode", "")
            error_msg = failure_reason.get("message", "詳細不明")

            # Notebook をサービスプリンシパルで起動した際に起こりやすい既知エラー
            if error_code == "UserAccessTokenException":
                raise RuntimeError(
                    "ジョブがFailedになりました: Job failed to start: unable to acquire user token\n"
                    "Notebook実行はユーザー委任トークンを要求しています。"
                    "現在のサービスプリンシパル認証では起動できません。\n"
                    "対応案: 1) Fabric UIからNotebookを手動実行する "
                    "2) ユーザー委任トークンでAPIを呼ぶ "
                    "3) Notebook実行をパイプライン/別経路に移す"
                )

            raise RuntimeError(f"ジョブが{status}になりました: [{error_code}] {error_msg}")

        # まだ実行中の場合は5秒待ってから再チェック
        time.sleep(5)


# =============================================================================
# Fabric接続可否チェック
# =============================================================================

def is_fabric_available() -> bool:
    """
    Fabric接続に必要な環境変数がすべて設定されているかチェックする。
    実際の接続テストは行わない（起動時間短縮のため）。

    戻り値:
      全環境変数が設定されていれば True、1つでも未設定なら False
    """
    # AZURE_* または FABRIC_* のいずれかが設定されていればOK
    has_tenant = os.environ.get("AZURE_TENANT_ID") or os.environ.get("FABRIC_TENANT_ID")
    has_client = os.environ.get("AZURE_CLIENT_ID") or os.environ.get("FABRIC_CLIENT_ID")
    has_secret = os.environ.get("AZURE_CLIENT_SECRET") or os.environ.get("FABRIC_CLIENT_SECRET")
    has_endpoint = os.environ.get("FABRIC_SQL_ENDPOINT")
    return all([has_tenant, has_client, has_secret, has_endpoint])
