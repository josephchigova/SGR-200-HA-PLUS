from rest_framework.routers import DefaultRouter

from .views import ProgrammeAllocationViewSet, ProgrammeViewSet, SeasonViewSet

router = DefaultRouter()
router.register(r"programmes", ProgrammeViewSet, basename="programme")
router.register(r"seasons", SeasonViewSet, basename="season")
router.register(r"programme-allocations", ProgrammeAllocationViewSet, basename="programme-allocations")

urlpatterns = router.urls
