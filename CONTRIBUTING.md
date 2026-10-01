# Contributing to AI Professor Lite

Thank you for considering a contribution.

AI Professor Lite is a self-hosted FastAPI application that combines lecture planning, slide generation, narration, TalkingHead generation, final video composition, Moodle integration, and a SQLite-backed job system.

## Development Baseline

The supported application runtime is Python 3.10.

For ordinary application development and the CPU-based test suite:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

For the full GPU / Ditto / TensorRT runtime, use the repository's `environment.yaml` or Docker setup described in the README.

The GitHub CI workflow intentionally validates the application without requiring an NVIDIA GPU. Changes to the Ditto, CUDA, TensorRT, or final media pipeline should also be tested on a supported GPU environment before merge.

## Before You Start

Please:

1. check existing issues and pull requests for overlapping work;
2. keep changes focused on one problem or feature;
3. avoid unrelated formatting or refactoring;
4. add or update tests for behavior changes;
5. update documentation when configuration or user-visible behavior changes.

For security vulnerabilities, follow `SECURITY.md` instead of opening a public issue.

## Local Checks

Run these before submitting a pull request:

```bash
ruff check .
pytest
```

Translation XML should also remain well-formed:

```bash
python - <<'PY'
import xml.etree.ElementTree as ET
from pathlib import Path

for path in sorted(Path("core/lang/xml").glob("*.xml")):
    ET.parse(path)
    print("OK:", path)
PY
```

You can also byte-compile the main application modules:

```bash
python -m compileall -q app.py core modules worker.py
```

## Tests

Tests must not depend on real external services, production credentials, or live network access.

Use mocks/fakes for OpenAI, Moodle, and other external integrations. Keep tests deterministic and suitable for GitHub-hosted CI runners.

If your change affects queueing, security, publishing, reference ingestion, narration, slides, or worker behavior, add coverage in the corresponding test module.

## Internationalization

AI Professor Lite supports Korean, English, Japanese, and Chinese UI resources.

When adding or changing user-visible text, keep the relevant translation resources under `core/lang/xml/` consistent.

When a README change affects installation, configuration, or project behavior, update the localized README files where applicable:

- `README.MD`
- `README_EN.MD`
- `README_JA.MD`
- `README_ZH.MD`

## Repository Hygiene

Do not commit:

- `.env`;
- API keys or access tokens;
- Moodle credentials;
- session secrets or encryption keys;
- user databases or production data;
- generated lecture media;
- local caches;
- Ditto checkpoints or other large model artifacts unless explicitly intended by the project.

Use `.env.example` for documented configuration placeholders.

The third-party Ditto source under `core/ditto-talkinghead/` is excluded from the project's normal Ruff scope. Avoid unrelated changes to vendored or third-party code.

## Pull Requests

A pull request should include:

- a concise description of the problem;
- an explanation of the proposed change;
- relevant tests;
- any configuration or migration impact;
- screenshots for meaningful UI changes;
- notes about GPU-specific validation when applicable.

CI should pass before merge.

## Commit Messages

Short, scoped messages are preferred. Examples:

```text
fix: preserve client IP behind trusted proxy
test: cover login rate limiting behind proxy
docs: document Docker reverse proxy setup
ci: add Python 3.10 test workflow
```

## Licensing

By submitting a contribution, you agree that your contribution may be distributed under the repository's Apache License 2.0 terms.
