"""System-wide audit trail.

Every successful change made through the API is written to AuditLog, together with
report and finance exports. Field names are kept. Field values are not, so passwords,
identity numbers and amounts never land in the log.
"""

import json
import logging

from .models import AuditLog

logger = logging.getLogger("apps.accounts")

WRITE_METHODS = {"POST": AuditLog.ACTION_CREATE, "PUT": AuditLog.ACTION_UPDATE, "PATCH": AuditLog.ACTION_UPDATE, "DELETE": AuditLog.ACTION_DELETE}
SKIPPED_PATHS = ("/api/auth/login/", "/api/auth/refresh/", "/api/auth/password-reset/", "/api/drafts/")
ACTION_WORDS = {
    "verify": "Verification decision",
    "receive": "Payment received",
    "approve": "Approval",
    "post": "Posted",
    "reverse": "Reversal",
    "depreciate": "Depreciation",
    "reset-password": "Password reset by administrator",
    "change-password": "Password changed",
    "dispose": "Disposal",
    "close": "Period closed",
    "reopen": "Period reopened",
}


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    address = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    return address or None


def record(*, user=None, email="", action, module="", object_id="", summary="", request=None, status_code=0, changed_fields=None):
    try:
        AuditLog.objects.create(
            user=user if getattr(user, "pk", None) else None,
            user_email=(getattr(user, "email", "") or email or "")[:254],
            user_role=getattr(user, "role", "") or "",
            action=action,
            module=module[:60],
            object_id=str(object_id or "")[:60],
            summary=summary[:255],
            method=(request.method if request else "")[:8],
            path=(request.path if request else "")[:255],
            status_code=status_code,
            changed_fields=changed_fields or [],
            ip_address=client_ip(request) if request else None,
        )
    except Exception:  # The audit trail must never break the request it describes.
        logger.exception("Audit entry could not be saved")


def _field_names(request):
    content_type = request.META.get("CONTENT_TYPE", "")
    if "application/json" not in content_type:
        return []
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return []
    if not 0 < length <= 200_000:
        return []
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    if isinstance(payload, dict):
        return sorted(str(key) for key in payload)[:60]
    return []


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        audited_write = path.startswith("/api/") and request.method in WRITE_METHODS and not path.startswith(SKIPPED_PATHS)
        fields = _field_names(request) if audited_write else []
        response = self.get_response(request)
        if response.status_code >= 400:
            return response
        if audited_write:
            self._record_write(request, response, fields)
        elif request.method == "GET" and path.startswith("/api/") and self._is_export(request):
            user = getattr(request, "user", None)
            if getattr(user, "is_authenticated", False):
                record(
                    user=user,
                    action=AuditLog.ACTION_EXPORT,
                    module=self._module(request),
                    summary=f"Exported {path.rstrip('/').split('/')[-2 if path.rstrip('/').endswith('export') else -1]} as {(self._export_format(request) or 'csv').upper()}",
                    request=request,
                    status_code=response.status_code,
                )
        return response

    @staticmethod
    def _export_format(request):
        return (request.GET.get("file_format") or request.GET.get("format") or "").lower()

    def _is_export(self, request):
        return request.path.rstrip("/").endswith("/export") or self._export_format(request) in {"pdf", "csv", "xlsx"}

    @staticmethod
    def _module(request):
        parts = [part for part in request.path.split("/") if part]
        return parts[1] if len(parts) > 1 else ""

    def _record_write(self, request, response, fields):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            user = None
        match = getattr(request, "resolver_match", None)
        kwargs = getattr(match, "kwargs", {}) or {}
        data = getattr(response, "data", None)
        object_id = kwargs.get("pk") or (data.get("id") if isinstance(data, dict) else "") or ""
        module = self._module(request)
        tail = request.path.rstrip("/").split("/")[-1]
        action = WRITE_METHODS[request.method]
        if tail in ACTION_WORDS:
            summary = f"{ACTION_WORDS[tail]} on {module}"
            if request.method == "POST" and kwargs.get("pk"):
                action = AuditLog.ACTION_UPDATE
        else:
            summary = f"{dict(AuditLog.ACTION_CHOICES)[action]} {module} record"
        if object_id:
            summary += f" #{object_id}"
        record(
            user=user,
            action=action,
            module=module,
            object_id=object_id,
            summary=summary,
            request=request,
            status_code=response.status_code,
            changed_fields=fields,
        )
