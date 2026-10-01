# Security Policy

## Supported Versions

Security fixes are provided for the current release line.

| Version | Supported |
| --- | --- |
| 1.0.x | Yes |
| < 1.0 | No |

When a newer release line becomes the current supported version, this table may be updated accordingly.

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for a suspected security vulnerability.

Prefer GitHub's private vulnerability reporting feature from the repository's **Security** tab when it is available. If private vulnerability reporting is not available, contact the repository maintainers through a private channel associated with the repository owner or organization.

A useful report should include:

- the affected version or commit;
- the affected component or endpoint;
- clear reproduction steps;
- the expected and observed behavior;
- the security impact;
- a minimal proof of concept, when appropriate;
- any suggested mitigation or fix.

Please remove real API keys, access tokens, cookies, personal data, Moodle credentials, and other secrets from reports and reproduction material.

## Security-Relevant Areas

Reports are especially useful when they involve:

- authentication, sessions, CSRF, or account isolation;
- credential encryption or secret handling;
- authorization or cross-user data access;
- upload validation or parser abuse;
- SSRF or Moodle/network-origin validation;
- trusted proxy and forwarded-header handling;
- rate-limit bypasses;
- queue ownership, leases, or job isolation;
- path traversal or unintended file access;
- command execution or media-processing boundaries.

## Coordinated Disclosure

Please allow maintainers a reasonable period to investigate, reproduce, and prepare a fix before public disclosure.

The maintainers will handle reports on a best-effort basis and aim to acknowledge a valid report within a few business days. Resolution time depends on severity, reproducibility, and the scope of the required fix.

## Secrets and Production Data

Do not include production secrets or sensitive data in an issue, pull request, test fixture, screenshot, log, or sample configuration.

Use placeholders or test-only credentials in all public material.
