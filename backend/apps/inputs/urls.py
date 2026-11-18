from rest_framework.routers import DefaultRouter

from .supply_views import InputSupplyRequestViewSet, ProgrammeVarietyCapViewSet
from .views import InputAllocationViewSet, InputIssueViewSet, InputViewSet

router = DefaultRouter()
router.register(r"input-issues", InputIssueViewSet, basename="input-issue")
router.register(r"inputs", InputViewSet, basename="input")
router.register(r"input-allocations", InputAllocationViewSet, basename="input-allocation")
router.register(r"programme-variety-caps", ProgrammeVarietyCapViewSet, basename="programme-variety-cap")
router.register(r"input-supply-requests", InputSupplyRequestViewSet, basename="input-supply-request")

urlpatterns = router.urls
