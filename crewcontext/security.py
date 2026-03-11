"""Access control for CrewContext.

Provides scope-based RBAC (Role-Based Access Control) for multi-agent systems.

Usage:
    from crewcontext.security import AccessPolicy, Role, Permission
    
    # Define roles
    admin_role = Role(
        name="admin",
        permissions=[Permission.READ, Permission.WRITE, Permission.DELETE],
        scopes=["*"]  # All scopes
    )
    
    auditor_role = Role(
        name="auditor",
        permissions=[Permission.READ],
        scopes=["finance", "compliance"]
    )
    
    # Create policy
    policy = AccessPolicy()
    policy.add_role(admin_role)
    policy.add_role(auditor_role)
    
    # Assign roles to agents
    policy.assign_role("agent-1", "admin")
    policy.assign_role("agent-2", "auditor")
    
    # Check permissions
    if policy.can_access("agent-2", "finance", Permission.READ):
        print("Agent can read finance scope")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)


class Permission(Enum):
    """Available permissions for access control."""
    READ = auto()      # Query events, entities
    WRITE = auto()     # Emit events, save entities
    DELETE = auto()    # Delete events (if enabled)
    ADMIN = auto()     # Full access including policy changes


class AccessDecision(Enum):
    """Result of an access control decision."""
    ALLOW = auto()
    DENY = auto()
    NOT_APPLICABLE = auto()


@dataclass
class Role:
    """A role with permissions and scope access.

    Attributes:
        name: Unique role identifier.
        permissions: Set of permissions this role grants.
        scopes: Set of scopes this role can access. "*" means all scopes.
        description: Human-readable description.
    """
    name: str
    permissions: Set[Permission] = field(default_factory=set)
    scopes: Set[str] = field(default_factory=set)
    description: str = ""

    def has_permission(self, permission: Permission) -> bool:
        """Check if role has a specific permission."""
        return permission in self.permissions

    def can_access_scope(self, scope: str) -> bool:
        """Check if role can access a specific scope."""
        return "*" in self.scopes or scope in self.scopes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "permissions": [p.name for p in self.permissions],
            "scopes": list(self.scopes),
            "description": self.description,
        }


@dataclass
class AccessRule:
    """Fine-grained access rule for complex policies.

    Allows conditional access based on event type, time, etc.

    Attributes:
        name: Rule identifier.
        roles: Roles this rule applies to.
        scopes: Scopes this rule applies to.
        permissions: Permissions granted/denied by this rule.
        allow: If True, grant access; if False, deny.
        conditions: Optional conditions (e.g., event types, time windows).
    """
    name: str
    roles: Set[str] = field(default_factory=set)
    scopes: Set[str] = field(default_factory=set)
    permissions: Set[Permission] = field(default_factory=set)
    allow: bool = True
    conditions: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher priority rules evaluated first

    def matches(self, context: AccessContext) -> bool:
        """Check if this rule matches the access context."""
        # Check role
        if context.role and context.role not in self.roles:
            return False

        # Check scope
        if self.scopes and context.scope not in self.scopes and "*" not in self.scopes:
            return False

        # Check permission
        if context.permission and context.permission not in self.permissions:
            return False

        # Check conditions
        for key, value in self.conditions.items():
            context_value = getattr(context, key, None)
            if isinstance(value, list):
                if context_value not in value:
                    return False
            elif context_value != value:
                return False

        return True


@dataclass
class AccessContext:
    """Context for an access control decision.

    Attributes:
        agent_id: Agent requesting access.
        role: Agent's current role.
        scope: Scope being accessed.
        permission: Permission being requested.
        event_type: Optional event type (for fine-grained rules).
        metadata: Additional context metadata.
    """
    agent_id: str
    scope: str
    permission: Permission
    role: Optional[str] = None
    event_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEntry:
    """Audit log entry for access control decisions.

    Attributes:
        timestamp: When the decision was made.
        agent_id: Agent that requested access.
        action: Action attempted (READ, WRITE, etc.).
        scope: Scope being accessed.
        decision: ALLOW or DENY.
        reason: Explanation for the decision.
        metadata: Additional context.
    """
    timestamp: datetime
    agent_id: str
    action: str
    scope: str
    decision: AccessDecision
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "agent_id": self.agent_id,
            "action": self.action,
            "scope": self.scope,
            "decision": self.decision.name,
            "reason": self.reason,
            "metadata": self.metadata,
        }


class AccessPolicy:
    """Main access control policy manager.

    Features:
    - Role-based access control (RBAC)
    - Scope-based isolation
    - Fine-grained access rules
    - Audit logging

    Usage:
        policy = AccessPolicy(enable_audit=True)
        policy.add_role(Role("admin", {Permission.READ, Permission.WRITE}, {"*"}))
        policy.assign_role("agent-1", "admin")

        if policy.can_access("agent-1", "finance", Permission.READ):
            # Proceed with operation
            pass
    """

    def __init__(
        self,
        enable_audit: bool = True,
        default_deny: bool = True,
    ):
        self._roles: Dict[str, Role] = {}
        self._agent_roles: Dict[str, Set[str]] = {}  # agent_id -> role names
        self._rules: List[AccessRule] = []
        self._audit_log: List[AuditEntry] = []
        self._enable_audit = enable_audit
        self._default_deny = default_deny  # Deny by default if no rule matches

    # -- Role management ----------------------------------------------------

    def add_role(self, role: Role) -> None:
        """Add a role to the policy."""
        self._roles[role.name] = role
        log.info("Added role: %s", role.name)

    def remove_role(self, name: str) -> bool:
        """Remove a role from the policy."""
        if name in self._roles:
            del self._roles[name]
            # Remove role assignments
            for agent_roles in self._agent_roles.values():
                agent_roles.discard(name)
            log.info("Removed role: %s", name)
            return True
        return False

    def get_role(self, name: str) -> Optional[Role]:
        """Get a role by name."""
        return self._roles.get(name)

    def list_roles(self) -> List[Dict[str, Any]]:
        """List all roles."""
        return [role.to_dict() for role in self._roles.values()]

    # -- Role assignments ---------------------------------------------------

    def assign_role(self, agent_id: str, role_name: str) -> bool:
        """Assign a role to an agent."""
        if role_name not in self._roles:
            log.warning("Cannot assign unknown role: %s", role_name)
            return False

        self._agent_roles.setdefault(agent_id, set()).add(role_name)
        log.info("Assigned role %s to agent %s", role_name, agent_id)
        return True

    def remove_role_assignment(self, agent_id: str, role_name: str) -> bool:
        """Remove a role assignment from an agent."""
        if agent_id in self._agent_roles:
            self._agent_roles[agent_id].discard(role_name)
            return True
        return False

    def get_agent_roles(self, agent_id: str) -> List[Role]:
        """Get all roles assigned to an agent."""
        role_names = self._agent_roles.get(agent_id, set())
        return [self._roles[name] for name in role_names if name in self._roles]

    def get_agent_permissions(self, agent_id: str) -> Set[Permission]:
        """Get all permissions for an agent (union of all roles)."""
        permissions: Set[Permission] = set()
        for role in self.get_agent_roles(agent_id):
            permissions.update(role.permissions)
        return permissions

    # -- Access control -----------------------------------------------------

    def can_access(
        self,
        agent_id: str,
        scope: str,
        permission: Permission,
        event_type: Optional[str] = None,
    ) -> bool:
        """Check if an agent can access a scope with a permission.

        Args:
            agent_id: Agent requesting access.
            scope: Scope being accessed.
            permission: Permission being requested.
            event_type: Optional event type for fine-grained rules.

        Returns:
            True if access is allowed, False otherwise.
        """
        agent_roles = self.get_agent_roles(agent_id)

        # Build access context
        context = AccessContext(
            agent_id=agent_id,
            scope=scope,
            permission=permission,
            event_type=event_type,
        )

        # Evaluate rules by priority
        sorted_rules = sorted(self._rules, key=lambda r: -r.priority)
        for rule in sorted_rules:
            if rule.matches(context):
                decision = AccessDecision.ALLOW if rule.allow else AccessDecision.DENY
                self._audit_access(context, decision, f"Matched rule: {rule.name}")
                return rule.allow

        # No rule matched - check role-based access
        for role in agent_roles:
            if role.has_permission(permission) and role.can_access_scope(scope):
                self._audit_access(context, AccessDecision.ALLOW, f"Role: {role.name}")
                return True

        # Default decision
        decision = AccessDecision.DENY if self._default_deny else AccessDecision.ALLOW
        self._audit_access(context, decision, "No matching rule or role")
        return not self._default_deny

    def add_rule(self, rule: AccessRule) -> None:
        """Add a fine-grained access rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)
        log.info("Added access rule: %s (priority=%d)", rule.name, rule.priority)

    def remove_rule(self, name: str) -> bool:
        """Remove an access rule."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        if len(self._rules) < before:
            log.info("Removed access rule: %s", name)
            return True
        return False

    # -- Audit logging ------------------------------------------------------

    def _audit_access(
        self,
        context: AccessContext,
        decision: AccessDecision,
        reason: str,
    ) -> None:
        """Log an access control decision."""
        if not self._enable_audit:
            return

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            agent_id=context.agent_id,
            action=context.permission.name,
            scope=context.scope,
            decision=decision,
            reason=reason,
            metadata={
                "role": context.role,
                "event_type": context.event_type,
                **context.metadata,
            },
        )
        self._audit_log.append(entry)

        # Keep only last 1000 entries
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-1000:]

        log_level = logging.INFO if decision == AccessDecision.ALLOW else logging.WARNING
        log.log(log_level, "Access %s: %s to %s (%s)", decision.name, context.agent_id, context.scope, reason)

    def get_audit_log(
        self,
        agent_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get audit log entries, optionally filtered by agent."""
        entries = self._audit_log
        if agent_id:
            entries = [e for e in entries if e.agent_id == agent_id]
        return [e.to_dict() for e in entries[-limit:]]

    def export_policy(self) -> Dict[str, Any]:
        """Export policy configuration for backup or review."""
        return {
            "roles": self.list_roles(),
            "rules": [
                {
                    "name": r.name,
                    "roles": list(r.roles),
                    "scopes": list(r.scopes),
                    "permissions": [p.name for p in r.permissions],
                    "allow": r.allow,
                    "priority": r.priority,
                }
                for r in self._rules
            ],
            "agent_assignments": {
                agent: list(roles)
                for agent, roles in self._agent_roles.items()
            },
        }


# -- Convenience functions --------------------------------------------------

def create_builtin_roles() -> List[Role]:
    """Create a set of built-in roles for common use cases.

    Returns:
        List of predefined roles.
    """
    return [
        Role(
            name="admin",
            permissions={Permission.READ, Permission.WRITE, Permission.DELETE, Permission.ADMIN},
            scopes={"*"},
            description="Full access to all scopes",
        ),
        Role(
            name="writer",
            permissions={Permission.READ, Permission.WRITE},
            scopes={"*"},
            description="Read and write access to all scopes",
        ),
        Role(
            name="reader",
            permissions={Permission.READ},
            scopes={"*"},
            description="Read-only access to all scopes",
        ),
        Role(
            name="auditor",
            permissions={Permission.READ},
            scopes={"*"},
            description="Read-only access with audit capabilities",
        ),
    ]
