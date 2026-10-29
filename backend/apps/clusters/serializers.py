from rest_framework import serializers

from .models import Cluster


class ClusterSerializer(serializers.ModelSerializer):
    province_name = serializers.CharField(source="province.name", read_only=True)
    district_name = serializers.CharField(source="district.name", read_only=True)
    lead_farmer_name = serializers.CharField(source="lead_farmer.get_full_name", read_only=True)

    def validate(self, attrs):
        province = attrs.get("province", getattr(self.instance, "province", None))
        district = attrs.get("district", getattr(self.instance, "district", None))
        if province and district and district.province_id != province.pk:
            raise serializers.ValidationError({"district": ["District does not belong to the selected province."]})
        name = attrs.get("name", getattr(self.instance, "name", ""))
        cleaned = " ".join(str(name or "").split())
        if not cleaned:
            raise serializers.ValidationError({"name": ["Enter the cluster name."]})
        attrs["name"] = cleaned
        return attrs

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
