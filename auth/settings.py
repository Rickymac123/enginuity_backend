"""Shared signing-key lookup for authentication and provider configuration."""
import os


def signing_secret():
    secret = os.getenv('SECRET') or os.getenv('SECRET_KEY')
    if not secret or not secret.strip() or secret == 'SUPER_SECRET_JWT':
        raise RuntimeError('Configure a private SECRET or SECRET_KEY before starting the API')
    return secret
