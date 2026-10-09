import pytest
from auth.settings import signing_secret


def test_render_key_is_used(monkeypatch):
    monkeypatch.delenv('SECRET', raising=False)
    monkeypatch.setenv('SECRET_KEY', 'render-test-key-' + 'x' * 32)
    assert signing_secret() == 'render-test-key-' + 'x' * 32


def test_explicit_secret_takes_precedence(monkeypatch):
    monkeypatch.setenv('SECRET', 'explicit-test-key')
    monkeypatch.setenv('SECRET_KEY', 'render-test-key')
    assert signing_secret() == 'explicit-test-key'


@pytest.mark.parametrize('value', [None, '', ' ', 'SUPER_SECRET_JWT'])
def test_missing_or_public_fallback_fails_closed(monkeypatch, value):
    monkeypatch.delenv('SECRET', raising=False)
    monkeypatch.delenv('SECRET_KEY', raising=False)
    if value is not None:
        monkeypatch.setenv('SECRET', value)
    with pytest.raises(RuntimeError):
        signing_secret()
