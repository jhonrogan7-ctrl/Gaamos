import secrets

from django.core.exceptions import ValidationError
from django.db import models

from .tenancy import TenantScopedModel, get_current_company
from .themes import DEFAULT_THEME, THEME_CHOICES

_TABLE_CODE_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'  # no 0/o/1/l/i


def generate_table_code(length=6):
    return ''.join(secrets.choice(_TABLE_CODE_ALPHABET) for _ in range(length))


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
    MENU_LAYOUT_CHOICES = [
        ('baseline', 'Baseline — rail + accordion'),
        ('tabs', 'Top tabs + scroll-spy'),
        ('iconrail', 'Icon rail + chips'),
    ]
    menu_layout = models.CharField(
        max_length=20, default='baseline', choices=MENU_LAYOUT_CHOICES)

    MENU_THEME_CHOICES = THEME_CHOICES   # name kept: ops form + tests read it
    menu_theme = models.CharField(
        max_length=20, default=DEFAULT_THEME, choices=THEME_CHOICES)

    PACKAGE_CHOICES = [('business', 'Business'), ('vip', 'VIP')]
    package = models.CharField(
        max_length=20, default='business', choices=PACKAGE_CHOICES)

    logo_url = models.CharField(max_length=200, blank=True)

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
    menu_theme = models.CharField(              # '' = inherit company default
        max_length=20, blank=True, default='',
        choices=THEME_CHOICES)
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
    slug = models.SlugField(max_length=80)
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


class _SameCompanyMixin:
    """Validates that all company-bearing FKs on a branch-rooted row agree."""
    same_company_fields = ()  # names of related objects that carry .company / .company_id

    def clean(self):
        super().clean()
        companies = set()
        for field in self.same_company_fields:
            obj = getattr(self, field, None)
            if obj is not None and getattr(obj, 'company_id', None) is not None:
                companies.add(obj.company_id)
        # Empty/singleton set = FKs unassigned or all one company; required-field
        # validation fires separately in full_clean(). Only a true multi-company span fails.
        if len(companies) > 1:
            raise ValidationError('All related objects must belong to the same company.')


class BranchMenuItem(_SameCompanyMixin, models.Model):
    same_company_fields = ('branch', 'menu_item')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='branch_items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='branch_items')
    price_override = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('branch', 'menu_item')

    @property
    def effective_price(self):
        return self.price_override if self.price_override is not None else self.menu_item.price

    def __str__(self):
        return f"{self.branch.name} / {self.menu_item.name}"


class BranchCategory(_SameCompanyMixin, models.Model):
    same_company_fields = ('branch', 'category')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='branch_categories')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='branch_links')
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('branch', 'category')
        ordering = ['display_order']

    def __str__(self):
        return f"{self.branch.name} / {self.category.name}"


class BranchSubCategory(_SameCompanyMixin, models.Model):
    same_company_fields = ('branch', 'sub_category')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='branch_subcategories')
    sub_category = models.ForeignKey(SubCategory, on_delete=models.CASCADE, related_name='branch_links')
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('branch', 'sub_category')
        ordering = ['display_order']

    def __str__(self):
        return f"{self.branch.name} / {self.sub_category.name}"


class BranchItemPlacement(_SameCompanyMixin, models.Model):
    same_company_fields = ('branch', 'menu_item', 'category', 'sub_category')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='placements')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='placements')
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    sub_category = models.ForeignKey(SubCategory, on_delete=models.CASCADE, null=True, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('branch', 'menu_item', 'category', 'sub_category')
        ordering = ['display_order']

    def __str__(self):
        return f"{self.branch.name} / {self.menu_item.name} @ {self.category.name}"


class Table(TenantScopedModel):
    """A physical table within a branch. Its QR encodes ?branch=<slug>&t=<code>;
    the QR image is rendered on demand (never stored)."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='tables')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='tables')
    code = models.CharField(max_length=16, unique=True, blank=True)
    label = models.CharField(max_length=40)
    display_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        ordering = ['display_order', 'created_at']

    def clean(self):
        super().clean()
        if (self.branch_id and self.company_id
                and self.branch.company_id != self.company_id):
            raise ValidationError('Table branch must belong to the same company.')

    def save(self, *args, **kwargs):
        if not self.code:
            for _ in range(10):
                candidate = generate_table_code()
                if not Table.all_objects.filter(code=candidate).exists():
                    self.code = candidate
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.branch.name} / {self.label}"


class BranchAd(TenantScopedModel):
    """Per-branch promo interstitial shown once per visit on the guest menu.
    One ad per branch; image stays saved while toggled off."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='branch_ads')
    branch = models.OneToOneField(Branch, on_delete=models.CASCADE, related_name='ad')
    image_url = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)  # guest-side re-show "version"

    def clean(self):
        super().clean()
        if (self.branch_id and self.company_id
                and self.branch.company_id != self.company_id):
            raise ValidationError('Ad branch must belong to the same company.')

    def __str__(self):
        return f"{self.branch.name} ad"


class Order(TenantScopedModel):
    STATUS_NEW = 'new'
    STATUS_SERVED = 'served'
    STATUS_CHOICES = [(STATUS_NEW, 'New'), (STATUS_SERVED, 'Served')]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='orders')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='orders')
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    table_label = models.CharField(max_length=40, blank=True)  # snapshot; "" => Takeaway
    number = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_NEW)
    total = models.PositiveIntegerField(default=0)  # Rs
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TenantScopedModel.Meta):
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['company', 'number'],
                                               name='uniq_order_company_number')]

    def clean(self):
        super().clean()
        if (self.table_id and self.company_id
                and self.table.company_id != self.company_id):
            raise ValidationError('Order table must belong to the same company.')

    def save(self, *args, **kwargs):
        if self.company_id is None:
            current = get_current_company()
            if current is not None:
                self.company = current
        if not self.number and self.company_id:
            last = (Order.all_objects.filter(company_id=self.company_id)
                    .aggregate(m=models.Max('number'))['m'] or 0)
            self.number = last + 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"#{self.number} @ {self.branch.name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=120)       # snapshot
    unit_price = models.PositiveIntegerField()    # Rs snapshot
    qty = models.PositiveSmallIntegerField()

    @property
    def line_total(self):
        return self.unit_price * self.qty

    def __str__(self):
        return f"{self.name} ×{self.qty}"


class Membership(models.Model):
    ROLE_OWNER = 'owner'
    ROLE_MANAGER = 'manager'
    ROLE_CHOICES = [(ROLE_OWNER, 'Owner'), (ROLE_MANAGER, 'Manager')]

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='memberships')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MANAGER)
    branches = models.ManyToManyField(Branch, blank=True, related_name='managers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'company')

    @property
    def is_owner(self):
        return self.role == self.ROLE_OWNER

    def __str__(self):
        return f"{self.user.username} @ {self.company.slug} ({self.role})"
