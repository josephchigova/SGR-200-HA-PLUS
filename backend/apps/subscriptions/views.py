from decimal import Decimal

from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.permissions import SubscriptionWorkflowPermission
from apps.farmers.models import Farm, Farmer
from apps.production.seasonal_services import SeasonalSubscriptionService

from .models import FarmerSubscription, Subscription
from .serializers import FarmerSubscriptionSerializer, FarmerSubscriptionStatusSerializer, SubscriptionSerializer
from .services import SubscriptionPaymentService


class FarmerSubscriptionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class SubscriptionViewSet(viewsets.ModelViewSet):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, SubscriptionWorkflowPermission]


class FarmerSubscriptionViewSet(viewsets.ModelViewSet):
    queryset = FarmerSubscription.objects.select_related("farmer").all()
    serializer_class = FarmerSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, SubscriptionWorkflowPermission]
    pagination_class = FarmerSubscriptionPagination

    @staticmethod
    def scope_farmers_to_user(farmers, user):
        if user.is_superuser:
            return farmers
        if user.role == user.ROLE_DISTRICT_COORDINATOR:
            return farmers.filter(district_id=user.district_id)
        if user.role == user.ROLE_PROVINCIAL_COORDINATOR:
            return farmers.filter(province_id=user.province_id)
        if user.role == user.ROLE_LEAD_FARMER:
            return farmers.filter(cluster_id=user.assigned_cluster_id)
        return farmers

    @staticmethod
    def with_season_payment_status(farmers, season):
        money_field = DecimalField(max_digits=14, decimal_places=2)
        farm_totals = Farm.objects.filter(farmer_id=OuterRef("pk")).values("farmer_id").annotate(
            total=Sum("arable_hectares")
        ).values("total")[:1]
        season_payments = FarmerSubscription.objects.filter(
            farmer_id=OuterRef("pk"),
            season__iexact=season,
        ).order_by("pk").values("paid_amount")[:1]

        return farmers.annotate(
            summary_arable_hectares=Coalesce(
                Subquery(farm_totals, output_field=money_field),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
            summary_paid_amount=Coalesce(
                Subquery(season_payments, output_field=money_field),
                Value(Decimal("0.00")),
                output_field=money_field,
            ),
        ).annotate(
            summary_expected_amount=Case(
                When(
                    summary_arable_hectares__gte=SeasonalSubscriptionService.LARGE_FARM_THRESHOLD,
                    then=Value(SeasonalSubscriptionService.LARGE_FARM_SUBSCRIPTION_AMOUNT),
                ),
                default=Value(SeasonalSubscriptionService.STANDARD_SUBSCRIPTION_AMOUNT),
                output_field=money_field,
            ),
        ).annotate(
            summary_payment_status=Case(
                When(summary_paid_amount__gte=F("summary_expected_amount"), then=Value("PAID")),
                When(summary_paid_amount__gt=0, then=Value("PARTIAL")),
                default=Value("UNPAID"),
                output_field=CharField(),
            )
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        # A farmer subscription belongs to the agricultural year named in season.
        # Summer and Winter share that payment, so crop_season is not applied.
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        if season_name:
            return queryset.filter(season__iexact=season_name)
        if season:
            return queryset.filter(season__iexact=season)
        return queryset

    def list(self, request, *args, **kwargs):
        season = request.query_params.get("season_name") or request.query_params.get("season")
        if not season:
            return super().list(request, *args, **kwargs)

        farmers = Farmer.objects.annotate(
            arable_hectares=Coalesce(
                Sum("farms__arable_hectares"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        farmers = self.scope_farmers_to_user(farmers, request.user)

        farmer_id = request.query_params.get("farmer") or request.query_params.get("farmer_id")
        if farmer_id:
            if not farmer_id.isdecimal():
                return Response({"farmer": ["A valid farmer ID is required."]}, status=status.HTTP_400_BAD_REQUEST)
            farmers = farmers.filter(pk=int(farmer_id))

        search = request.query_params.get("search", "").strip()
        if search:
            search_filter = Q()
            for field in ("full_name", "first_name", "surname", "national_id", "membership_number", "phone_primary", "phone_secondary"):
                search_filter |= Q(**{f"{field}__icontains": search})
            if search.isdecimal():
                search_filter |= Q(pk=int(search))
            farmers = farmers.filter(search_filter)

        farmers = farmers.order_by("surname", "first_name", "id")
        page = self.paginate_queryset(farmers)
        page_farmers = list(page if page is not None else farmers)
        farmer_ids = [farmer.pk for farmer in page_farmers]
        subscriptions = {
            subscription.farmer_id: subscription
            for subscription in FarmerSubscription.objects.filter(
                farmer_id__in=farmer_ids,
                season__iexact=season,
            )
        }

        rows = []
        for farmer in page_farmers:
            subscription = subscriptions.get(farmer.pk)
            hectares, category, expected_amount = SubscriptionPaymentService.subscription_details(farmer.arable_hectares)
            paid_amount = subscription.paid_amount if subscription else Decimal("0.00")
            summary = SubscriptionPaymentService.calculate_display_summary(expected_amount, paid_amount)
            rows.append({
                "id": subscription.pk if subscription else None,
                "farmer": farmer.pk,
                "farmer_name": farmer.full_name,
                "membership_number": farmer.membership_number or "",
                "national_id": farmer.national_id or "",
                "phone_primary": farmer.phone_primary or "",
                "farmer_arable_hectares": hectares,
                "category": category,
                "expected_amount": expected_amount,
                "paid_amount": paid_amount,
                "outstanding_amount": summary["outstanding_amount"],
                "payment_status": summary["payment_status"],
                "payment_date": subscription.payment_date if subscription else None,
                "season": season,
            })

        serializer = FarmerSubscriptionStatusSerializer(rows, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        season = request.query_params.get("season_name") or request.query_params.get("season")
        if not season:
            return Response({"season": ["A season is required."]}, status=status.HTTP_400_BAD_REQUEST)

        farmers = self.scope_farmers_to_user(Farmer.objects.all(), request.user)
        summary = self.with_season_payment_status(farmers, season).aggregate(
            total_farmers=Count("pk"),
            paid=Count("pk", filter=Q(summary_payment_status="PAID")),
            partial=Count("pk", filter=Q(summary_payment_status="PARTIAL")),
            unpaid=Count("pk", filter=Q(summary_payment_status="UNPAID")),
        )
        return Response(summary)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        response_status = status.HTTP_201_CREATED if serializer.context.get("created") else status.HTTP_200_OK
        return Response(serializer.data, status=response_status, headers=headers)
