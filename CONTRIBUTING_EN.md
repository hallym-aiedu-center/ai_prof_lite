[한국어](./CONTRIBUTING.md) | **English** | [日本語](./CONTRIBUTING_JA.md) | [中文](./CONTRIBUTING_ZH.md)

# Contributing

[README](./README_EN.md) | [Installation & Operations](./docs/INSTALLATION_EN.md) | [Developer Guide](./docs/DEVELOPMENT_EN.md)

Before modifying code or adding tests, set up the development environment by following the manual installation section in [Installation & Operations](./docs/INSTALLATION_EN.md).

## Development / Test Dependencies

```bash
python -m pip install -r requirements-dev.txt
```

## Before Changing Code

User-facing text in the multilingual UI is managed with translation keys. When adding or changing strings, check that the same key exists in each language file under `core/lang/xml/`. See the multilingual section in the [Developer Guide](./docs/DEVELOPMENT_EN.md) for details.

The project does not allow inline JavaScript event handlers because of CSP. Register event handlers in static JavaScript files.

## Tests

```bash
python -m pytest
```

Individual tests:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

After modifying code, run at least the following two checks.

```bash
python scripts/preflight.py
python -m pytest
```

## Pull Request

Describe the purpose of the change and the main changes, and include the tests you ran and their results. If you changed the UI, attach screenshots that make the change easy to verify.
