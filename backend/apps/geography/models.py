from django.db import models


class Province(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True, blank=True)
    official = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class District(models.Model):
    province = models.ForeignKey(Province, on_delete=models.CASCADE, related_name="districts")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["province__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["province", "name"], name="unique_district_per_province"),
        ]

    def __str__(self):
        return f"{self.name}, {self.province.name}"


class Ward(models.Model):
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name="wards")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["district__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["district", "name"], name="unique_ward_per_district"),
        ]

    def __str__(self):
        return f"{self.name}, {self.district.name}"
