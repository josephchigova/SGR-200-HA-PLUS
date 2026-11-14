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
    LeadFarmerPermission,
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
        # Ordinary farmers are registered by their lead farmer. Administrators register lead farmers.
        {User.ROLE_LEAD_FARMER},
        FarmerWorkflowPermission.write_roles,
        FarmerWorkflowPermission.delete_roles,
        VerificationPermission.allowed_roles,
        FarmerWorkflowPermission.read_roles,
    ),
    "lead_registration": (
        LeadFarmerPermission.write_roles,
        LeadFarmerPermission.write_roles,
        set(), set(), set(), set(),
    ),
    "verification": (
        VerificationPermission.allowed_roles | {User.ROLE_AUDITOR, User.ROLE_MEMBERSHIP_OFFICER},
        set(), set(), set(),
        VerificationPermission.allowed_roles,
        VerificationPermission.allowed_roles | {User.ROLE_AUDITOR},
    ),
    # Clusters are managed through lead farmers. A lead farmer sees only their own cluster on the dashboard.
    "clusters": (
        LeadFarmerPermission.read_roles,
        LeadFarmerPermission.write_roles,
        LeadFarmerPermission.write_roles,
        set(),
        LeadFarmerPermission.write_roles,
        LeadFarmerPermission.read_roles,
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


# Rights that belong to a role, not to rank. Only a lead farmer registers ordinary farmers,
# so a superuser account does not receive this one automatically.
ROLE_BOUND = {("farmers", "create")}


def _allowed(user, module, action, roles):
    if user.is_superuser and (module, action) not in ROLE_BOUND:
        return True
    return user.role in roles


def capabilities(user):
    """Return {module: {action: bool}} for one user."""
    result = {}
    for module, role_sets in MATRIX.items():
        result[module] = {
            action: bool(_allowed(user, module, action, roles))
            for action, roles in zip(ACTIONS, role_sets)
        }
    return result


def can(user, module, action="view"):
    if not user or not user.is_authenticated:
        return False
    return _allowed(user, module, action, MATRIX[module][ACTIONS.index(action)])


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
