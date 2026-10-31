import csv
import io

from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import CATEGORIES, FILTER_LABELS, LIMITATIONS, spec_by_code, specs_for
from .engine import ReportParams, analytics, csv_rows, export_filename, preview, render_pdf, visible_spec
from .formatting import csv_safe
from .models import ReportTemplate
from .serializers import ReportTemplateSerializer


class ReportTemplateViewSet(viewsets.ModelViewSet):
    queryset = ReportTemplate.objects.all()
    serializer_class = ReportTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]


def _params(request):
    try:
        return ReportParams(request.user, request.query_params)
    except ValueError as error:
        return str(error)


def _resolve(request, code):
    if spec_by_code(code) is None:
        return None, Response({"detail": "That report is not available."}, status=404)
    spec = visible_spec(request.user, code)
    if spec is None:
        return None, Response({"detail": "You do not have permission to open this report."}, status=403)
    params = _params(request)
    if isinstance(params, str):
        return None, Response({"detail": params}, status=400)
    return (spec, params), None


def _public(spec):
    return {
        "code": spec.code,
        "category": spec.category,
        "title": spec.title,
        "description": spec.description,
        "orientation": spec.orientation,
        "filters": list(spec.filters),
        "status_options": spec.status_options,
        "gap": spec.gap,
    }


class ReportCatalogueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        reports = [_public(spec) for spec in specs_for(request.user)]
        categories = []
        for code, label in CATEGORIES:
            items = [report for report in reports if report["category"] == code]
            if items:
                categories.append({"code": code, "label": label, "count": len(items)})
        return Response({
            "categories": categories,
            "reports": reports,
            "filters": FILTER_LABELS,
            "limitations": LIMITATIONS,
        })


class ReportAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        params = _params(request)
        if isinstance(params, str):
            return Response({"detail": params}, status=400)
        return Response(analytics(request.user, params))


class ReportPreviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, code):
        resolved, error = _resolve(request, code)
        if error:
            return error
        spec, params = resolved
        return Response(preview(spec, params))


class ReportExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, code):
        resolved, error = _resolve(request, code)
        if error:
            return error
        spec, params = resolved
        export_format = (request.query_params.get("file_format") or "").lower()
        if export_format == "pdf":
            document = render_pdf(spec, params)
            response = HttpResponse(document, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{export_filename(spec, params, "pdf")}"'
            response["Content-Length"] = str(len(document))
            return response
        if export_format == "csv":
            response = StreamingHttpResponse(_csv_stream(spec, params), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{export_filename(spec, params, "csv")}"'
            return response
        return Response({"detail": "Choose file_format=pdf or file_format=csv."}, status=400)


def _csv_stream(spec, params):
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow([column.label for column in spec.columns])
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in csv_rows(spec, params):
        writer.writerow([csv_safe(row.get(column.key), column.kind) for column in spec.columns])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
