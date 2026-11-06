from rest_framework import serializers

from apps.farmers.models import Farmer

from .models import Cluster


class ClusterSerializer(serializers.ModelSerializer):
    province_name = serializers.CharField(source="province.name", read_only=True)
    district_name = serializers.SerializerMethodField()
    lead_farmer_name = serializers.SerializerMethodField()
    lead_member_national_id = serializers.SerializerMethodField()
    lead_member_phone = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Cluster
        fields = [
            "id",
            "name",
            "province",
            "province_name",
            "district",
            "district_name",
            "lead_member",
            "lead_farmer_name",
            "lead_member_national_id",
            "lead_member_phone",
            "lead_farmer",
            "member_count",
            "contact_person",
            "phone",
            "active",
        ]
        read_only_fields = ["lead_farmer"]

    def get_member_count(self, obj):
        annotated = getattr(obj, "member_count", None)
        if isinstance(annotated, int):
            return annotated
        return obj.farmers.count()

    def get_district_name(self, obj):
        return obj.district.name if obj.district_id else ""

    def get_lead_farmer_name(self, obj):
        if obj.lead_member_id:
            return obj.lead_member.full_name
        if obj.lead_farmer_id:
            return obj.lead_farmer.get_full_name() or obj.lead_farmer.email
        return ""

    def get_lead_member_national_id(self, obj):
        return obj.lead_member.national_id if obj.lead_member_id else ""

    def get_lead_member_phone(self, obj):
        return obj.lead_member.phone_primary if obj.lead_member_id else ""

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

        lead = attrs.get("lead_member", getattr(self.instance, "lead_member", None))
        if lead is not None:
            if not isinstance(lead, Farmer):
                lead = Farmer.objects.filter(pk=lead).select_related("province", "district").first()
            if lead is None:
                raise serializers.ValidationError({"lead_member": ["Select a farmer from the register."]})
            province_ids = {lead.province_id} if lead.province_id else set()
            province_ids.update(lead.farms.exclude(province_id=None).values_list("province_id", flat=True))
            if province and province.pk not in province_ids:
                raise serializers.ValidationError({
                    "lead_member": ["The lead farmer must already be registered in the cluster province."],
                })
            if district is not None:
                district_ids = {lead.district_id} if lead.district_id else set()
                district_ids.update(lead.farms.exclude(district_id=None).values_list("district_id", flat=True))
                if district.pk not in district_ids:
                    raise serializers.ValidationError({
                        "lead_member": ["The lead farmer must already be registered in the cluster district."],
                    })
            active = attrs.get("active", getattr(self.instance, "active", True))
            if active:
                clash = Cluster.objects.filter(lead_member=lead, active=True)
                if self.instance is not None:
                    clash = clash.exclude(pk=self.instance.pk)
                if clash.exists():
                    raise serializers.ValidationError({
                        "lead_member": ["This farmer already leads another active cluster."],
                    })
        return attrs
