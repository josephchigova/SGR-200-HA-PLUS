import csv
import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from . import audit
from .models import AuditLog
from .permissions import AuditReadPermission, UserAdminPermission
from .roles import can, matrix_rows
from .serializers import (
    AuditLogSerializer,
    ChangePasswordSerializer,
    ManagedUserSerializer,
    RegisterSerializer,
    UserSerializer,
    check_password_strength,
)

User = get_user_model()
logger = logging.getLogger("apps.accounts")


class EmailTokenObtainPairView(TokenObtainPairView):
    """Email login that ignores a stale bearer token and does not log secrets."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        email = str(request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        if not email or not password:
            logger.warning("Login rejected because the email or password was empty")
            raise AuthenticationFailed("Enter both an email address and a password.")
        user = User.objects.filter(email__iexact=email).order_by("id").first()
        if user is None or not user.check_password(password):
            logger.warning("Login failed for %s", email)
            audit.record(email=email, action=AuditLog.ACTION_LOGIN_FAILED, module="auth", summary="Sign-in failed", request=request, status_code=401)
            raise AuthenticationFailed("The email or password is incorrect.")
        if not user.is_active:
            logger.warning("Login rejected for inactive account %s", email)
            audit.record(user=user, action=AuditLog.ACTION_LOGIN_FAILED, module="auth", summary="Sign-in refused: account inactive", request=request, status_code=401)
            raise AuthenticationFailed("This account is inactive. Ask an administrator to activate it.")
        refresh = RefreshToken.for_user(user)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        logger.info("Login succeeded for %s", user.email)
        audit.record(user=user, action=AuditLog.ACTION_LOGIN, module="auth", summary="Signed in", request=request, status_code=200)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


class RegisterView(generics.CreateAPIView):
    """Request an account. It stays inactive until an administrator approves it."""

    queryset = User.objects.all()
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        return Response({"detail": "Your password has been changed."})


class PasswordResetRequestView(APIView):
    """Email a reset link. The reply is the same whether or not the address exists."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        email = str(request.data.get("email") or "").strip()
        user = User.objects.filter(email__iexact=email, is_active=True).first() if email else None
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?uid={uid}&token={token}"
            try:
                send_mail(
                    "Reset your SGR 200HA+ password",
                    "A password reset was requested for your SGR 200HA+ account.\n\n"
                    f"Open this link to choose a new password:\n{link}\n\n"
                    "The link expires after a short time. If you did not ask for it, ignore this message.",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
                audit.record(user=user, action=AuditLog.ACTION_PASSWORD, module="auth", summary="Password reset link requested", request=request, status_code=200)
            except Exception:
                logger.exception("Password reset email could not be sent")
        return Response({"detail": "If that email belongs to an active account, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        invalid = Response({"detail": "This reset link is invalid or has expired. Request a new one."}, status=400)
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(str(request.data.get("uid") or ""))), is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return invalid
        if not default_token_generator.check_token(user, str(request.data.get("token") or "")):
            return invalid
        try:
            password = check_password_strength(str(request.data.get("new_password") or ""), user)
        except Exception as error:
            return Response({"new_password": getattr(error, "detail", ["Choose a stronger password."])}, status=400)
        user.set_password(password)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        audit.record(user=user, action=AuditLog.ACTION_PASSWORD, module="auth", summary="Password reset with emailed link", request=request, status_code=200)
        return Response({"detail": "Your password has been reset. Sign in with the new password."})


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Accounts can be deactivated or deleted.

    Deleting a login never deletes business records: every reference to a user is
    cleared rather than cascaded, and the audit log keeps the email as text.
    """

    serializer_class = ManagedUserSerializer
    permission_classes = [UserAdminPermission]
    pagination_class = StandardPagination

    def get_queryset(self):
        queryset = User.objects.select_related("province", "district", "assigned_cluster", "farmer").order_by("first_name", "last_name", "email")
        params = self.request.query_params
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(username__icontains=search)
            )
        if params.get("role"):
            queryset = queryset.filter(role=params["role"])
        if params.get("is_active") in {"true", "false"}:
            queryset = queryset.filter(is_active=params["is_active"] == "true")
        return queryset

    def destroy(self, request, *args, **kwargs):
        from django.db.models import ProtectedError

        account = self.get_object()
        if account.pk == request.user.pk:
            return Response({"detail": "You cannot delete your own account."}, status=status.HTTP_400_BAD_REQUEST)
        if account.role == User.ROLE_SUPER_ADMIN and account.is_active:
            others = User.objects.filter(role=User.ROLE_SUPER_ADMIN, is_active=True).exclude(pk=account.pk)
            if not others.exists():
                return Response({"detail": "This is the only active Super Administrator. Make another one before deleting it."}, status=status.HTTP_400_BAD_REQUEST)
        email, role, label = account.email, account.role, account.get_role_display()
        try:
            account.delete()
        except ProtectedError:
            return Response({"detail": "This account is still linked to records that need it. Deactivate it instead."}, status=status.HTTP_400_BAD_REQUEST)
        audit.record(user=request.user, action=AuditLog.ACTION_DELETE, module="users", object_id=kwargs.get("pk"),
                     summary=f"Deleted the {label} account {email}"[:255], request=request, status_code=204)
        if role == User.ROLE_LEAD_FARMER:
            logger.info("Lead farmer login %s deleted. The cluster and its farmers are kept.", email)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        temporary = secrets.token_urlsafe(9)
        user.set_password(temporary)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        return Response({
            "detail": "A temporary password was set. Give it to the user. They must change it after signing in.",
            "temporary_password": temporary,
        })


class RoleMatrixView(APIView):
    permission_classes = [UserAdminPermission]

    def get(self, request):
        return Response(matrix_rows())


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [AuditReadPermission]
    pagination_class = StandardPagination

    def get_queryset(self):
        queryset = AuditLog.objects.all()
        params = self.request.query_params
        if params.get("action"):
            queryset = queryset.filter(action=params["action"])
        if params.get("module"):
            queryset = queryset.filter(module=params["module"])
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(user_email__icontains=search) | Q(summary__icontains=search) | Q(path__icontains=search))
        start = parse_date(params.get("start_date") or "")
        end = parse_date(params.get("end_date") or "")
        if start:
            queryset = queryset.filter(created_at__date__gte=start)
        if end:
            queryset = queryset.filter(created_at__date__lte=end)
        return queryset

    @action(detail=False, methods=["get"], url_path="modules")
    def modules(self, request):
        names = AuditLog.objects.exclude(module="").values_list("module", flat=True).distinct().order_by("module")
        return Response({"modules": list(names), "actions": [{"code": code, "label": label} for code, label in AuditLog.ACTION_CHOICES]})

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="SGR_Audit_Log.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow(["Date and time", "User", "Role", "Action", "Module", "Record", "Summary", "Fields sent", "IP address"])
        for row in self.get_queryset()[:10000]:
            writer.writerow([
                timezone.localtime(row.created_at).strftime("%Y-%m-%d %H:%M:%S"), row.user_email, row.user_role,
                row.get_action_display(), row.module, row.object_id, row.summary, ", ".join(row.changed_fields or []), row.ip_address or "",
            ])
        return response


class NotificationsView(APIView):
    """Work waiting for the signed-in user, counted from live records."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.farmers.models import Farmer
        from apps.recovery.models import InputDebt
        from apps.subscriptions.models import FarmerSubscription

        from .scoping import scope_by_farmer, scope_farmers

        user = request.user
        items = []

        def add(key, count, title, detail, url, tone="info"):
            if count:
                items.append({"key": key, "count": count, "title": title, "detail": detail, "url": url, "tone": tone})

        if user.must_change_password:
            add("password", 1, "Change your temporary password", "An administrator set your password. Choose your own.", "/account", "warning")
        if can(user, "farmers"):
            farmers = scope_farmers(Farmer.objects.all(), user)
            pending = farmers.filter(verification_status__in=[Farmer.STATUS_SUBMITTED, Farmer.STATUS_UNDER_REVIEW, Farmer.STATUS_PENDING]).count()
            rejected = farmers.filter(verification_status=Farmer.STATUS_REJECTED).count()
            if can(user, "farmers", "approve"):
                add("verification", pending, f"{pending} farmer{'s' if pending != 1 else ''} awaiting verification", "Review the submitted registrations.", "/verification", "warning")
            elif can(user, "farmers", "create"):
                add("verification", pending, f"{pending} registration{'s' if pending != 1 else ''} with the verification team", "No action needed until a decision is made.", "/farmers")
            if can(user, "farmers", "approve"):
                from apps.farmers.models import FarmerChangeRequest

                waiting = scope_by_farmer(FarmerChangeRequest.objects.filter(status=FarmerChangeRequest.PENDING), user).count()
                add("changes", waiting, f"{waiting} change request{'s' if waiting != 1 else ''} to review", "Lead farmers asked to change approved details.", "/verification?queue=changes", "warning")
            if can(user, "farmers", "edit"):
                add("rejected", rejected, f"{rejected} rejected registration{'s' if rejected != 1 else ''}", "Correct the record and resubmit it.", "/farmers", "danger")
        if can(user, "subscriptions"):
            subscriptions = scope_by_farmer(FarmerSubscription.objects.all(), user)
            unpaid = subscriptions.exclude(payment_status__iexact="paid").count()
            add("subscriptions", unpaid, f"{unpaid} subscription{'s' if unpaid != 1 else ''} not fully paid", "These farmers cannot receive inputs yet.", "/subscriptions", "warning")
        if can(user, "recovery"):
            debts = scope_by_farmer(InputDebt.objects.all(), user).exclude(status=InputDebt.STATUS_FULLY_RECOVERED).count()
            add("recovery", debts, f"{debts} input debt{'s' if debts != 1 else ''} still to recover", "Grain deliveries reduce these balances.", "/recovery")
        if can(user, "users", "edit"):
            waiting = User.objects.filter(is_active=False, last_login__isnull=True).count()
            add("accounts", waiting, f"{waiting} account request{'s' if waiting != 1 else ''} awaiting approval", "Assign a role and activate the account.", "/users", "warning")
        return Response({"count": sum(1 for _ in items), "items": items})
