from django.db.models import Q
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.arda_requests.models import ARDARequest
from apps.farmers.models import Farmer
from apps.inputs.models import InputIssue
from apps.programmes.models import Programme
from apps.recovery.models import RecoveryRecord
from apps.subscriptions.models import FarmerSubscription, Subscription


class GlobalSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return Response({"query": "", "results": []})

        farmer_filter = Q(first_name__icontains=query) | Q(surname__icontains=query) | Q(full_name__icontains=query) | Q(national_id__icontains=query) | Q(membership_number__icontains=query) | Q(phone_primary__icontains=query) | Q(email__icontains=query)
        farmer_ids = list(Farmer.objects.filter(farmer_filter).values_list("id", flat=True)[:25])
        farmer_results = [
            {"type": "Farmer", "id": farmer.id, "title": farmer.full_name, "subtitle": farmer.national_id, "url": "/farmers"}
            for farmer in Farmer.objects.filter(id__in=farmer_ids)
        ]

        results = farmer_results
        results += [
            {"type": "Programme", "id": item.id, "title": item.name, "subtitle": item.code, "url": "/programmes"}
            for item in Programme.objects.filter(Q(name__icontains=query) | Q(code__icontains=query))[:25]
        ]
        results += [
            {"type": "Input Issue", "id": item.id, "title": item.input_name, "subtitle": item.farmer.full_name, "url": "/inputs"}
            for item in InputIssue.objects.select_related("farmer").filter(Q(input_name__icontains=query) | Q(batch_number__icontains=query) | Q(farmer__full_name__icontains=query))[:25]
        ]
        results += [
            {"type": "Recovery", "id": item.id, "title": item.farmer.full_name, "subtitle": item.status, "url": "/recovery"}
            for item in RecoveryRecord.objects.select_related("farmer").filter(Q(farmer__full_name__icontains=query) | Q(farm_name__icontains=query) | Q(crop__icontains=query) | Q(status__icontains=query))[:25]
        ]
        results += [
            {"type": "ARDA Request", "id": item.id, "title": item.farmer.full_name, "subtitle": item.request_type, "url": "/arda-requests"}
            for item in ARDARequest.objects.select_related("farmer").filter(Q(farmer__full_name__icontains=query) | Q(request_type__icontains=query) | Q(status__icontains=query))[:25]
        ]
        results += [
            {"type": "Subscription", "id": item.id, "title": item.name, "subtitle": item.code, "url": "/subscriptions"}
            for item in Subscription.objects.filter(Q(name__icontains=query) | Q(code__icontains=query))[:25]
        ]
        results += [
            {"type": "Farmer Subscription", "id": item.id, "title": item.farmer.full_name, "subtitle": item.category, "url": "/subscriptions"}
            for item in FarmerSubscription.objects.select_related("farmer").filter(Q(farmer__full_name__icontains=query) | Q(category__icontains=query) | Q(payment_status__icontains=query))[:25]
        ]

        return Response({"query": query, "results": results[:100]})
