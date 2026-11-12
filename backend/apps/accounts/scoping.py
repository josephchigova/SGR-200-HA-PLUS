"""Record-level visibility shared by every module.

A lead farmer sees the farmers in the assigned cluster. A district or provincial
coordinator sees the assigned district or province. Every other role that is allowed
to open a module sees all of its records.
"""


def scope_farmers(queryset, user):
    return scope_by_farmer(queryset, user, prefix="")


def scope_by_farmer(queryset, user, prefix="farmer__"):
    if not user or not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset
    if user.role == user.ROLE_LEAD_FARMER:
        if not user.assigned_cluster_id:
            return queryset.none()
        return queryset.filter(**{f"{prefix}cluster_id": user.assigned_cluster_id})
    if user.role == user.ROLE_DISTRICT_COORDINATOR:
        if not user.district_id:
            return queryset.none()
        return queryset.filter(**{f"{prefix}district_id": user.district_id})
    if user.role == user.ROLE_PROVINCIAL_COORDINATOR:
        if not user.province_id:
            return queryset.none()
        return queryset.filter(**{f"{prefix}province_id": user.province_id})
    return queryset


def is_scoped(user):
    return not user.is_superuser and user.role in {
        user.ROLE_LEAD_FARMER,
        user.ROLE_DISTRICT_COORDINATOR,
        user.ROLE_PROVINCIAL_COORDINATOR,
    }
