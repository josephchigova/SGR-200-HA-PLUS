from rest_framework.routers import DefaultRouter

from .leads import LeadFarmerViewSet
from .views import ClusterViewSet

router = DefaultRouter()
router.register(r"clusters", ClusterViewSet, basename="cluster")
router.register(r"lead-farmers", LeadFarmerViewSet, basename="lead-farmer")

urlpatterns = router.urls
