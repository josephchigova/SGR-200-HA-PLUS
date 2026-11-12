from django.db.models import Q
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import can
from apps.accounts.scoping import is_scoped, scope_by_farmer, scope_farmers
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

        user = request.user
        results = []
        if can(user, "farmers"):
            farmer_filter = Q(first_name__icontains=query) | Q(surname__icontains=query) | Q(full_name__icontains=query) | Q(national_id__icontains=query) | Q(membership_number__icontains=query) | Q(phone_primary__icontains=query) | Q(email__icontains=query)
            results += [
                {"type": "Farmer", "id": farmer.id, "title": farmer.full_name, "subtitle": farmer.national_id, "url": f"/farmers/{farmer.id}"}
                for farmer in scope_farmers(Farmer.objects.filter(farmer_filter), user)[:25]
            ]
        if can(user, "programmes") and not is_scoped(user):
            results += [
                {"type": "Programme", "id": item.id, "title": item.name, "subtitle": item.code, "url": "/programmes"}
                for item in Programme.objects.filter(Q(name__icontains=query) | Q(code__icontains=query))[:25]
            ]
        if can(user, "allocations"):
            results += [
                {"type": "Input Issue", "id": item.id, "title": item.input_name, "subtitle": item.farmer.full_name, "url": "/input-allocations"}
                for item in scope_by_farmer(InputIssue.objects.select_related("farmer"), user).filter(Q(input_name__icontains=query) | Q(batch_number__icontains=query) | Q(farmer__full_name__icontains=query))[:25]
            ]
        if can(user, "recovery"):
            results += [
                {"type": "Recovery", "id": item.id, "title": item.farmer.full_name, "subtitle": item.status, "url": "/recovery"}
                for item in scope_by_farmer(RecoveryRecord.objects.select_related("farmer"), user).filter(Q(farmer__full_name__icontains=query) | Q(farm_name__icontains=query) | Q(crop__icontains=query) | Q(status__icontains=query))[:25]
            ]
        if can(user, "arda"):
            results += [
                {"type": "ARDA Request", "id": item.id, "title": item.farmer.full_name, "subtitle": item.request_type, "url": "/arda-requests"}
                for item in scope_by_farmer(ARDARequest.objects.select_related("farmer"), user).filter(Q(farmer__full_name__icontains=query) | Q(request_type__icontains=query) | Q(status__icontains=query))[:25]
            ]
        if can(user, "subscriptions"):
            if not is_scoped(user):
                results += [
                    {"type": "Subscription", "id": item.id, "title": item.name, "subtitle": item.code, "url": "/subscriptions"}
                    for item in Subscription.objects.filter(Q(name__icontains=query) | Q(code__icontains=query))[:25]
                ]
            results += [
                {"type": "Farmer Subscription", "id": item.id, "title": item.farmer.full_name, "subtitle": item.category, "url": "/subscriptions"}
                for item in scope_by_farmer(FarmerSubscription.objects.select_related("farmer"), user).filter(Q(farmer__full_name__icontains=query) | Q(category__icontains=query) | Q(payment_status__icontains=query))[:25]
            ]

        return Response({"query": query, "results": results[:100]})
