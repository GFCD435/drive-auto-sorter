FROM mcr.microsoft.com/devcontainers/python:3.10
# 必要なら OS パッケージ
RUN apt-get update && apt-get install -y nginx curl jq && rm -rf /var/lib/apt/lists/*
WORKDIR /workspaces/drive-auto-sorter-clean
