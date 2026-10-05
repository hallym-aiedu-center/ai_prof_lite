[한국어](./CONTRIBUTING.md) | [English](./CONTRIBUTING_EN.md) | **日本語** | [中文](./CONTRIBUTING_ZH.md)

# コントリビューション

[README](./README_JA.md) | [インストール・運用](./docs/INSTALLATION_JA.md) | [開発者ガイド](./docs/DEVELOPMENT_JA.md)

コードを修正したりテストを追加したりする場合は、まず [インストール・運用](./docs/INSTALLATION_JA.md) の手動インストール手順に従って開発環境を準備します。

## 開発 / テスト依存関係

```bash
python -m pip install -r requirements-dev.txt
```

## コード変更時の確認事項

多言語 UI のユーザー向け文言は translation key で管理します。文字列を追加・変更する場合は、`core/lang/xml/` 配下の各言語ファイルに同じ key があることを確認してください。詳しい構造は [開発者ガイド](./docs/DEVELOPMENT_JA.md) の多言語セクションを参照してください。

このプロジェクトでは CSP のため inline JavaScript event handler を許可していません。イベント処理は静的 JavaScript ファイルで登録します。

## テスト

```bash
python -m pytest
```

個別テスト:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

コードを修正した後は、最低限次の 3 つを確認します。

```bash
ruff check .
python scripts/preflight.py
python -m pytest
```

## Pull Request

変更の目的と主な変更内容を記載し、実行したテストとその結果もあわせて残してください。UI を変更した場合は、変更内容を確認できる画面も添付してください。
