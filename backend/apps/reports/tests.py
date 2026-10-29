from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()


class ReportTemplateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reports@example.com",
            username="reports-user",
            password="StrongPass123!",
            first_name="Nyasha",
            last_name="Chikuruwo",
            role=User.ROLE_AUDITOR,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_report_template_can_be_created(self):
        url = reverse("report-template-list")
        response = self.client.post(
            url,
            {
                "name": "Farmer Verification Summary",
                "code": "FARMER-VERIFICATION-SUMMARY",
                "description": "Summary of verification outcomes",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "FARMER-VERIFICATION-SUMMARY")

