from rest_framework import permissions, viewsets

from .models import ReportTemplate
from .serializers import ReportTemplateSerializer


class ReportTemplateViewSet(viewsets.ModelViewSet):
    queryset = ReportTemplate.objects.all()
    serializer_class = ReportTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]
