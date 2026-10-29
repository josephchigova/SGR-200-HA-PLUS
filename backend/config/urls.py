from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.search_views import GlobalSearchView
from config.views import health, spa_index

urlpatterns = [
    path("api/health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/search/", GlobalSearchView.as_view(), name="global-search"),
    path("api/", include("apps.geography.urls")),
    path("api/", include("apps.clusters.urls")),
    path("api/", include("apps.farmers.urls")),
    path("api/", include("apps.programmes.urls")),
    path("api/", include("apps.inputs.urls")),
    path("api/", include("apps.recovery.urls")),
    path("api/", include("apps.arda_requests.urls")),
    path("api/", include("apps.reports.urls")),
    path("api/", include("apps.subscriptions.urls")),
    path("api/", include("apps.finance.urls")),
    path("api/", include("apps.production.urls")),
    path("api/", include("apps.source_data.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    re_path(r"^(?!api(?:/|$)|admin(?:/|$)|static(?:/|$)|media(?:/|$)).*$", spa_index, name="spa"),
]
