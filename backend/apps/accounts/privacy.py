"""Financial privacy.

A lead farmer follows how the cluster's farmers are doing, but never sees money:
no subscription amounts, payments, balances, input costs or prices. The fields are
removed from the API response itself, so hiding them does not depend on the interface.
"""

from decimal import Decimal


def hides_money(user):
    return bool(user and user.is_authenticated and not user.is_superuser and user.role == user.ROLE_LEAD_FARMER)


def compliance_percent(expected, paid):
    expected = Decimal(str(expected or 0))
    paid = Decimal(str(paid or 0))
    if expected <= 0:
        return 0
    return int(min(max(paid / expected * 100, Decimal(0)), Decimal(100)))


def compliance_label(percent):
    if percent >= 100:
        return "Complete"
    if percent > 0:
        return "In progress"
    return "Not started"


class MoneyPrivacyMixin:
    """Serializer mixin. List the money fields in `money_fields`."""

    money_fields = ()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is not None and hides_money(getattr(request, "user", None)):
            for name in self.money_fields:
                data.pop(name, None)
        return data
