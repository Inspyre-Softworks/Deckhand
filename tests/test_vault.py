import json
from dataclasses import replace
import pytest
from deckhand.credentials import Vault, CredentialError, default_backend
from deckhand.storage import Account, Settings


def test_session_never_written(tmp_path):
    vault = Vault(tmp_path); a = Account('Alpha', backend='session')
    vault.save(a, 'nation-secret')
    assert vault.load(a) == 'nation-secret'
    assert not list(tmp_path.rglob('*'))
    with pytest.raises(CredentialError): Vault(tmp_path).load(a)
    vault.delete(a)
    with pytest.raises(CredentialError): vault.load(a)


def test_encryption_and_account_isolation(tmp_path):
    vault = Vault(tmp_path); a = Account('alpha', backend='encrypted')
    vault.save(a, 'nation-secret', master='master password')
    assert 'nation-secret' not in vault.path(a).read_text()
    assert 'master password' not in vault.path(a).read_text()
    assert vault.load(a, master='master password') == 'nation-secret'
    with pytest.raises(CredentialError): vault.load(a, master='wrong')
    data = json.loads(vault.path(a).read_text()); data['ciphertext'] = data['ciphertext'][:-4] + 'AAAA'
    vault.path(a).write_text(json.dumps(data))
    with pytest.raises(CredentialError): vault.load(a, master='master password')


def test_plaintext_requires_warning(tmp_path):
    vault = Vault(tmp_path); a = Account('alpha', backend='plaintext')
    with pytest.raises(CredentialError): vault.save(a, 'secret')
    with pytest.warns(UserWarning): vault.save(a, 'secret', allow_plaintext=True)
    with pytest.warns(UserWarning): assert vault.load(a) == 'secret'


def test_multiple_accounts(tmp_path):
    settings = Settings(tmp_path)
    a, b = Account('Alpha'), Account('Beta', maximum='RARE', protect_collections=False)
    settings.add(a); settings.add(b)
    loaded = Settings(tmp_path)
    assert len(loaded.accounts) == 2
    assert loaded.accounts[0].policy.protect_collections
    assert not loaded.accounts[1].policy.protect_collections
    with pytest.raises(ValueError): settings.add(Account('alpha'))


def test_hello_round_trip_adapter(tmp_path, monkeypatch):
    # Unit test the envelope, not a claim about native OS/TPM behavior.
    class FakeHello:
        def crypt(self, name, payload, **kwargs): return payload[::-1]
        def delete(self, name): pass
    monkeypatch.setattr('deckhand.credentials.Hello', FakeHello)
    vault = Vault(tmp_path); a = Account('alpha', backend='hello')
    vault.save(a, 'secret')
    assert 'secret' not in vault.path(a).read_text()
    assert vault.load(a) == 'secret'
    vault.delete(a)
    assert not vault.path(a).exists()


def test_hello_failure_never_falls_back(tmp_path, monkeypatch):
    class BrokenHello:
        def crypt(self, *args, **kwargs): raise RuntimeError('Unavailable')
    monkeypatch.setattr('deckhand.credentials.Hello', BrokenHello)
    a = Account('alpha', backend='hello'); vault = Vault(tmp_path)
    with pytest.raises(RuntimeError): vault.save(a, 'secret')
    assert not vault.path(a).exists()


def test_defaults(monkeypatch):
    monkeypatch.setattr('deckhand.credentials.sys.platform', 'win32')
    assert default_backend() == 'hello'
    monkeypatch.setattr('deckhand.credentials.sys.platform', 'linux')
    assert default_backend() == 'keyring'
