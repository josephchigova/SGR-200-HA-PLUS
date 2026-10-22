from rest_framework import viewsets

from apps.accounts.permissions import FinanceAccessPermission

from .models import Asset, Expense, PayrollEntry, Receipt
from .serializers import AssetSerializer, ExpenseSerializer, PayrollEntrySerializer, ReceiptSerializer


class ReceiptViewSet(viewsets.ModelViewSet):
    queryset = Receipt.objects.all()
    serializer_class = ReceiptSerializer
    permission_classes = [FinanceAccessPermission]


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [FinanceAccessPermission]


class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    permission_classes = [FinanceAccessPermission]


class PayrollEntryViewSet(viewsets.ModelViewSet):
    queryset = PayrollEntry.objects.all()
    serializer_class = PayrollEntrySerializer
    permission_classes = [FinanceAccessPermission]
