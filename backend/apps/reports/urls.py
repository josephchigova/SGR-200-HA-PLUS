from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ReportAnalyticsView, ReportCatalogueView, ReportExportView, ReportPreviewView, ReportTemplateViewSet

router = DefaultRouter()
router.register(r"report-templates", ReportTemplateViewSet, basename="report-template")

urlpatterns = [
    path("reports/catalogue/", ReportCatalogueView.as_view(), name="report-catalogue"),
    path("reports/analytics/", ReportAnalyticsView.as_view(), name="report-analytics"),
    path("reports/<slug:code>/preview/", ReportPreviewView.as_view(), name="report-preview"),
    path("reports/<slug:code>/export/", ReportExportView.as_view(), name="report-export"),
] + router.urls
