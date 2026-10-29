from rest_framework.routers import DefaultRouter

from .views import ClusterViewSet

router = DefaultRouter()
router.register(r"clusters", ClusterViewSet, basename="cluster")

urlpatterns = router.urls
