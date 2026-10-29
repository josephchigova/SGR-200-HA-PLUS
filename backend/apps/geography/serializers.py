from rest_framework import serializers

from .models import District, Province, Ward


class ProvinceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Province
        fields = ["id", "name", "code", "official", "active"]
        read_only_fields = ["official"]


class DistrictSerializer(serializers.ModelSerializer):
    province_name = serializers.CharField(source="province.name", read_only=True)

    class Meta:
        model = District
        fields = ["id", "province", "province_name", "name", "code", "active"]


class WardSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source="district.name", read_only=True)

    class Meta:
        model = Ward
        fields = ["id", "district", "district_name", "name", "code", "active"]
