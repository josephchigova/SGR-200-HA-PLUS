from rest_framework import serializers

from .models import Cluster


class ClusterSerializer(serializers.ModelSerializer):
    province_name = serializers.CharField(source="province.name", read_only=True)
    district_name = serializers.CharField(source="district.name", read_only=True)
    lead_farmer_name = serializers.CharField(source="lead_farmer.get_full_name", read_only=True)

    class Meta:
        model = Cluster
        fields = [
            "id",
            "name",
            "province",
            "province_name",
            "district",
            "district_name",
            "lead_farmer",
            "lead_farmer_name",
            "contact_person",
            "phone",
            "active",
        ]
