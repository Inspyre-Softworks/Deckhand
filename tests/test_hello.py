import ctypes as C
from unittest.mock import Mock
import pytest
from deckhand.hello import Hello, HelloError, passport_key_name


def test_passport_key_name_is_user_qualified():
    assert passport_key_name('S-1-5-21-123', 'account-key') == 'S-1-5-21-123//Deckhand/credentials/account-key'


def test_native_create_and_delete_use_same_qualified_name():
    hello = Hello.__new__(Hello)
    hello.sid = 'S-1-5-21-123'
    hello.dll = Mock()
    calls = []
    def call(name, *args):
        calls.append((name, args))
        if name == 'NCryptOpenStorageProvider':
            C.cast(args[0], C.POINTER(C.c_size_t))[0] = 11
        elif name in ('NCryptCreatePersistedKey', 'NCryptOpenKey'):
            C.cast(args[1], C.POINTER(C.c_size_t))[0] = 22
        elif name == 'NCryptGetProperty':
            C.cast(args[2], C.POINTER(C.c_ulong))[0] = 1
    hello.call = call
    with hello.key('account-key', create=True):
        pass
    hello.delete('account-key')
    create = next(args for name,args in calls if name == 'NCryptCreatePersistedKey')
    opened = next(args for name,args in calls if name == 'NCryptOpenKey')
    assert create[3] == opened[2] == passport_key_name(hello.sid, 'account-key')


def test_native_error_identifies_stage_without_exposing_key_name():
    hello = Hello.__new__(Hello)
    hello.dll = Mock()
    hello.dll.NCryptCreatePersistedKey.return_value = -2146893785
    with pytest.raises(HelloError) as error:
        hello.call('NCryptCreatePersistedKey', 0, None, 'RSA', 'private-account-key', 0, 0)
    assert 'NCryptCreatePersistedKey' in str(error.value)
    assert '0x80090027' in str(error.value)
    assert 'private-account-key' not in str(error.value)
