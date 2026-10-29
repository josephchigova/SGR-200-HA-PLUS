from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import FarmerDocumentViewSet, FarmerViewSet, FarmViewSet

router = DefaultRouter()
router.register(r"farmers", FarmerViewSet, basename="farmer")
router.register(r"farms", FarmViewSet, basename="farm")
router.register(r"farmer-documents", FarmerDocumentViewSet, basename="farmer-document")

urlpatterns = [
    path("farmers/dashboard-summary/", FarmerViewSet.as_view({"get": "dashboard_summary"}), name="dashboard-summary"),
    *router.urls,
]
