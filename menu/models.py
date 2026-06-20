from django.db import models

from .tenancy import TenantScopedModel


class Company(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=20, default='active',
                              choices=[('active', 'Active'), ('suspended', 'Suspended')])
    created_at = models.DateTimeField(auto_now_add=True)
    tagline = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    instagram = models.CharField(max_length=120, blank=True)
    facebook = models.CharField(max_length=120, blank=True)
    tiktok = models.CharField(max_length=120, blank=True)

    objects = models.Manager()   # plain — Company is the tenant root, not scoped

    def __str__(self):
        return self.name


class Branch(TenantScopedModel):
    TAG_CHOICES = [('FLAGSHIP', 'Flagship'), ('NEW', 'New'), ('', 'Standard')]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=120)
    slug = models.SlugField(blank=True)
    address = models.CharField(max_length=200)
    tag = models.CharField(max_length=20, blank=True, choices=TAG_CHOICES)
    qr_image = models.CharField(max_length=200, blank=True)

    class Meta(TenantScopedModel.Meta):
        constraints = [models.UniqueConstraint(fields=['company', 'slug'],
                                               name='uniq_branch_company_slug')]

    def __str__(self):
        return self.name


class Category(TenantScopedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=80)
    slug = models.SlugField()
    icon_key = models.CharField(max_length=40, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    hours_note = models.CharField(max_length=80, blank=True)

    class Meta(TenantScopedModel.Meta):
        ordering = ['display_order']
        constraints = [models.UniqueConstraint(fields=['company', 'slug'],
                                               name='uniq_category_company_slug')]

    def __str__(self):
        return self.name


class SubCategory(TenantScopedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='subcategories')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='subcategories')
    name = models.CharField(max_length=80)
    icon_key = models.CharField(max_length=40, default='subAll')
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        ordering = ['display_order']
        verbose_name_plural = 'sub-categories'

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class MenuItem(TenantScopedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=120)
    slug = models.SlugField()
    description = models.TextField(blank=True)
    price = models.PositiveIntegerField()
    dietary_tags = models.JSONField(default=list)
    image_url = models.CharField(max_length=500, blank=True)
    focal_x = models.PositiveSmallIntegerField(default=50)
    focal_y = models.PositiveSmallIntegerField(default=50)
    is_popular = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    order_count = models.PositiveIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['company', 'slug'],
                                               name='uniq_menuitem_company_slug')]

    def __str__(self):
        return self.name
