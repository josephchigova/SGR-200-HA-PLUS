from rest_framework.routers import DefaultRouter

from .views import FarmerSubscriptionViewSet, SubscriptionViewSet

router = DefaultRouter()
router.register(r"subscriptions", SubscriptionViewSet, basename="subscription")
router.register(r"farmer-subscriptions", FarmerSubscriptionViewSet, basename="farmer-subscription")

urlpatterns = router.urls
