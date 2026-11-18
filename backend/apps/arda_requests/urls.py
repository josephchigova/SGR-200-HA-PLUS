from rest_framework.routers import DefaultRouter

from .lead_views import LeadRequestLineViewSet, LeadRequestViewSet
from .views import ARDAFarmerRequestViewSet, ARDARequestBatchViewSet, ARDARequestViewSet

router = DefaultRouter()
router.register(r"arda-requests", ARDARequestViewSet, basename="arda-request")
router.register(r"arda-request-batches", ARDARequestBatchViewSet, basename="arda-request-batch")
router.register(r"arda-farmer-requests", ARDAFarmerRequestViewSet, basename="arda-farmer-request")
router.register(r"lead-requests", LeadRequestViewSet, basename="lead-request")
router.register(r"lead-request-lines", LeadRequestLineViewSet, basename="lead-request-line")

urlpatterns = router.urls
