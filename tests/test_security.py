"""Tests for Phase 3 security features."""
import pytest
from datetime import datetime, timezone

from crewcontext.security import (
    AccessPolicy, Permission, Role, AccessRule, AccessDecision,
    AccessContext, create_builtin_roles,
)
from crewcontext.encryption import (
    EncryptionManager, EncryptedStore, FieldEncryption, EncryptionError,
)
from crewcontext.secrets import (
    SecretsManager, EnvSecretProvider, FileSecretProvider,
    JsonSecretProvider, SecretNotFoundError,
)
from crewcontext.models import Event, generate_id


class TestAccessPolicy:
    """Test RBAC access control."""

    def test_create_role(self):
        """Test role creation."""
        role = Role(
            name="admin",
            permissions={Permission.READ, Permission.WRITE},
            scopes={"finance", "hr"},
        )
        assert role.name == "admin"
        assert role.has_permission(Permission.READ)
        assert role.can_access_scope("finance")
        assert not role.can_access_scope("unknown")

    def test_wildcard_scope(self):
        """Test wildcard scope access."""
        role = Role(
            name="super_admin",
            permissions={Permission.ADMIN},
            scopes={"*"},
        )
        assert role.can_access_scope("any_scope")
        assert role.can_access_scope("finance")

    def test_access_policy_basic(self):
        """Test basic access policy functionality."""
        policy = AccessPolicy()
        role = Role("reader", {Permission.READ}, {"finance"})
        policy.add_role(role)
        policy.assign_role("agent-1", "reader")

        assert policy.can_access("agent-1", "finance", Permission.READ)
        assert not policy.can_access("agent-1", "finance", Permission.WRITE)
        assert not policy.can_access("agent-1", "hr", Permission.READ)

    def test_default_deny(self):
        """Test default deny policy."""
        policy = AccessPolicy(default_deny=True)
        assert not policy.can_access("unknown-agent", "any", Permission.READ)

    def test_default_allow(self):
        """Test default allow policy."""
        policy = AccessPolicy(default_deny=False)
        assert policy.can_access("unknown-agent", "any", Permission.READ)

    def test_access_rules_priority(self):
        """Test access rules with priority."""
        policy = AccessPolicy()

        # Low priority rule: allow all
        policy.add_rule(AccessRule(
            name="allow-all",
            allow=True,
            priority=0,
        ))

        # High priority rule: deny specific agent
        policy.add_rule(AccessRule(
            name="deny-bad-agent",
            roles=set(),
            scopes={"*"},
            permissions={Permission.READ},
            allow=False,
            priority=10,
        ))

        # Should be denied due to higher priority rule
        assert not policy.can_access("bad-agent", "finance", Permission.READ)

    def test_audit_logging(self):
        """Test access control audit logging."""
        policy = AccessPolicy(enable_audit=True)
        role = Role("reader", {Permission.READ}, {"*"})
        policy.add_role(role)
        policy.assign_role("agent-1", "reader")

        policy.can_access("agent-1", "finance", Permission.READ)
        policy.can_access("agent-1", "hr", Permission.WRITE)  # Denied

        audit_log = policy.get_audit_log()
        assert len(audit_log) == 2
        assert audit_log[0]["decision"] == "ALLOW"
        assert audit_log[1]["decision"] == "DENY"

    def test_builtin_roles(self):
        """Test built-in role creation."""
        roles = create_builtin_roles()
        assert len(roles) >= 3

        role_names = {r.name for r in roles}
        assert "admin" in role_names
        assert "reader" in role_names
        assert "writer" in role_names

    def test_export_policy(self):
        """Test policy export."""
        policy = AccessPolicy()
        policy.add_role(Role("test", {Permission.READ}, {"*"}))
        policy.assign_role("agent-1", "test")

        exported = policy.export_policy()
        assert "roles" in exported
        assert "agent_assignments" in exported
        assert len(exported["roles"]) == 1


class TestEncryption:
    """Test encryption at rest."""

    def test_generate_key(self):
        """Test key generation."""
        key = EncryptionManager.generate_key()
        assert len(key) == 32

    def test_key_from_password(self):
        """Test password-based key derivation."""
        key1 = EncryptionManager.key_from_password("password123")
        key2 = EncryptionManager.key_from_password("password123")
        key3 = EncryptionManager.key_from_password("different")

        assert key1 == key2  # Same password = same key
        assert key1 != key3  # Different password = different key

    def test_encrypt_decrypt_dict(self):
        """Test full dictionary encryption/decryption."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(key)

        original = {"ssn": "123-45-6789", "amount": 5000}
        encrypted = manager.encrypt(original)

        assert encrypted["ssn"] != original["ssn"]
        assert isinstance(encrypted["ssn"], str)

        decrypted = manager.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_specific_fields(self):
        """Test field-level encryption."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(key)

        original = {"ssn": "123-45-6789", "name": "John", "amount": 5000}
        encrypted = manager.encrypt_fields(original, {"ssn"})

        assert encrypted["ssn"] != original["ssn"]
        assert encrypted["name"] == original["name"]  # Not encrypted
        assert encrypted["amount"] == original["amount"]  # Not encrypted
        assert encrypted.get("ssn__encrypted") is True

        decrypted = manager.decrypt_fields(encrypted, {"ssn"})
        assert decrypted["ssn"] == original["ssn"]
        assert "ssn__encrypted" not in decrypted

    def test_decrypt_count_tracking(self):
        """Test decrypt operation counting."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(key)

        assert manager.decrypt_count == 0

        manager.decrypt({"field": "encrypted_value"})
        assert manager.decrypt_count == 1

    def test_none_value_handling(self):
        """Test None value handling in encryption."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(key)

        original = {"field": None, "other": "value"}
        encrypted = manager.encrypt(original)
        decrypted = manager.decrypt(encrypted)

        assert decrypted["field"] is None
        assert decrypted["other"] == "value"


