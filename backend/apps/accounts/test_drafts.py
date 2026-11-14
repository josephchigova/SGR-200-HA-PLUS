from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog, FormDraft, User


class FormDraftTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="drafter", email="drafter@example.com", password="Str0ng!Passw0rd")
        self.other = User.objects.create_user(username="other", email="other@example.com", password="Str0ng!Passw0rd")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_save_restore_and_discard(self):
        response = self.client.put("/api/drafts/", {"key": "register:new", "data": {"form": {"first_name": "Tendai"}, "step": 2}}, format="json")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/drafts/", {"key": "register:new"})
        self.assertEqual(response.data["data"], {"form": {"first_name": "Tendai"}, "step": 2})
        self.client.put("/api/drafts/", {"key": "register:new", "data": {"step": 3}}, format="json")
        self.assertEqual(FormDraft.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.client.delete("/api/drafts/?key=register:new").status_code, 204)
        self.assertEqual(self.client.get("/api/drafts/", {"key": "register:new"}).status_code, 404)

    def test_passwords_are_never_stored(self):
        self.client.put("/api/drafts/", {"key": "users:new", "data": {"email": "a@b.co", "password": "x", "login_password": "y", "nested": {"new_password": "z", "ok": 1}}}, format="json")
        self.assertEqual(FormDraft.objects.get(user=self.user, key="users:new").data, {"email": "a@b.co", "nested": {"ok": 1}})

    def test_drafts_are_private(self):
        FormDraft.objects.create(user=self.other, key="register:new", data={"form": {"first_name": "Secret"}})
        self.assertEqual(self.client.get("/api/drafts/", {"key": "register:new"}).status_code, 404)
        self.client.delete("/api/drafts/?key=register:new")
        self.assertTrue(FormDraft.objects.filter(user=self.other).exists())
        self.assertEqual(self.client.get("/api/drafts/").data, [])

    def test_rejects_bad_input_and_skips_audit(self):
        self.assertEqual(self.client.put("/api/drafts/", {"key": "bad key!", "data": {}}, format="json").status_code, 400)
        self.assertEqual(self.client.put("/api/drafts/", {"key": "ok", "data": "text"}, format="json").status_code, 400)
        self.assertEqual(self.client.put("/api/drafts/", {"key": "big", "data": {"x": "a" * 300_000}}, format="json").status_code, 400)
        self.client.put("/api/drafts/", {"key": "ok", "data": {"a": 1}}, format="json")
        self.assertFalse(AuditLog.objects.filter(path__startswith="/api/drafts/").exists())

    def test_requires_sign_in(self):
        self.assertEqual(APIClient().get("/api/drafts/").status_code, 401)
