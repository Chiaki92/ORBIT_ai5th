#!/bin/bash
# =============================================================
# ORBIT Streamlit アプリ — Azure App Service スタートアップスクリプト
# =============================================================
# このスクリプトは Azure App Service の「スタートアップコマンド」に設定する。
# やっていること:
#   1. Microsoft ODBC Driver 18 for SQL Server をインストール
#      （pyodbc で Fabric SQL エンドポイントに接続するために必要）
#   2. Streamlit アプリを起動
# =============================================================

# --- 1. ODBCドライバのインストール ---
# Azure App Service の Linux 環境にはデフォルトで入っていないため、
# 起動のたびにインストールする（コンテナが再作成されると消えるため）

# Microsoft のリポジトリキーを追加
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -

# Microsoft のリポジトリを追加（Debian 12 = bookworm）
curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list

# パッケージリストを更新
apt-get update

# ODBC Driver 18 をインストール（ライセンスに自動同意）
ACCEPT_EULA=Y apt-get install -y msodbcsql18

# unixodbc-dev も入れる（pyodbc のビルドに必要な場合がある）
apt-get install -y unixodbc-dev

# --- 2. Streamlit アプリを起動 ---
# --server.port 8000        : Azure App Service が使うポート
# --server.address 0.0.0.0  : 外部からのアクセスを許可
# --server.headless true    : ブラウザを開こうとしない（サーバー環境用）
python -m streamlit run app.py \
    --server.port 8000 \
    --server.address 0.0.0.0 \
    --server.headless true
