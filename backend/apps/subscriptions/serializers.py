from decimal import Decimal

from rest_framework import serializers

from .models import FarmerSubscription, Subscription
from .services import SubscriptionPaymentService


class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = [
            "id",
            "name",
            "code",
            "description",
            "fee",
            "is_active",
            "created_at",
            "updated_at",
        ]


class FarmerSubscriptionSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    season = serializers.CharField(max_length=80, trim_whitespace=True, required=True)
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    payment_date = serializers.DateField(required=False, allow_null=True)

    class Meta:
        model = FarmerSubscription
        fields = [
            "id",
            "farmer",
            "farmer_name",
            "category",
            "expected_amount",
            "paid_amount",
            "outstanding_amount",
            "payment_status",
            "season",
            "payment_date",
        ]
        read_only_fields = ["farmer_name", "category", "expected_amount", "outstanding_amount", "payment_status"]
        validators = []

    def _payment_summary(self, expected_amount, paid_amount):
        try:
            return SubscriptionPaymentService.calculate_summary(expected_amount, paid_amount)
        except ValueError as error:
            raise serializers.ValidationError({"paid_amount": [str(error)]}) from error

    def validate(self, attrs):
        farmer = attrs.get("farmer", getattr(self.instance, "farmer", None))
        paid_amount = attrs.get("paid_amount", getattr(self.instance, "paid_amount", Decimal("0.00")))
        payment_date = attrs.get("payment_date", getattr(self.instance, "payment_date", None))
        if paid_amount > 0 and payment_date is None:
            raise serializers.ValidationError({"payment_date": ["A payment date is required when an amount has been paid."]})

        _, _, expected_amount = SubscriptionPaymentService.farmer_subscription_details(farmer)
        self._payment_summary(expected_amount, paid_amount)
        return attrs

    def create(self, validated_data):
        farmer = validated_data["farmer"]
        season = validated_data["season"]
        paid_amount = validated_data["paid_amount"]
        payment_date = validated_data.get("payment_date")
        _, category, expected_amount = SubscriptionPaymentService.farmer_subscription_details(farmer)
        summary = self._payment_summary(expected_amount, paid_amount)
        subscription, created = FarmerSubscription.objects.update_or_create(
            farmer=farmer,
            season=season,
            defaults={
                "category": category,
                "expected_amount": expected_amount,
                "paid_amount": paid_amount,
                "payment_date": payment_date,
                **summary,
            },
        )
        self.context["created"] = created
        return subscription

    def update(self, instance, validated_data):
        paid_amount = validated_data.get("paid_amount", instance.paid_amount)
        farmer = validated_data.get("farmer", instance.farmer)
        _, category, expected_amount = SubscriptionPaymentService.farmer_subscription_details(farmer)
        summary = self._payment_summary(expected_amount, paid_amount)
        for field, value in {**validated_data, "category": category, "expected_amount": expected_amount, **summary}.items():
            setattr(instance, field, value)
        instance.save()
        return instance


class FarmerSubscriptionStatusSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    farmer = serializers.IntegerField()
    farmer_name = serializers.CharField()
    membership_number = serializers.CharField(allow_blank=True)
    national_id = serializers.CharField(allow_blank=True)
    phone_primary = serializers.CharField(allow_blank=True)
    farmer_arable_hectares = serializers.DecimalField(max_digits=14, decimal_places=2)
    category = serializers.CharField()
    expected_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    outstanding_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_status = serializers.CharField()
    payment_date = serializers.DateField(allow_null=True)
    season = serializers.CharField()
