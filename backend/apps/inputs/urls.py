from rest_framework.routers import DefaultRouter

from .views import InputAllocationViewSet, InputIssueViewSet, InputViewSet

router = DefaultRouter()
router.register(r"input-issues", InputIssueViewSet, basename="input-issue")
router.register(r"inputs", InputViewSet, basename="input")
router.register(r"input-allocations", InputAllocationViewSet, basename="input-allocation")

urlpatterns = router.urls