class TestSecretsManager:
    """Test secrets management."""

    def test_env_secret_provider(self):
        """Test environment variable provider."""
        import os
        os.environ["TEST_SECRET"] = "secret_value"

        provider = EnvSecretProvider()
        assert provider.get("TEST_SECRET") == "secret_value"
        assert provider.get("NONEXISTENT") is None

    def test_env_secret_provider_with_prefix(self):
        """Test environment provider with prefix."""
        import os
        os.environ["CREWCONTEXT_API_KEY"] = "key123"

        provider = EnvSecretProvider(prefix="CREWCONTEXT_")
        assert provider.get("API_KEY") == "key123"
        assert provider.get("NONEXISTENT") is None

    def test_secrets_manager_get(self):
        """Test basic secrets manager get."""
        import os
        os.environ["TEST_GET_SECRET"] = "test_value"

        secrets = SecretsManager(provider="env")
        assert secrets.get("TEST_GET_SECRET") == "test_value"
        assert secrets.get("NONEXISTENT") is None

    def test_secrets_manager_default(self):
        """Test default value for missing secret."""
        secrets = SecretsManager(provider="env")
        assert secrets.get("NONEXISTENT", "default") == "default"

    def test_secrets_manager_get_int(self):
        """Test integer secret retrieval."""
        import os
        os.environ["TEST_PORT"] = "5432"

        secrets = SecretsManager(provider="env")
        assert secrets.get_int("TEST_PORT") == 5432
        assert secrets.get_int("NONEXISTENT", 8080) == 8080

    def test_secrets_manager_get_bool(self):
        """Test boolean secret retrieval."""
        import os
        os.environ["TEST_ENABLED"] = "true"
        os.environ["TEST_DISABLED"] = "false"

        secrets = SecretsManager(provider="env")
        assert secrets.get_bool("TEST_ENABLED") is True
        assert secrets.get_bool("TEST_DISABLED") is False
        assert secrets.get_bool("NONEXISTENT", True) is True

    def test_require_secret_success(self):
        """Test requiring existing secrets."""
        import os
        os.environ["REQUIRED_SECRET"] = "value"

        secrets = SecretsManager(provider="env")
        secrets.require("REQUIRED_SECRET")  # Should not raise

    def test_require_secret_failure(self):
        """Test requiring missing secrets."""
        secrets = SecretsManager(provider="env")

        with pytest.raises(SecretNotFoundError):
            secrets.require("NONEXISTENT_SECRET_12345")

    def test_access_log(self):
        """Test secret access logging."""
        import os
        os.environ["LOGGED_SECRET"] = "value"

        secrets = SecretsManager(provider="env")
        secrets.get("LOGGED_SECRET")
        secrets.get("NONEXISTENT")

        log = secrets.get_access_log()
        assert len(log) == 2
        assert log[0]["secret_name"] == "LOGGED_SECRET"
        assert log[0]["found"] is True
        assert log[1]["found"] is False

    def test_list_secrets(self):
        """Test listing available secrets."""
        import os
        os.environ["LIST_SECRET_1"] = "value1"
        os.environ["LIST_SECRET_2"] = "value2"

        provider = EnvSecretProvider(prefix="LIST_")
        names = provider.list()

        assert "SECRET_1" in names
        assert "SECRET_2" in names


class TestQueryAudit:
    """Test query audit logging in ProcessContext."""

    @pytest.mark.skip(reason="Requires PostgreSQL")
    def test_query_audit_log(self, pg_store, unique_process_id):
        """Test that queries are audited."""
        from crewcontext.context import ProcessContext

        with ProcessContext(
            process_id=unique_process_id,
            agent_id="test-agent",
        ) as ctx:
            # Perform some queries
            ctx.query(limit=10)
            ctx.timeline("entity-1")

            # Check audit log
            audit_log = ctx.get_query_audit_log()
            assert len(audit_log) == 2
            assert audit_log[0]["query_type"] == "query"
            assert audit_log[1]["query_type"] == "timeline"
            assert audit_log[0]["agent_id"] == "test-agent"


class TestAccessPolicyIntegration:
    """Test access policy integration with ProcessContext."""

    @pytest.mark.skip(reason="Requires PostgreSQL")
    def test_context_access_check(self, pg_store, unique_process_id):
        """Test access checking in context."""
        from crewcontext.context import ProcessContext
        from crewcontext.security import AccessPolicy, Permission, Role

        # Create policy with specific permissions
        policy = AccessPolicy()
        policy.add_role(Role("reader", {Permission.READ}, {"*"}))
        policy.assign_role("reader-agent", "reader")

        with ProcessContext(
            process_id=unique_process_id,
            agent_id="reader-agent",
            access_policy=policy,
        ) as ctx:
            # Should have read access
            assert ctx.check_access(Permission.READ)

            # Should not have write access
            assert not ctx.check_access(Permission.WRITE)
