from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AuthenticationSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="auth@example.com",
            username="auth-user",
            password="StrongPass123!",
            role=User.ROLE_VIEWER,
        )
        self.client = APIClient()

    def test_valid_login_returns_access_and_refresh_tokens(self):
        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": "auth@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_invalid_login_is_rejected(self):
        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": "auth@example.com", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("incorrect", response.data["detail"].lower())

    def test_login_accepts_email_case_and_ignores_an_expired_bearer_token(self):
        access = RefreshToken.for_user(self.user).access_token
        access.set_exp(lifetime=timedelta(seconds=-30))
        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": " Auth@Example.com ", "password": "StrongPass123!"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_unauthenticated_and_expired_tokens_are_rejected(self):
        url = reverse("farmer-list")
        self.assertEqual(self.client.get(url).status_code, 401)

        access = RefreshToken.for_user(self.user).access_token
        access.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_viewer_can_read_golden_path_lists_but_cannot_write_workflow_records(self):
        self.client.force_authenticate(user=self.user)
        readable_endpoints = [
            "/api/programmes/",
            "/api/seasons/",
            "/api/arda-requests/",
            "/api/arda-request-batches/",
            "/api/arda-farmer-requests/",
            "/api/inputs/",
            "/api/input-allocations/",
            "/api/production-plans/",
            "/api/farmer-productions/",
            "/api/deliveries/",
            "/api/recovery-records/",
            "/api/input-debts/",
            "/api/farmer-subscriptions/",
        ]

        for endpoint in readable_endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 200)

        restricted_response = self.client.post(
            "/api/seasons/",
            {"name": "Viewer Restricted Season", "start_date": "2026-10-01", "end_date": "2027-09-30"},
            format="json",
        )
        self.assertEqual(restricted_response.status_code, 403)