from datetime import date
from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.finance.ledger import (
    account_by_code,
    cash_book_for,
    ensure_default_chart,
    ensure_open_period,
    post_recognized_receipt,
)
from apps.finance.models import RecognizedReceipt

from .models import FarmerSubscription, SubscriptionPayment
from .services import SubscriptionPaymentService


@transaction.atomic
def receive_subscription_payment(*, farmer, season, amount, payment_date, method, reference="", notes="", idempotency_key, user):
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValidationError({"amount": ["Enter an amount greater than zero."]})
    if method not in {SubscriptionPayment.METHOD_CASH, SubscriptionPayment.METHOD_BANK}:
        raise ValidationError({"method": ["Choose Cash or Bank."]})
    if isinstance(payment_date, str):
        payment_date = date.fromisoformat(payment_date)
    if not payment_date:
        raise ValidationError({"payment_date": ["A payment date is required."]})
    if not idempotency_key:
        raise ValidationError({"idempotency_key": ["A payment key is required."]})

    existing = SubscriptionPayment.objects.select_related("subscription").filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing.subscription, existing, False

    _, category, expected_amount = SubscriptionPaymentService.farmer_subscription_details(farmer)
    subscription, _created = FarmerSubscription.objects.get_or_create(
        farmer=farmer,
        season=season,
        defaults={"category": category, "expected_amount": expected_amount, "paid_amount": Decimal("0.00"), "outstanding_amount": expected_amount, "payment_status": "UNPAID"},
    )
    subscription = FarmerSubscription.objects.select_for_update().get(pk=subscription.pk)
    subscription.expected_amount = expected_amount
    subscription.category = category
    outstanding = expected_amount - subscription.paid_amount
    if amount > outstanding:
        raise ValidationError({"amount": [f"The payment cannot exceed the outstanding balance of {outstanding:.2f}."]})

    payment = SubscriptionPayment.objects.create(
        subscription=subscription,
        amount=amount,
        payment_date=payment_date,
        method=method,
        reference=reference or "",
        notes=notes or "",
        idempotency_key=idempotency_key,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    subscription.paid_amount += amount
    summary = SubscriptionPaymentService.calculate_summary(expected_amount, subscription.paid_amount)
    subscription.outstanding_amount = summary["outstanding_amount"]
    subscription.payment_status = summary["payment_status"]
    subscription.payment_date = payment_date
    subscription.save()
    _post_receipt(payment, user)
    return subscription, payment, True


def _post_receipt(payment, user):
    ensure_default_chart()
    ensure_open_period(payment.payment_date)
    revenue = account_by_code("4000")
    cash_account = cash_book_for(payment.method)
    receipt = RecognizedReceipt.objects.create(
        receipt_number=f"SUB-{payment.pk:06d}",
        payer=payment.subscription.farmer.full_name or payment.subscription.farmer.surname,
        received_on=payment.payment_date,
        amount=payment.amount,
        method=payment.method,
        external_reference=payment.reference,
        recognition=RecognizedReceipt.EARNED,
        credit_account=revenue,
        cash_account=cash_account,
        farmer=payment.subscription.farmer,
        subscription=payment.subscription,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    post_recognized_receipt(receipt.pk, user)
