"""The role and permission matrix sent to the interface.

The sets on the permission classes stay the single source of truth. This module only
reads them, so the navigation a user sees always matches what the API will accept.
"""

from apps.reports.catalog import FINANCE_ROLES as FINANCE_REPORT_ROLES
from apps.reports.catalog import READERS as OPERATIONS_REPORT_ROLES
from apps.reports.catalog import USER_ROLES as USER_REPORT_ROLES

from .models import User
from .permissions import (
    AuditReadPermission,
    FarmerWorkflowPermission,
    FinanceAccessPermission,
    LocationReferencePermission,
    ProgrammeWorkflowPermission,
    RecoveryWorkflowPermission,
    SubscriptionWorkflowPermission,
    UserAdminPermission,
    VerificationPermission,
)

ALL_ROLES = {code for code, _ in User.ROLE_CHOICES}
ADMIN = {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE}
PROGRAMME_WRITE = set(ProgrammeWorkflowPermission.write_roles)

# module: (view, create, edit, delete, approve, export)
MATRIX = {
    "dashboard": (ALL_ROLES, set(), set(), set(), set(), set()),
    "farmers": (
        FarmerWorkflowPermission.read_roles,
        {User.ROLE_SUPER_ADMIN, User.ROLE_LEAD_FARMER},
        FarmerWorkflowPermission.write_roles,
        FarmerWorkflowPermission.delete_roles,
        VerificationPermission.allowed_roles,
        FarmerWorkflowPermission.read_roles,
    ),
    "lead_registration": (
        {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_MEMBERSHIP_OFFICER},
        {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_MEMBERSHIP_OFFICER},
        set(), set(), set(), set(),
    ),
    "verification": (
        VerificationPermission.allowed_roles | {User.ROLE_AUDITOR, User.ROLE_MEMBERSHIP_OFFICER},
        set(), set(), set(),
        VerificationPermission.allowed_roles,
        VerificationPermission.allowed_roles | {User.ROLE_AUDITOR},
    ),
    "clusters": (
        # A lead farmer is tied to one cluster, so there is nothing to choose or manage here.
        ALL_ROLES - {User.ROLE_PROCUREMENT_OFFICER, User.ROLE_STORES_OFFICER, User.ROLE_LEAD_FARMER},
        LocationReferencePermission.write_roles,
        LocationReferencePermission.write_roles,
        ADMIN, set(), set(),
    ),
    "subscriptions": (
        SubscriptionWorkflowPermission.read_roles,
        SubscriptionWorkflowPermission.write_roles,
        SubscriptionWorkflowPermission.write_roles,
        ADMIN,
        SubscriptionWorkflowPermission.write_roles,
        SubscriptionWorkflowPermission.read_roles - {User.ROLE_LEAD_FARMER, User.ROLE_VIEWER},
    ),
    "crops": (ProgrammeWorkflowPermission.read_roles - {User.ROLE_LEAD_FARMER}, PROGRAMME_WRITE, PROGRAMME_WRITE, ADMIN, set(), set()),
    "programmes": (ProgrammeWorkflowPermission.read_roles - {User.ROLE_LEAD_FARMER}, PROGRAMME_WRITE, PROGRAMME_WRITE, ADMIN, set(), set()),
    "arda": (ProgrammeWorkflowPermission.read_roles - {User.ROLE_LEAD_FARMER}, PROGRAMME_WRITE, PROGRAMME_WRITE, ADMIN, PROGRAMME_WRITE, set()),
    "allocations": (ProgrammeWorkflowPermission.read_roles, PROGRAMME_WRITE, PROGRAMME_WRITE, ADMIN, PROGRAMME_WRITE, set()),
    "production": (ProgrammeWorkflowPermission.read_roles, PROGRAMME_WRITE, PROGRAMME_WRITE, ADMIN, set(), set()),
    "planting": (ProgrammeWorkflowPermission.read_roles, PROGRAMME_WRITE, PROGRAMME_WRITE, ADMIN, set(), set()),
    "deliveries": (RecoveryWorkflowPermission.read_roles, RecoveryWorkflowPermission.write_roles, set(), set(), set(), set()),
    "recovery": (RecoveryWorkflowPermission.read_roles, set(), RecoveryWorkflowPermission.write_roles, set(), set(), set()),
    "finance": (
        FinanceAccessPermission.read_roles,
        FinanceAccessPermission.write_roles,
        FinanceAccessPermission.write_roles,
        set(),
        FinanceAccessPermission.write_roles,
        FinanceAccessPermission.read_roles,
    ),
    "reports": (OPERATIONS_REPORT_ROLES, set(), set(), set(), set(), OPERATIONS_REPORT_ROLES),
    "reports_finance": (FINANCE_REPORT_ROLES, set(), set(), set(), set(), FINANCE_REPORT_ROLES),
    "reports_users": (USER_REPORT_ROLES, set(), set(), set(), set(), USER_REPORT_ROLES),
    "users": (
        UserAdminPermission.read_roles,
        UserAdminPermission.write_roles,
        UserAdminPermission.write_roles,
        UserAdminPermission.write_roles,
        UserAdminPermission.write_roles,
        set(),
    ),
    "audit": (AuditReadPermission.allowed_roles, set(), set(), set(), set(), AuditReadPermission.allowed_roles),
}
ACTIONS = ("view", "create", "edit", "delete", "approve", "export")


def capabilities(user):
    """Return {module: {action: bool}} for one user."""
    result = {}
    for module, role_sets in MATRIX.items():
        result[module] = {
            action: bool(user.is_superuser or user.role in roles)
            for action, roles in zip(ACTIONS, role_sets)
        }
    return result


def can(user, module, action="view"):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.role in MATRIX[module][ACTIONS.index(action)]


def matrix_rows():
    """The whole matrix, for the role reference shown in user management."""
    labels = dict(User.ROLE_CHOICES)
    rows = []
    for code, label in User.ROLE_CHOICES:
        rows.append({
            "role": code,
            "label": label,
            "modules": {
                module: [action for action, roles in zip(ACTIONS, role_sets) if code in roles]
                for module, role_sets in MATRIX.items()
            },
        })
    return {"roles": rows, "labels": labels, "actions": list(ACTIONS), "modules": list(MATRIX)}
