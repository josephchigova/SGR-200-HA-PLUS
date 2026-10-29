from rest_framework.routers import DefaultRouter

from .views import ReportTemplateViewSet

router = DefaultRouter()
router.register(r"report-templates", ReportTemplateViewSet, basename="report-template")

urlpatterns = router.urls
