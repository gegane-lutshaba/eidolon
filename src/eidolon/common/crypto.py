"""Ed25519 signing/verification wrappers (PRD §8: Ed25519 throughout).

Thin helpers over PyNaCl. Keys and signatures are exchanged as hex strings so
they round-trip cleanly through canonical JSON and the SAGE ledger.
"""

from __future__ import annotations

from dataclasses import dataclass

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey


@dataclass(frozen=True)
class KeyPair:
    signing_key_hex: str
    public_key_hex: str

    @property
    def signing_key(self) -> SigningKey:
        return SigningKey(bytes.fromhex(self.signing_key_hex))

    @property
    def verify_key(self) -> VerifyKey:
        return VerifyKey(bytes.fromhex(self.public_key_hex))


def generate_keypair() -> KeyPair:
    sk = SigningKey.generate()
    return KeyPair(
        signing_key_hex=bytes(sk).hex(),
        public_key_hex=bytes(sk.verify_key).hex(),
    )


def public_key_from_private(signing_key_hex: str) -> str:
    """Derive the Ed25519 public key (hex) from a private signing key (hex)."""
    return bytes(SigningKey(bytes.fromhex(signing_key_hex)).verify_key).hex()


def sign(signing_key_hex: str, message: bytes) -> str:
    """Return a detached signature (hex) over ``message``."""
    sk = SigningKey(bytes.fromhex(signing_key_hex))
    return sk.sign(message).signature.hex()


def verify(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    """Return True iff ``signature_hex`` is a valid Ed25519 signature.

    Fails closed: any malformed key/signature returns False rather than raising.
    """
    try:
        vk = VerifyKey(bytes.fromhex(public_key_hex))
        vk.verify(message, bytes.fromhex(signature_hex))
        return True
    except (BadSignatureError, ValueError):
        return False
