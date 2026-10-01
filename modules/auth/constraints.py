"""Shared authentication input limits.

Keep these bounds close to the authentication code so route validation,
service-level validation, rate-limit keys, and request-body limits stay in sync.
"""

EMAIL_MAX_LENGTH = 254
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 256
AUTH_BODY_MAX_BYTES = 16 * 1024
