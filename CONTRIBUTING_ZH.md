[한국어](./CONTRIBUTING.md) | [English](./CONTRIBUTING_EN.md) | [日本語](./CONTRIBUTING_JA.md) | **中文**

# 参与贡献

[README](./README_ZH.md) | [安装与运维](./docs/INSTALLATION_ZH.md) | [开发者指南](./docs/DEVELOPMENT_ZH.md)

如需修改代码或添加测试，请先按照 [安装与运维](./docs/INSTALLATION_ZH.md) 中的手动安装说明准备开发环境。

## 开发 / 测试依赖

```bash
python -m pip install -r requirements-dev.txt
```

## 修改代码时的检查事项

多语言 UI 中面向用户的文本使用 translation key 管理。新增或修改字符串时，请确认 `core/lang/xml/` 下各语言文件中都存在相同的 key。详细结构请参考 [开发者指南](./docs/DEVELOPMENT_ZH.md) 的多语言部分。

由于 CSP，本项目不允许 inline JavaScript event handler。事件处理应在静态 JavaScript 文件中注册。

## 测试

```bash
python -m pytest
```

单独运行测试:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

修改代码后，至少执行以下三项检查。

```bash
ruff check .
python scripts/preflight.py
python -m pytest
```

## Pull Request

请说明修改目的和主要变更内容，并附上已执行的测试及其结果。如果修改了 UI，请同时附上便于确认变更的界面截图。
