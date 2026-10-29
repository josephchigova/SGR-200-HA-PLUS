from django.contrib import admin

from .models import District, Province, Ward

admin.site.register(Province)
admin.site.register(District)
admin.site.register(Ward)
