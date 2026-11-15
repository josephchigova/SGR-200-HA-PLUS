"""Daily subscription deadline check. Schedule it once a day (see deploy/sgr-reminders.timer)."""

from datetime import date

from django.core.management.base import BaseCommand

from apps.subscriptions.reminders import check_subscription_deadlines, record_run


class Command(BaseCommand):
    help = "Create reminders for subscriptions that are due soon, due today, overdue or still unpaid."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Check as if today were this date (YYYY-MM-DD). For testing.")

    def handle(self, *args, **options):
        today = date.fromisoformat(options["date"]) if options.get("date") else None
        result = check_subscription_deadlines(today=today)
        record_run(result)
        self.stdout.write(f"{result['date']}: {result['notifications_created']} notifications created, {result['farmers_not_paid']} farmers not fully paid.")
