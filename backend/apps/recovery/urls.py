from rest_framework.routers import DefaultRouter

from .views import InputDebtViewSet, RecoveryRecordViewSet

router = DefaultRouter()
router.register(r"recovery-records", RecoveryRecordViewSet, basename="recovery-record")
router.register(r"input-debts", InputDebtViewSet, basename="input-debt")

urlpatterns = router.urls
