from rest_framework.routers import DefaultRouter

from .views import ARDAFarmerRequestViewSet, ARDARequestBatchViewSet, ARDARequestViewSet

router = DefaultRouter()
router.register(r"arda-requests", ARDARequestViewSet, basename="arda-request")
router.register(r"arda-request-batches", ARDARequestBatchViewSet, basename="arda-request-batch")
router.register(r"arda-farmer-requests", ARDAFarmerRequestViewSet, basename="arda-farmer-request")

urlpatterns = router.urls
