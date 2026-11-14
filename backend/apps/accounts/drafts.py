"""Server copies of unfinished forms.

GET    /api/drafts/?key=<key>   the user's draft for one form (404 when there is none)
GET    /api/drafts/             the user's drafts, newest first (keys and times only)
PUT    /api/drafts/             {"key": ..., "data": {...}} saves or replaces a draft
DELETE /api/drafts/?key=<key>   discards a draft

Users only ever see their own drafts. Anything that looks like a password is dropped.
"""

import json
import re

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FormDraft

MAX_DRAFT_BYTES = 200_000
MAX_DRAFTS_PER_USER = 200
KEY_PATTERN = re.compile(r"^[A-Za-z0-9:_\-./]{1,160}$")
SECRET_WORDS = ("password", "secret", "token")


def strip_secrets(value):
    if isinstance(value, dict):
        return {
            key: strip_secrets(item)
            for key, item in value.items()
            if not any(word in str(key).lower() for word in SECRET_WORDS)
        }
    if isinstance(value, list):
        return [strip_secrets(item) for item in value]
    return value


def _key(source):
    key = str(source.get("key") or "").strip()
    if not KEY_PATTERN.match(key):
        return None
    return key


def _payload(draft):
    return {"key": draft.key, "data": draft.data, "updated_at": draft.updated_at.isoformat()}


class FormDraftView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        drafts = FormDraft.objects.filter(user=request.user)
        if "key" not in request.query_params:
            return Response([{"key": draft.key, "updated_at": draft.updated_at.isoformat()} for draft in drafts[:MAX_DRAFTS_PER_USER]])
        key = _key(request.query_params)
        if key is None:
            return Response({"detail": "Give a valid draft key."}, status=status.HTTP_400_BAD_REQUEST)
        draft = drafts.filter(key=key).first()
        if draft is None:
            return Response({"detail": "No draft."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_payload(draft))

    def put(self, request):
        key = _key(request.data)
        if key is None:
            return Response({"detail": "Give a valid draft key."}, status=status.HTTP_400_BAD_REQUEST)
        data = request.data.get("data")
        if not isinstance(data, dict):
            return Response({"detail": "Draft data must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        data = strip_secrets(data)
        if len(json.dumps(data, default=str)) > MAX_DRAFT_BYTES:
            return Response({"detail": "This draft is too large to save."}, status=status.HTTP_400_BAD_REQUEST)
        draft, _ = FormDraft.objects.update_or_create(user=request.user, key=key, defaults={"data": data})
        stale = FormDraft.objects.filter(user=request.user).order_by("-updated_at").values_list("id", flat=True)[MAX_DRAFTS_PER_USER:]
        if stale:
            FormDraft.objects.filter(id__in=list(stale)).delete()
        return Response(_payload(draft))

    post = put

    def delete(self, request):
        key = _key(request.query_params)
        if key is None:
            return Response({"detail": "Give a valid draft key."}, status=status.HTTP_400_BAD_REQUEST)
        FormDraft.objects.filter(user=request.user, key=key).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
