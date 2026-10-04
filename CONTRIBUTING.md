**한국어** | [English](./CONTRIBUTING_EN.md) | [日本語](./CONTRIBUTING_JA.md) | [中文](./CONTRIBUTING_ZH.md)

# 기여하기

[README](./README.md) | [설치 및 운영](./docs/INSTALLATION.md) | [개발자 가이드](./docs/DEVELOPMENT.md)

코드를 수정하거나 테스트를 추가하려면 먼저 [설치 및 운영](./docs/INSTALLATION.md)의 수동 설치 내용을 따라 개발 환경을 준비합니다.

## 개발 / 테스트 의존성

```bash
python -m pip install -r requirements-dev.txt
```

## 코드 수정 시 확인

다국어 UI의 사용자 노출 문구는 translation key로 관리합니다. 문자열을 추가하거나 변경할 때는 `core/lang/xml/`의 각 언어 파일에서 같은 key를 확인합니다. 자세한 구조는 [개발자 가이드](./docs/DEVELOPMENT.md)의 다국어 항목을 참고하세요.

프로젝트는 CSP 때문에 inline JavaScript event handler를 허용하지 않습니다. 이벤트 처리는 정적 JavaScript 파일에서 등록합니다.

## 테스트

```bash
python -m pytest
```

개별 테스트:

```bash
python -m pytest tests/test_pipeline.py
python -m pytest tests/test_worker.py
python -m pytest tests/test_security.py
```

코드를 수정한 뒤에는 최소한 아래 두 가지를 확인합니다.

```bash
python scripts/preflight.py
python -m pytest
```

## Pull Request

변경 목적과 주요 변경 내용을 적고, 실행한 테스트와 결과를 함께 남깁니다. UI를 변경했다면 확인할 수 있는 화면도 함께 첨부합니다.
