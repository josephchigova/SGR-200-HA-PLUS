from django.conf import settings
from django.http import HttpResponse, JsonResponse


def health(request):
    return JsonResponse({"status": "ok"})


def spa_index(request, path=""):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        return HttpResponse(
            "Frontend build not found. From the project root, run deploy/prepare.sh.",
            status=503,
            content_type="text/plain",
        )
    return HttpResponse(index.read_bytes(), content_type="text/html")
