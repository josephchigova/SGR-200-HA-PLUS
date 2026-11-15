"""Subscription deadline reminders.

Each agricultural year (Season) can carry a subscription due date. A daily check finds
approved farmers whose subscription for that year is not fully paid and notifies the users
who look after them:

* due soon      - within SUBSCRIPTION_REMINDER_DAYS of the due date
* due today     - on the due date
* overdue       - the first day after the due date
* still unpaid  - every SUBSCRIPTION_STILL_UNPAID_DAYS after that

Every notice has a dedupe key, so running the check again never repeats one. Amounts are
stored only for recipients allowed to see money; lead farmers get the payment status.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Notification, ScheduledJobRun, User
from apps.accounts.privacy import hides_money
from apps.accounts.roles import can
from apps.accounts.scoping import scope_farmers
from apps.farmers.models import Farmer
from apps.programmes.models import Season

from .models import FarmerSubscription
from .services import SubscriptionPaymentService, allocated_hectares

JOB_NAME = "subscription-reminders"
APPROVED = (Farmer.STATUS_VERIFIED, Farmer.STATUS_APPROVED)


def reminder_days():
    return int(getattr(settings, "SUBSCRIPTION_REMINDER_DAYS", 7))


def still_unpaid_days():
    return int(getattr(settings, "SUBSCRIPTION_STILL_UNPAID_DAYS", 30))


def _stage(due_date, today):
    """Which notice, if any, a farmer who has not paid should get today. Returns (kind, period, days_overdue)."""
    days = (today - due_date).days
    if days < -reminder_days():
        return None
    if days < 0:
        return Notification.KIND_SUBSCRIPTION_UPCOMING, "", 0
    if days == 0:
        return Notification.KIND_SUBSCRIPTION_DUE, "", 0
    step = still_unpaid_days()
    if days >= step:
        # One reminder per period: at 30, 60, 90 days... A missed day is caught up on the next run.
        return Notification.KIND_SUBSCRIPTION_STILL_UNPAID, str(days // step), days
    return Notification.KIND_SUBSCRIPTION_OVERDUE, "", days


def _text(kind, farmer, season, due_date, days, status, amount):
    name = farmer.full_name
    due = due_date.strftime("%d %b %Y")
    money = f" {amount:,.2f} USD is outstanding." if amount is not None else ""
    status_text = {"UNPAID": "Not paid", "PARTIAL": "Partly paid"}.get(status, status.title())
    if kind == Notification.KIND_SUBSCRIPTION_UPCOMING:
        left = (due_date - timezone.localdate()).days
        return (f"{name}: subscription due in {left} day{'s' if left != 1 else ''}",
                f"The {season} subscription is due on {due}. Payment status: {status_text}.{money}")
    if kind == Notification.KIND_SUBSCRIPTION_DUE:
        return (f"{name}: subscription due today", f"The {season} subscription is due today ({due}). Payment status: {status_text}.{money}")
    if kind == Notification.KIND_SUBSCRIPTION_OVERDUE:
        return (f"{name}: subscription overdue", f"The {season} subscription was due on {due} and is {days} day{'s' if days != 1 else ''} overdue. Payment status: {status_text}.{money}")
    return (f"{name}: subscription still unpaid after {days} days", f"The {season} subscription was due on {due}. It is {days} days overdue. Payment status: {status_text}.{money}")


def _recipients():
    users = User.objects.filter(is_active=True).select_related("assigned_cluster")
    return [user for user in users if can(user, "subscriptions")]


def check_subscription_deadlines(today=None):
    """Create any reminders due today. Safe to run as often as wanted."""
    today = today or timezone.localdate()
    earliest = today - timedelta(days=365)
    latest = today + timedelta(days=reminder_days())
    created = 0
    farmers_flagged = 0
    recipients = _recipients()
    for season in Season.objects.filter(subscription_due_date__isnull=False, subscription_due_date__range=(earliest, latest)):
        stage = _stage(season.subscription_due_date, today)
        if stage is None:
            continue
        kind, period, days = stage
        farmers = list(Farmer.objects.filter(verification_status__in=APPROVED, is_active=True))
        ids = [farmer.pk for farmer in farmers]
        paid = dict(FarmerSubscription.objects.filter(farmer_id__in=ids, season__iexact=season.name).values_list("farmer_id", "paid_amount"))
        hectares = allocated_hectares(ids, season.name)
        owing = {}
        for farmer in farmers:
            _, _, expected = SubscriptionPaymentService.subscription_details(hectares.get(farmer.pk, Decimal("0")))
            summary = SubscriptionPaymentService.calculate_display_summary(expected, paid.get(farmer.pk, Decimal("0")))
            if summary["payment_status"] != "PAID":
                owing[farmer.pk] = (farmer, summary["payment_status"], summary["outstanding_amount"])
        farmers_flagged += len(owing)
        if not owing:
            continue
        notices = []
        for user in recipients:
            visible = set(scope_farmers(Farmer.objects.filter(pk__in=owing), user).values_list("pk", flat=True))
            private = hides_money(user)
            for farmer_id in visible:
                farmer, status, outstanding = owing[farmer_id]
                amount = None if private else outstanding
                title, body = _text(kind, farmer, season.name, season.subscription_due_date, days, status, amount)
                notices.append(Notification(
                    recipient=user, kind=kind,
                    dedupe_key=f"subscription:{season.pk}:{farmer_id}:{kind}:{period}",
                    title=title[:200], body=body, url=f"/subscriptions?farmer={farmer_id}",
                    tone="danger" if kind in {Notification.KIND_SUBSCRIPTION_OVERDUE, Notification.KIND_SUBSCRIPTION_STILL_UNPAID} else "warning",
                    farmer=farmer, season_name=season.name, due_date=season.subscription_due_date, days_overdue=days,
                    payment_status=status, amount_due=amount,
                ))
        before = Notification.objects.count()
        Notification.objects.bulk_create(notices, ignore_conflicts=True, batch_size=500)
        created += Notification.objects.count() - before
    return {"date": today.isoformat(), "notifications_created": created, "farmers_not_paid": farmers_flagged}


def run_if_due(min_hours=6, today=None):
    """The backstop: run the check when the scheduled job has not run for a while.

    The scheduled job (management command send_subscription_reminders) is the main way the
    check runs. This keeps reminders flowing even if the schedule was never set up.
    """
    now = timezone.now()
    with transaction.atomic():
        job, _ = ScheduledJobRun.objects.get_or_create(name=JOB_NAME)
        job = ScheduledJobRun.objects.select_for_update(skip_locked=True).filter(pk=job.pk).first()
        if job is None:
            return None
        if job.last_started_at and now - job.last_started_at < timedelta(hours=min_hours):
            return None
        job.last_started_at = now
        job.save(update_fields=["last_started_at"])
    result = check_subscription_deadlines(today=today)
    ScheduledJobRun.objects.filter(name=JOB_NAME).update(last_finished_at=timezone.now(), last_result=result)
    return result


def record_run(result):
    now = timezone.now()
    ScheduledJobRun.objects.update_or_create(name=JOB_NAME, defaults={"last_started_at": now, "last_finished_at": now, "last_result": result})
