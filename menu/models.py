import secrets

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from pgvector.django import VectorField

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


class BranchVisit(TenantScopedModel):
    """One row per guest menu page load. Backs the QR-scan analytics on the
    dashboard overview; a 'scan' is a guest hitting the menu, not a distinct
    physical QR code read (a table refresh counts too)."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='branch_visits')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='visits')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.branch.name} @ {self.created_at:%Y-%m-%d %H:%M}"


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


class PushSubscription(TenantScopedModel):
    """One browser's Web Push registration for one dashboard user.

    Opt-in **per device**: a manager who enables notifications on their phone
    does not thereby enable them on the till. The endpoint is the browser's
    own push-service URL and is globally unique, so it is the natural key —
    re-subscribing the same browser updates the row rather than duplicating it.

    Rows are disposable. Push services expire endpoints without warning, and a
    404/410 on send is the documented signal to delete the subscription.
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE,
                                related_name='push_subscriptions')
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE,
                             related_name='push_subscriptions')
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)   # client public key
    auth = models.CharField(max_length=255)     # client auth secret
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantScopedModel.Meta):
        ordering = ['-created_at']

    def as_subscription_info(self):
        """The dict shape pywebpush expects."""
        return {'endpoint': self.endpoint,
                'keys': {'p256dh': self.p256dh, 'auth': self.auth}}

    def __str__(self):
        return f"push<{self.user.username}@{self.company.slug}>"


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


