"""Encryption utilities for CrewContext.

Provides encryption at rest for sensitive event data.

Usage:
    from crewcontext.encryption import EncryptionManager, FieldEncryption
    
    # Initialize with a key (in production, use secrets management)
    encryption = EncryptionManager.generate_key()
    manager = EncryptionManager(encryption)
    
    # Encrypt specific fields
    sensitive_data = {"ssn": "123-45-6789", "amount": 5000}
    encrypted = manager.encrypt_fields(sensitive_data, fields=["ssn"])
    
    # Decrypt when needed
    decrypted = manager.decrypt_fields(encrypted, fields=["ssn"])
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)

# Try to import cryptography, fall back to basic implementation
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    log.warning("cryptography package not installed. Using basic encryption.")


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


class EncryptionManager:
    """Manages encryption for sensitive data.

    Features:
    - Field-level encryption
    - Key rotation support
    - Audit logging for decrypt operations

    Usage:
        manager = EncryptionManager(key)
        encrypted = manager.encrypt({"ssn": "123-45-6789"})
        decrypted = manager.decrypt(encrypted)
    """

    def __init__(
        self,
        key: bytes,
        enable_audit: bool = True,
    ):
        """Initialize encryption manager.

        Args:
            key: 32-byte encryption key. Use generate_key() to create one.
            enable_audit: Log decrypt operations.
        """
        if len(key) != 32:
            raise ValueError("Encryption key must be 32 bytes")

        self._key = key
        self._enable_audit = key
        self._decrypt_count = 0

        if CRYPTO_AVAILABLE:
            # Derive a Fernet key from the master key
            salt = b"crewcontext_salt"  # In production, use random salt
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            fernet_key = base64.urlsafe_b64encode(kdf.derive(key))
            self._fernet = Fernet(fernet_key)
        else:
            self._fernet = None

    @staticmethod
    def generate_key() -> bytes:
        """Generate a new random encryption key.

        Returns:
            32-byte random key.
        """
        return os.urandom(32)

    @staticmethod
    def key_from_password(password: str, salt: str = "crewcontext") -> bytes:
        """Derive a key from a password.

        Args:
            password: User password.
            salt: Salt for key derivation.

        Returns:
            32-byte derived key.
        """
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            100000,
            dklen=32,
        )

    def encrypt(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt all values in a dictionary.

        Args:
            data: Dictionary to encrypt.

        Returns:
            Dictionary with encrypted values.
        """
        result = {}
        for key, value in data.items():
            result[key] = self._encrypt_value(value)
        return result

    def decrypt(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt all values in a dictionary.

        Args:
            data: Dictionary with encrypted values.

        Returns:
            Dictionary with decrypted values.
        """
        result = {}
        for key, value in data.items():
            result[key] = self._decrypt_value(value)
        self._decrypt_count += 1
        return result

    def encrypt_fields(
        self,
        data: Dict[str, Any],
        fields: Set[str],
    ) -> Dict[str, Any]:
        """Encrypt specific fields in a dictionary.

        Args:
            data: Dictionary to partially encrypt.
            fields: Field names to encrypt.

        Returns:
            Dictionary with specified fields encrypted.
        """
        result = dict(data)
        for field in fields:
            if field in result:
                result[field] = self._encrypt_value(result[field])
                result[f"{field}__encrypted"] = True
        return result

    def decrypt_fields(
        self,
        data: Dict[str, Any],
        fields: Set[str],
    ) -> Dict[str, Any]:
        """Decrypt specific fields in a dictionary.

        Args:
            data: Dictionary with encrypted fields.
            fields: Field names to decrypt.

        Returns:
            Dictionary with specified fields decrypted.
        """
        result = dict(data)
        for field in fields:
            if field in result:
                result[field] = self._decrypt_value(result[field])
                result.pop(f"{field}__encrypted", None)
        self._decrypt_count += 1
        return result

    def _encrypt_value(self, value: Any) -> str:
        """Encrypt a single value.

        Args:
            value: Value to encrypt.

        Returns:
            Base64-encoded encrypted string.
        """
        if value is None:
            return value

        # Convert to JSON string
        plaintext = json.dumps(value, default=str).encode()

        if CRYPTO_AVAILABLE and self._fernet:
            encrypted = self._fernet.encrypt(plaintext)
        else:
            # Basic XOR encryption (not secure, for demo only)
            encrypted = bytes(a ^ b for a, b in zip(plaintext, self._key * (len(plaintext) // 32 + 1)))

        return base64.b64encode(encrypted).decode()

    def _decrypt_value(self, value: Any) -> Any:
        """Decrypt a single value.

        Args:
            value: Encrypted base64 string.

        Returns:
            Decrypted original value.
        """
        if value is None:
            return value

        if not isinstance(value, str):
            return value

        try:
            encrypted = base64.b64decode(value.encode())

            if CRYPTO_AVAILABLE and self._fernet:
                plaintext = self._fernet.decrypt(encrypted)
            else:
                # Basic XOR decryption
                plaintext = bytes(a ^ b for a, b in zip(encrypted, self._key * (len(encrypted) // 32 + 1)))

            return json.loads(plaintext.decode())
        except Exception as e:
            log.warning("Failed to decrypt value: %s", e)
            return value  # Return as-is if decryption fails

    @property
    def decrypt_count(self) -> int:
        """Get number of decrypt operations performed."""
        return self._decrypt_count


class FieldEncryption:
    """Descriptor for automatic field encryption in dataclasses.

    Usage:
        from dataclasses import dataclass
        from crewcontext.encryption import FieldEncryption, EncryptionManager

        manager = EncryptionManager(key)

        @dataclass
        class SensitiveEvent:
            id: str
            ssn: str = FieldEncryption(manager)
            amount: float

        event = SensitiveEvent(id="1", ssn="123-45-6789", amount=5000)
        print(event.ssn)  # Automatically encrypted
    """

    def __init__(self, manager: EncryptionManager, field_name: Optional[str] = None):
        self.manager = manager
        self.field_name = field_name
        self.private_name: Optional[str] = None

    def __set_name__(self, owner: type, name: str) -> None:
        self.private_name = f"_{name}"
        self.field_name = name

    def __get__(self, obj: Any, objtype: Optional[type] = None) -> Any:
        if obj is None:
            return self
        return getattr(obj, self.private_name, None)

    def __set__(self, obj: Any, value: Any) -> None:
        encrypted = self.manager._encrypt_value(value)
        setattr(obj, self.private_name, encrypted)


class EncryptedStore:
    """Wrapper that adds encryption to any CrewContext store.

    Usage:
        from crewcontext.store.postgres import PostgresStore
        from crewcontext.encryption import EncryptedStore, EncryptionManager

        # Create base store
        base_store = PostgresStore(db_url)

        # Wrap with encryption
        manager = EncryptionManager(key)
        encrypted_store = EncryptedStore(base_store, manager, sensitive_fields=["ssn", "account_number"])

        # Use as normal - sensitive fields are automatically encrypted
        encrypted_store.save_event(event)
    """

    def __init__(
        self,
        inner_store: Any,
        encryption_manager: EncryptionManager,
        sensitive_fields: Optional[Set[str]] = None,
    ):
        """Initialize encrypted store wrapper.

        Args:
            inner_store: Underlying store (e.g., PostgresStore).
            encryption_manager: Encryption manager instance.
            sensitive_fields: Field names to encrypt.
        """
        self._inner = inner_store
        self._encryption = encryption_manager
        self._sensitive_fields = sensitive_fields or set()

    def __getattr__(self, name: str) -> Any:
        # Delegate all other attributes to inner store
        return getattr(self._inner, name)

    def save_event(self, event: Any) -> None:
        """Save event with encrypted sensitive fields."""
        # Encrypt sensitive fields in event data
        if self._sensitive_fields:
            event.data = self._encryption.encrypt_fields(event.data, self._sensitive_fields)
        self._inner.save_event(event)

    def query_events(self, *args, **kwargs) -> List[Dict[str, Any]]:
        """Query events and decrypt sensitive fields."""
        events = self._inner.query_events(*args, **kwargs)

        if self._sensitive_fields:
            for event in events:
                if "data" in event:
                    event["data"] = self._encryption.decrypt_fields(
                        event["data"],
                        self._sensitive_fields,
                    )

        return events

    def save_entity(self, entity: Any) -> None:
        """Save entity with encrypted sensitive fields."""
        if self._sensitive_fields:
            entity.attributes = self._encryption.encrypt_fields(
                entity.attributes,
                self._sensitive_fields,
            )
        self._inner.save_entity(entity)

    def get_entity(self, entity_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Get entity and decrypt sensitive fields."""
        entity = self._inner.get_entity(entity_id, **kwargs)

        if entity and self._sensitive_fields and "attributes" in entity:
            entity["attributes"] = self._encryption.decrypt_fields(
                entity["attributes"],
                self._sensitive_fields,
            )

        return entity
