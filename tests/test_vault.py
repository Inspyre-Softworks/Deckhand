import json
from dataclasses import replace
import pytest
from deckhand.credentials import Vault, CredentialError, default_backend
from deckhand.storage import Account, Settings, RequestCounter


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


def test_name_rules_persist_and_include_all_configured_nations(tmp_path):
    settings = Settings(tmp_path)
    settings.add(Account('Alpha', protected_names=['Friend Nation'], protected_substrings=['Silver']))
    settings.add(Account('Beta'))
    loaded = Settings(tmp_path)
    policy = loaded.policy_for(loaded.accounts[0])
    assert policy.protect_own_nations and policy.own_nations == ('alpha', 'beta')
    assert policy.protected_names == ('friend nation',)
    assert policy.protected_substrings == ('silver',)


def test_request_counter_persists_and_demo_does_not_create_file(tmp_path):
    counter = RequestCounter(tmp_path)
    assert counter.total() == 0 and not counter.path.exists()
    assert counter.increment() == 1
    assert RequestCounter(tmp_path).increment() == 2
    assert counter.total() == 2


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


def test_fast_execution_saved_per_account_and_defaults_off(tmp_path):
    settings = Settings(tmp_path)
    settings.add(Account('alpha', fast_execution=True))
    settings.add(Account('beta'))
    loaded = Settings(tmp_path)
    assert loaded.policy_for(loaded.accounts[0]).fast_execution is True
    assert loaded.policy_for(loaded.accounts[1]).fast_execution is False
    with pytest.raises(ValueError):
        Account('gamma', fast_execution='false')