class ImageAsset(models.Model):
    """Global (cross-tenant) sourcing pool for menu images. NOT tenant-scoped:
    a staff-only internal library the pipeline matches against before hitting
    external finders. Never exposed to tenant operators."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]

    name = models.CharField(max_length=200, blank=True)
    caption = models.TextField(blank=True)
    tags = models.JSONField(default=list)
    embedding = VectorField(dimensions=768, null=True, blank=True)
    source = models.CharField(max_length=20)
    origin_url = models.CharField(max_length=1000, blank=True)
    prompt = models.TextField(blank=True)
    license = models.CharField(max_length=200, blank=True)
    attribution = models.CharField(max_length=500, blank=True)
    file = models.CharField(max_length=500, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    found_for_slug = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey('auth.User', null=True, blank=True,
                                    on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['origin_url'], condition=~Q(origin_url=''),
                name='uniq_imageasset_origin_url'),
            models.UniqueConstraint(
                fields=['content_hash'], condition=~Q(content_hash=''),
                name='uniq_imageasset_content_hash'),
        ]

    def __str__(self):
        return self.name or f"ImageAsset #{self.pk}"

    @property
    def image_url(self):
        from django.conf import settings
        return f"{settings.MEDIA_URL}{self.file}" if self.file else ""

    @property
    def origin_link(self):
        url = self.origin_url or ""
        return url if url.startswith(("http://", "https://")) else ""


class MenuScan(models.Model):
    """A staff-uploaded cafe menu document + its extraction job (global, non-tenant)."""

    STATUS_CHOICES = [
        ('queued', 'Queued'), ('processing', 'Processing'),
        ('extracted', 'Extracted'), ('reviewed', 'Reviewed'),
        ('imported', 'Imported'), ('failed', 'Failed'),
    ]

    file = models.CharField(max_length=500)
    source_cafe = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='queued')
    raw_extraction = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    task_id = models.CharField(max_length=100, blank=True)
    image_task_id = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey('auth.User', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='menu_scans')
    created_at = models.DateTimeField(auto_now_add=True)
    # Nullable on purpose: the pre-wizard /platform/scans/ flow creates scans
    # with no build and must keep working untouched.
    build = models.ForeignKey('MenuBuild', null=True, blank=True,
                              on_delete=models.CASCADE, related_name='scans')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.source_cafe or 'scan'} #{self.pk} ({self.status})"

    @property
    def file_url(self):
        from django.conf import settings
        return f"{settings.MEDIA_URL}{self.file}" if self.file else ""


class Item(models.Model):
    """A global platform-catalog menu item (staff-curated, cross-tenant, reusable).

    One item = one price. A price variant (Half/Full, 60ml/Qtr., Yellow/Blue) is a
    SEPARATE Item sharing a `base_name` — founder decision D3 — so every variant
    carries its own photo, tags and library match.
    """

    STATUS_CHOICES = [
        ('draft', 'Draft'), ('active', 'Active'),
        ('merged', 'Merged'), ('rejected', 'Rejected'),
    ]

    # Identity
    name = models.CharField(max_length=200)
    base_name = models.CharField(max_length=200, blank=True)
    variant_label = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    tags = models.JSONField(default=list, blank=True)

    # Commerce
    reference_price = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default='NPR')

    # Classification
    dietary_tags = models.JSONField(default=list, blank=True)

    # --- Library (spec D3: the library IS this model, extended) ---
    # The normalized base name, written by `name_norm.search_form`. The
    # matcher's fast path and the backfill's dedup key; trigram-indexed below.
    search_name = models.CharField(max_length=200, blank=True)
    # Every entry carries its prompt, so a MATCHED item can be re-rolled at
    # gate 2 without re-deriving anything.
    image_prompt = models.TextField(blank=True)
    # How many venues serve this entry. Breaks ties between duplicate
    # candidates: the tea four venues pour outranks a one-off.
    use_count = models.PositiveIntegerField(default=0)
    origin_company = models.ForeignKey('Company', null=True, blank=True,
                                       on_delete=models.SET_NULL,
                                       related_name='library_items')
    # False for a photograph the venue supplied (founder, spec D2). It is their
    # property: the entry matches for that venue only and never leaks.
    shareable = models.BooleanField(default=True)

    # Media + matching
    # 1024-d: `nvidia/nv-embedqa-e5-v5`'s width. See menu/pipeline/item_embed.py
    # for why re-using the old 768-d Gemini vectors was never an option.
    embedding = VectorField(dimensions=1024, null=True, blank=True)
    image_asset = models.ForeignKey('ImageAsset', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='items')

    # Provenance — verbatim print, so nothing is ever unrecoverable
    source_scan = models.ForeignKey('MenuScan', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='items')
    source_page = models.PositiveSmallIntegerField(null=True, blank=True)
    raw_name = models.CharField(max_length=300, blank=True)
    raw_price_text = models.CharField(max_length=120, blank=True)
    raw_section = models.CharField(max_length=200, blank=True)
    split_from = models.CharField(max_length=300, blank=True)
    confidence = models.FloatField(default=1.0)
    needs_review = models.BooleanField(default=False)

    # Lifecycle
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    merged_into = models.ForeignKey('self', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='merged_from')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('auth.User', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='catalog_items')

    class Meta:
        ordering = ['name']
        indexes = [
            # Layer 2 of the matcher: fuzzy candidates over OCR noise and
            # spelling drift, at zero API cost.
            GinIndex(OpClass(F('search_name'), name='gin_trgm_ops'),
                     name='item_search_name_trgm'),
            # Layer 1: exact on (search_name, variant_label).
            models.Index(fields=['search_name', 'variant_label'],
                         name='item_search_variant'),
        ]

    def __str__(self):
        return self.name


class MenuBuild(models.Model):
    """One onboarding run: a venue, its branches, and the card it was built from.

    Owns disposable scratch rows, never tenant data. Nothing here is written to
    a live menu until `publish`, which is what makes an abandoned build free and
    re-extracting a single document safe.
    """

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('generating', 'Generating'),
        ('review', 'Review'),
        ('publishing', 'Publishing'),
        ('published', 'Published'),
        ('failed', 'Failed'),
    ]

    company = models.ForeignKey('Company', on_delete=models.CASCADE,
                                related_name='menu_builds')
    branches = models.ManyToManyField('Branch', related_name='menu_builds')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='draft')
    created_by = models.ForeignKey('auth.User', null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name='menu_builds')
    created_at = models.DateTimeField(auto_now_add=True)
    # The models this run actually used. A build is reproducible, and a later
    # model swap is visible rather than silently changing what a rebuild means.
    vision_model = models.CharField(max_length=120, blank=True)
    embed_model = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.company.slug} build #{self.pk} ({self.status})'

    def branch_list(self):
        """This build's branches, read cross-tenant on purpose.

        `self.branches.all()` CANNOT be used and is not an oversight: the M2M's
        related manager derives from `Branch`'s fail-closed `TenantManager`, and
        every wizard screen is apex with no company in context, so it raises
        `TenantContextRequired`. Routing through `all_objects` here is the
        deliberate cross-tenant access that guard asks for -- in one place, so
        no view or service can forget it.
        """
        return Branch.all_objects.filter(menu_builds=self)


class MenuBuildSection(models.Model):
    """A printed section of the card, in the venue's own words.

    A model rather than a string on the row (the parent spec's shape) because
    gate 1 confirms prices PER SECTION, and sections rename, reorder and carry
    an icon. Against a denormalised string a rename rewrites every row and
    `prices_confirmed` has nowhere to live.
    """

    build = models.ForeignKey(MenuBuild, on_delete=models.CASCADE,
                              related_name='sections')
    name = models.CharField(max_length=200)
    # The sheet has two levels and so does a published menu (BranchCategory +
    # BranchSubcategory). A section is therefore the PAIR: `Nepali Foods` alone
    # holds six subcategories on the first real card, and flattening them would
    # drop all six into one heap.
    sub_name = models.CharField(max_length=200, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    icon_key = models.CharField(max_length=60, blank=True)
    # Gate 1's blocking rule. The spec's null-price rule can never fire -- the
    # extractor invents a price for every one it cannot read -- so what blocks
    # the build is a human confirming a section against the photograph.
    prices_confirmed = models.BooleanField(default=False)

    class Meta:
        ordering = ['display_order', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['build', 'name', 'sub_name'],
                                    name='uniq_buildsection_build_name'),
        ]

    def __str__(self):
        return self.name


class MenuBuildRow(models.Model):
    """One printed menu row, as scratch space.

    Disposable by design: `Item`, `ImageAsset` and `MenuItem` stay canonical and
    this table is free to be rewritten by a re-extraction.
    """

    MATCH_STATES = [
        ('none', 'No match'), ('auto', 'Auto'), ('suggested', 'Suggested'),
        ('accepted', 'Accepted'), ('rejected', 'Rejected'),
    ]
    IMAGE_STATES = [
        ('none', 'None'), ('matched', 'From the library'), ('generated', 'Generated'),
    ]

    build = models.ForeignKey(MenuBuild, on_delete=models.CASCADE, related_name='rows')
    section = models.ForeignKey(MenuBuildSection, on_delete=models.CASCADE,
                                related_name='rows')
    display_order = models.PositiveSmallIntegerField(default=0)

    # --- what the card printed ---
    name = models.CharField(max_length=300)
    base_name = models.CharField(max_length=200, blank=True)
    variant_label = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    price = models.PositiveIntegerField(null=True, blank=True)
    tags = models.JSONField(default=list, blank=True)
    dietary_tags = models.JSONField(default=list, blank=True)
    raw_name = models.CharField(max_length=300, blank=True)
    raw_price_text = models.CharField(max_length=120, blank=True)
    split_from = models.CharField(max_length=300, blank=True)
    confidence = models.FloatField(default=1.0)
    source_scan = models.ForeignKey('MenuScan', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='build_rows')
    source_page = models.PositiveSmallIntegerField(null=True, blank=True)

    # --- the match ---
    matched_item = models.ForeignKey('Item', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='build_rows')
    match_score = models.FloatField(default=0.0)
    match_method = models.CharField(max_length=20, blank=True)
    match_state = models.CharField(max_length=10, choices=MATCH_STATES, default='none')

    # --- the image ---
    image_prompt = models.TextField(blank=True)
    image_asset = models.ForeignKey('ImageAsset', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='build_rows')
    image_state = models.CharField(max_length=10, choices=IMAGE_STATES, default='none')

    # Whatever the sheet's Notes column said, plus anything the parser found.
    # This is the ONLY signal for "a human should look at this row", so it must
    # survive into review — a row that turns red without saying why is worse
    # than a row that is not flagged at all.
    notes = models.TextField(blank=True)

    @property
    def needs_check(self):
        return bool(self.notes)

    # --- after publish ---
    published_item = models.ForeignKey('MenuItem', null=True, blank=True,
                                       on_delete=models.SET_NULL,
                                       related_name='build_rows')

    class Meta:
        ordering = ['section__display_order', 'display_order', 'pk']

    def __str__(self):
        return self.name
