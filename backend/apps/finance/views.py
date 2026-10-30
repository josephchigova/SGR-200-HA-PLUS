from datetime import date

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import AssetCategoryPermission, FinanceAccessPermission

from .assets import (
    add_document,
    asset_summary,
    dispose_asset,
    record_maintenance,
    record_valuation,
    reject,
    transfer_asset,
)
from .models import Asset, AssetCategory, AssetDisposal, DepreciationEntry, Expense, PayrollEntry, Receipt
from .serializers import (
    AssetAuditSerializer,
    AssetCategorySerializer,
    AssetDisposalSerializer,
    AssetDocumentSerializer,
    AssetMaintenanceSerializer,
    AssetSerializer,
    AssetTransferSerializer,
    AssetValuationSerializer,
    DepreciationEntrySerializer,
    ExpenseSerializer,
    PayrollEntrySerializer,
    ReceiptSerializer,
)

ORDERING = {
    "asset_id", "-asset_id", "name", "-name", "cost", "-cost",
    "purchase_date", "-purchase_date", "status", "-status",
}


def parse_day(value, label):
    if not value:
        reject(f"Enter {label}.")
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        reject(f"{label} must be a valid date.")


class ReceiptViewSet(viewsets.ModelViewSet):
    queryset = Receipt.objects.all()
    serializer_class = ReceiptSerializer
    permission_classes = [FinanceAccessPermission]


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [FinanceAccessPermission]


class AssetCategoryViewSet(viewsets.ModelViewSet):
    queryset = AssetCategory.objects.all()
    serializer_class = AssetCategorySerializer
    permission_classes = [AssetCategoryPermission]
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if category.assets.exists():
            return Response(
                {"detail": "This category is used by registered assets and cannot be removed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class AssetViewSet(viewsets.ModelViewSet):
    serializer_class = AssetSerializer
    permission_classes = [FinanceAccessPermission]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        queryset = Asset.objects.select_related("category_ref")
        params = self.request.query_params
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(asset_id__icontains=search)
                | Q(description__icontains=search)
                | Q(supplier__icontains=search)
                | Q(responsible_person__icontains=search)
                | Q(location__icontains=search)
            )
        category = params.get("category")
        if category:
            queryset = queryset.filter(category_ref_id=category)
        location = (params.get("location") or "").strip()
        if location:
            queryset = queryset.filter(location__icontains=location)
        if params.get("condition"):
            queryset = queryset.filter(condition=params["condition"])
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        ordering = params.get("ordering") or "asset_id"
        if ordering not in ORDERING:
            ordering = "asset_id"
        return queryset.order_by(ordering)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Assets stay on the register for the audit trail. Record a disposal or write-off instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(asset_summary())

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        asset = self.get_object()
        disposal = AssetDisposal.objects.filter(asset=asset).first()
        return Response({
            "valuations": AssetValuationSerializer(asset.valuations.all(), many=True).data,
            "maintenance": AssetMaintenanceSerializer(asset.maintenance_records.all(), many=True).data,
            "transfers": AssetTransferSerializer(asset.transfers.all(), many=True).data,
            "disposal": AssetDisposalSerializer(disposal).data if disposal else None,
            "depreciation": DepreciationEntrySerializer(DepreciationEntry.objects.filter(asset=asset).select_related("journal"), many=True).data,
            "documents": AssetDocumentSerializer(asset.documents.all(), many=True, context={"request": request}).data,
            "audit": AssetAuditSerializer(asset.audit_events.select_related("actor"), many=True).data,
        })

    @action(detail=True, methods=["post"])
    def maintenance(self, request, pk=None):
        record = record_maintenance(
            self.get_object(),
            request.user,
            parse_day(request.data.get("activity_date"), "the maintenance date"),
            request.data.get("description") or "",
            request.data.get("cost") or 0,
            request.data.get("supplier") or "",
            request.data.get("notes") or "",
        )
        return Response(AssetMaintenanceSerializer(record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        record = transfer_asset(
            self.get_object(),
            request.user,
            parse_day(request.data.get("transfer_date"), "the transfer date"),
            request.data.get("to_location") or "",
            request.data.get("to_department") or "",
            request.data.get("to_person") or "",
            request.data.get("notes") or "",
        )
        return Response(AssetTransferSerializer(record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def dispose(self, request, pk=None):
        record = dispose_asset(
            self.get_object(),
            request.user,
            request.data.get("kind") or "",
            parse_day(request.data.get("disposed_on"), "the disposal date"),
            request.data.get("reason") or "",
            request.data.get("proceeds") or 0,
        )
        return Response(AssetDisposalSerializer(record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def valuations(self, request, pk=None):
        asset = record_valuation(
            self.get_object(),
            request.user,
            parse_day(request.data.get("valued_on"), "the valuation date"),
            request.data.get("amount"),
            request.data.get("note") or "",
        )
        return Response(AssetSerializer(asset).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def documents(self, request, pk=None):
        asset = self.get_object()
        if request.method == "GET":
            return Response(AssetDocumentSerializer(asset.documents.all(), many=True, context={"request": request}).data)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "Choose a file to attach."}, status=status.HTTP_400_BAD_REQUEST)
        document = add_document(asset, request.user, upload, request.data.get("title") or "")
        return Response(AssetDocumentSerializer(document, context={"request": request}).data, status=status.HTTP_201_CREATED)


class PayrollEntryViewSet(viewsets.ModelViewSet):
    queryset = PayrollEntry.objects.all()
    serializer_class = PayrollEntrySerializer
    permission_classes = [FinanceAccessPermission]
