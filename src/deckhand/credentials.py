import base64
import json
import os
from pathlib import Path
import sys
import warnings
from uuid import uuid4
import keyring
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from .storage import atomic_write
from .hello import Hello

SERVICE = "ns-deckhand"


class CredentialError(RuntimeError):
    pass


def default_backend():
    return "hello" if sys.platform == "win32" else "keyring"


def encode(data):
    return base64.b64encode(data).decode("ascii")


def decode(data):
    return base64.b64decode(data, validate=True)


class Vault:
    def __init__(self, directory):
        self.directory = Path(directory) / "credentials"
        self.session = {}

    def path(self, account):
        return self.directory / f"{account.id}.json"

    @staticmethod
    def derive(password, salt):
        if not password:
            raise CredentialError("Enter the vault password.")
        return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode())

    @staticmethod
    def secure_keyring():
        backend = keyring.get_keyring()
        # Reject alternate/plaintext/chained fallback backends rather than guessing.
        approved = ("keyring.backends.Windows", "keyring.backends.macOS",
            "keyring.backends.SecretService", "keyring.backends.kwallet")
        candidates = backend.backends if type(backend).__module__ == "keyring.backends.chainer" else [backend]
        for candidate in candidates:
            if type(candidate).__module__.startswith(approved) and candidate.priority > 0:
                return candidate
        raise CredentialError("No supported secure keyring is active. Configure Secret Service/KWallet or choose password encryption.")

    def save(self, account, secret, *, master=None, allow_plaintext=False):
        if not secret:
            raise CredentialError("Enter the nation password.")
        mode = account.backend
        if mode == "session":
            self.session[account.id] = secret
            return
        if mode == "keyring":
            self.secure_keyring().set_password(SERVICE, account.id, secret)
            return
        if mode == "plaintext":
            if not allow_plaintext:
                raise CredentialError("Plaintext requires explicit acknowledgment.")
            warnings.warn("Nation password will be stored in readable plaintext.", UserWarning, stacklevel=2)
            data = {"mode": mode, "secret": secret}
        else:
            key_name = None
            if mode == "encrypted":
                salt = os.urandom(16)
                key = self.derive(master, salt)
                data = {"mode": mode, "salt": encode(salt)}
            elif mode == "hello":
                key = AESGCM.generate_key(bit_length=256)
                key_name = f"Deckhand-{account.id}-{uuid4().hex}"
                wrapped = Hello().crypt(key_name, key, create=True)
                data = {"mode": mode, "key_name": key_name, "wrapped": encode(wrapped)}
            else:
                raise CredentialError("Unknown credential mode")
            nonce = os.urandom(12)
            data.update(nonce=encode(nonce), ciphertext=encode(AESGCM(key).encrypt(nonce,
                secret.encode(), account.id.encode())))
        old = json.loads(self.path(account).read_text()) if self.path(account).exists() else None
        try:
            atomic_write(self.path(account), json.dumps(data).encode())
        except Exception:
            if mode == "hello":
                Hello().delete(data["key_name"])
            raise
        if old and old.get("mode") == "hello":
            Hello().delete(old["key_name"])

    def load(self, account, *, master=None):
        mode = account.backend
        if mode == "session":
            result = self.session.get(account.id)
            if result is None:
                raise CredentialError("No session password. Use Credentials to enter it.")
            return result
        if mode == "keyring":
            result = self.secure_keyring().get_password(SERVICE, account.id)
            if result is None:
                raise CredentialError("No saved password for this account.")
            return result
        try:
            data = json.loads(self.path(account).read_text("utf-8"))
            if data["mode"] != mode:
                raise CredentialError("Credential file does not match account settings.")
            if mode == "plaintext":
                warnings.warn("Loading a plaintext nation password.", UserWarning, stacklevel=2)
                return data["secret"]
            if mode == "encrypted":
                key = self.derive(master, decode(data["salt"]))
            elif mode == "hello":
                key = Hello().crypt(data["key_name"], decode(data["wrapped"]), decrypt=True)
            else:
                raise CredentialError("Unknown credential mode")
            return AESGCM(key).decrypt(decode(data["nonce"]), decode(data["ciphertext"]), account.id.encode()).decode()
        except InvalidTag:
            raise CredentialError("Wrong vault password or damaged credential file.") from None
        except (FileNotFoundError, KeyError, ValueError):
            raise CredentialError("Credential file is missing or damaged.") from None

    def delete(self, account):
        if account.backend == "session":
            self.session.pop(account.id, None)
        elif account.backend == "keyring":
            self.secure_keyring().delete_password(SERVICE, account.id)
        else:
            path = self.path(account)
            if path.exists():
                data = json.loads(path.read_text("utf-8"))
                if data.get("mode") == "hello":
                    Hello().delete(data["key_name"])
                path.unlink()
