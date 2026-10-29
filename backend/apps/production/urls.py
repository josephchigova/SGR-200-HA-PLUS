from rest_framework.routers import DefaultRouter

from .views import CropInputRequirementViewSet, CropSellingPriceViewSet, CropViewSet, FarmerProductionViewSet, GMBDeliveryViewSet, ProductionPlanViewSet, SeasonalPlantingPlanViewSet

router = DefaultRouter()
router.register(r"production-plans", ProductionPlanViewSet, basename="production-plan")
router.register(r"farmer-productions", FarmerProductionViewSet, basename="farmer-production")
router.register(r"deliveries", GMBDeliveryViewSet, basename="delivery")
router.register(r"crops", CropViewSet, basename="crop")
router.register(r"crop-input-requirements", CropInputRequirementViewSet, basename="crop-input-requirement")
router.register(r"crop-selling-prices", CropSellingPriceViewSet, basename="crop-selling-price")
router.register(r"seasonal-planting-plans", SeasonalPlantingPlanViewSet, basename="seasonal-planting-plan")

urlpatterns = router.urls
