"""API for lead farmer input requests."""

from decimal import Decimal

from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.privacy import hides_money
from apps.accounts.roles import can
from apps.clusters.models import Cluster
from apps.farmers.models import Farm, Farmer
from apps.programmes.models import Crop, Programme, Season

from . import lead_requests as service
from .models import LeadRequest, LeadRequestLine

ACTIONS = {"GET": "view", "HEAD": "view", "OPTIONS": "view", "POST": "create", "PUT": "edit", "PATCH": "edit", "DELETE": "delete"}


class LeadRequestPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # Approve and reject are POSTs, but they are an approval decision, not a new request.
        action = getattr(view, "action", None)
        if action in {"approve", "reject"}:
            return can(user, "lead_requests", "approve")
        if action == "submit":
            return can(user, "lead_requests", "create")
        return can(user, "lead_requests", ACTIONS.get(request.method, "view"))


def _person(user):
    return (user.get_full_name() or user.username) if user else ""


def _lead_name(cluster):
    if cluster.lead_member_id:
        return cluster.lead_member.full_name
    if cluster.lead_farmer_id:
        return _person(cluster.lead_farmer)
    return cluster.name


def _number(value, places="0.01"):
    return format(Decimal(value).quantize(Decimal(places)).normalize(), "f") if value is not None else None


def _totals_payload(result, show_money):
    return {
        "farmers": result["farmers"],
        "rows": [
            {
                **{key: row[key] for key in ("crop", "input_category", "input_category_label", "product_name", "unit", "farmers")},
                "rate_per_hectare": _number(row["rate_per_hectare"], "0.0001"),
                "hectares": _number(row["hectares"]), "quantity": _number(row["quantity"], "0.0001"),
                "cost": _number(row["cost"]) if show_money else None,
            }
            for row in result["rows"]
        ],
    }


class LeadRequestLineSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    membership_number = serializers.CharField(source="farmer.membership_number", read_only=True)
    crop_name = serializers.CharField(source="crop.name", read_only=True)
    farm_name = serializers.CharField(source="farm.farm_name", read_only=True, default="")
    request_number = serializers.CharField(source="batch.request_number", read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = LeadRequestLine
        fields = ["id", "farmer", "farmer_name", "membership_number", "farm", "farm_name", "crop", "crop_name", "hectares", "batch", "request_number", "items", "allocation"]

    def get_items(self, obj):
        show_money = not hides_money(self.context["request"].user)
        return [
            {
                "request_line": item["request_line"], "input_category": item["input_category"], "input_category_label": item["input_category_label"],
                "product_name": item["product_name"], "unit": item["unit"], "rate_per_hectare": _number(item["rate_per_hectare"], "0.0001"),
                "quantity": _number(item["quantity"], "0.0001"), "cost": _number(item["cost"]) if show_money else None,
            }
            for item in service.line_items(obj)
        ]


class LeadRequestSerializer(serializers.ModelSerializer):
    cluster_name = serializers.CharField(source="cluster.name", read_only=True)
    lead_farmer_name = serializers.SerializerMethodField()
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)
    crop_season_label = serializers.CharField(source="get_crop_season_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    submitted_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()
    total_hectares = serializers.SerializerMethodField()
    farmers = serializers.SerializerMethodField()

    class Meta:
        model = LeadRequest
        fields = [
            "id", "cluster", "cluster_name", "lead_farmer_name", "programme", "programme_name", "season", "season_name",
            "crop_season", "crop_season_label", "status", "status_label", "notes", "decision_notes",
            "submitted_at", "submitted_by_name", "decided_at", "decided_by_name", "created_at", "total_hectares", "farmers",
        ]
        read_only_fields = ["status", "decision_notes", "submitted_at", "decided_at", "created_at"]

    def get_lead_farmer_name(self, obj):
        return _lead_name(obj.cluster)

    def get_submitted_by_name(self, obj):
        return _person(obj.submitted_by)

    def get_decided_by_name(self, obj):
        return _person(obj.decided_by)

    def get_total_hectares(self, obj):
        return _number(sum((line.hectares for line in obj.lines.all()), Decimal("0")))

    def get_farmers(self, obj):
        return len({line.farmer_id for line in obj.lines.all()})


class LeadRequestDetailSerializer(LeadRequestSerializer):
    lines = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()

    class Meta(LeadRequestSerializer.Meta):
        fields = [*LeadRequestSerializer.Meta.fields, "lines", "totals"]

    def _lines(self, obj):
        return obj.lines.select_related("farmer", "farm", "crop", "batch").prefetch_related("products__requirement__input_product")

    def get_lines(self, obj):
        return LeadRequestLineSerializer(self._lines(obj), many=True, context=self.context).data

    def get_totals(self, obj):
        return _totals_payload(service.totals(self._lines(obj)), not hides_money(self.context["request"].user))


def _by_id(model, value):
    return model.objects.filter(pk=value).first() if str(value or "").isdigit() else None


class LeadRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [LeadRequestPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = LeadRequest.objects.select_related("cluster__lead_member", "cluster__lead_farmer", "programme", "season", "submitted_by", "decided_by").prefetch_related("lines")
        if user.role == user.ROLE_LEAD_FARMER:
            queryset = queryset.filter(cluster_id=user.assigned_cluster_id) if user.assigned_cluster_id else queryset.none()
        params = self.request.query_params
        for name, field in (("season", "season_id"), ("programme", "programme_id"), ("cluster", "cluster_id")):
            if str(params.get(name) or "").isdigit():
                queryset = queryset.filter(**{field: params[name]})
        for name in ("crop_season", "status"):
            if params.get(name):
                queryset = queryset.filter(**{name: params[name].upper()})
        return queryset

    def get_serializer_class(self):
        return LeadRequestDetailSerializer if self.action in {"retrieve", "submit", "approve", "reject"} else LeadRequestSerializer

    def _cluster(self, value):
        user = self.request.user
        if user.role == user.ROLE_LEAD_FARMER:
            if not user.assigned_cluster_id:
                raise ValidationError({"detail": ["Your account is not linked to a cluster yet."]})
            return user.assigned_cluster
        return _by_id(Cluster, value)

    def create(self, request, *args, **kwargs):
        programme = _by_id(Programme, request.data.get("programme"))
        if programme is None:
            raise ValidationError({"programme": ["Choose the programme."]})
        try:
            created = service.open_request(
                cluster=self._cluster(request.data.get("cluster")), programme=programme,
                season=_by_id(Season, request.data.get("season")), crop_season=str(request.data.get("crop_season") or "").upper(), user=request.user,
            )
        except service.LeadRequestError as error:
            raise ValidationError({"detail": [str(error)]}) from error
        if request.data.get("notes"):
            created.notes = request.data["notes"]
            created.save(update_fields=["notes"])
        return Response(LeadRequestDetailSerializer(created, context=self.get_serializer_context()).data, status=201)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status not in service.EDITABLE:
            raise ValidationError({"detail": ["Only a draft or rejected request can be changed."]})
        instance.notes = request.data.get("notes", instance.notes)
        instance.save(update_fields=["notes", "updated_at"])
        return Response(LeadRequestDetailSerializer(instance, context=self.get_serializer_context()).data)

    def perform_destroy(self, instance):
        if instance.status not in service.EDITABLE:
            raise ValidationError({"detail": ["Only a draft or rejected request can be deleted."]})
        instance.delete()

    def _run(self, change, permission):
        if not can(self.request.user, "lead_requests", permission):
            raise PermissionDenied("You do not have permission to do this.")
        instance = self.get_object()
        try:
            instance = change(instance)
        except service.LeadRequestError as error:
            raise ValidationError({"detail": [str(error)]}) from error
        return Response(LeadRequestDetailSerializer(instance, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._run(lambda item: service.submit(item, user=request.user), "create")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._run(lambda item: service.approve(item, user=request.user, notes=request.data.get("notes", "")), "approve")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._run(lambda item: service.reject(item, user=request.user, notes=request.data.get("notes", "")), "approve")

    @action(detail=True, methods=["get"])
    def choices(self, request, pk=None):
        """Farmers of the cluster, the programme's crops for the season and the products each crop's programme request offers."""
        instance = self.get_object()
        show_money = not hides_money(request.user)
        crops = []
        for crop in service.season_crops(instance):
            batch = service.programme_request_for(programme=instance.programme, crop=crop, season=instance.season)
            products = []
            if batch is not None:
                for line in batch.lines.select_related("requirement__input_product"):
                    if not line.approved_hectares or not line.requirement.active:
                        continue
                    requirement = line.requirement
                    products.append({
                        "id": line.pk, "input_category": requirement.input_category, "name": service._name(requirement), "unit": requirement.unit,
                        "rate_per_hectare": _number(requirement.rate_per_hectare, "0.0001"),
                        "unit_price": _number(requirement.cost_per_unit, "0.0001") if show_money else None,
                    })
            crops.append({"id": crop.pk, "name": crop.name, "request_number": batch.request_number if batch else None, "products": products})
        farmers = [
            {"id": farmer.pk, "name": farmer.full_name, "membership_number": farmer.membership_number}
            for farmer in service.farmer_options(instance)
        ]
        return Response({"crops": crops, "farmers": farmers})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Consolidated totals across every lead farmer request that matches the filters, and per lead farmer."""
        show_money = not hides_money(request.user)
        requests = list(self.get_queryset().exclude(status=LeadRequest.STATUS_REJECTED))
        lines = list(
            LeadRequestLine.objects.filter(request__in=requests)
            .select_related("farmer", "crop", "request__cluster__lead_member", "request__cluster__lead_farmer")
            .prefetch_related("products__requirement__input_product")
        )
        by_lead = {}
        for line in lines:
            by_lead.setdefault(line.request_id, []).append(line)
        leads = []
        for item in requests:
            leads.append({
                "request": item.pk, "lead_farmer_name": _lead_name(item.cluster), "cluster_name": item.cluster.name,
                "programme_name": item.programme.name, "season_name": item.season.name, "crop_season_label": item.get_crop_season_display(),
                "status": item.status, "status_label": item.get_status_display(),
                "totals": _totals_payload(service.totals(by_lead.get(item.pk, [])), show_money),
            })
        return Response({"totals": _totals_payload(service.totals(lines), show_money), "requests": leads})


class LeadRequestLineViewSet(viewsets.ModelViewSet):
    """Farmers, crops and products inside a lead farmer's request."""

    permission_classes = [LeadRequestPermission]
    serializer_class = LeadRequestLineSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = LeadRequestLine.objects.select_related("request", "farmer", "farm", "crop", "batch").prefetch_related("products__requirement__input_product")
        if user.role == user.ROLE_LEAD_FARMER:
            queryset = queryset.filter(request__cluster_id=user.assigned_cluster_id) if user.assigned_cluster_id else queryset.none()
        if str(self.request.query_params.get("request") or "").isdigit():
            queryset = queryset.filter(request_id=self.request.query_params["request"])
        return queryset

    def _request(self, value):
        user = self.request.user
        request = _by_id(LeadRequest, value)
        if request is None or (user.role == user.ROLE_LEAD_FARMER and request.cluster_id != user.assigned_cluster_id):
            raise ValidationError({"request": ["Choose one of your requests."]})
        return request

    def _save(self, data, line=None):
        request = line.request if line else self._request(data.get("request"))
        products = data.get("products")
        if products is None and line is not None:
            products = list(line.products.values_list("pk", flat=True))
        try:
            saved = service.save_line(
                request=request,
                farmer=_by_id(Farmer, data.get("farmer")) if "farmer" in data or line is None else line.farmer,
                crop=_by_id(Crop, data.get("crop")) if "crop" in data or line is None else line.crop,
                hectares=data.get("hectares", line.hectares if line else None),
                farm=_by_id(Farm, data.get("farm")) if "farm" in data else (line.farm if line else None),
                products=[int(value) for value in products or [] if str(value).isdigit()],
                line=line,
            )
        except service.LeadRequestError as error:
            raise ValidationError({"detail": [str(error)]}) from error
        return saved

    def create(self, request, *args, **kwargs):
        return Response(self.get_serializer(self._save(request.data)).data, status=201)

    def update(self, request, *args, **kwargs):
        return Response(self.get_serializer(self._save(request.data, line=self.get_object())).data)

    def perform_destroy(self, instance):
        try:
            service.delete_line(instance)
        except service.LeadRequestError as error:
            raise ValidationError({"detail": [str(error)]}) from error
