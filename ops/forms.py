import secrets

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction

from menu.models import Branch, Company, Membership
from menu.slugs import validate_subdomain_slug
from menu.themes import DEFAULT_THEME


class TenantCreateForm(forms.Form):
    # venue
    name = forms.CharField(max_length=120, label='Venue name')
    slug = forms.CharField(max_length=40, label='Subdomain')
    tagline = forms.CharField(max_length=200, required=False)
    phone = forms.CharField(max_length=40, required=False)
    email = forms.EmailField(required=False)
    instagram = forms.CharField(max_length=120, required=False)
    facebook = forms.CharField(max_length=120, required=False)
    tiktok = forms.CharField(max_length=120, required=False)
    # look
    menu_theme = forms.ChoiceField(choices=Company.MENU_THEME_CHOICES,
                                   initial=DEFAULT_THEME, label='Menu theme')
    menu_layout = forms.ChoiceField(choices=Company.MENU_LAYOUT_CHOICES,
                                    initial='baseline', label='Menu layout')
    # commercial
    package = forms.ChoiceField(choices=Company.PACKAGE_CHOICES,
                                initial='business')
    status = forms.ChoiceField(choices=[('active', 'Active'),
                                        ('suspended', 'Suspended')],
                               initial='active')
    # owner login
    owner_username = forms.CharField(max_length=150, label='Owner username')
    owner_email = forms.EmailField(required=False, label='Owner email')
    owner_password = forms.CharField(
        max_length=128, required=False, label='Owner password',
        help_text='Leave blank to auto-generate.')
    # first branch
    branch_name = forms.CharField(max_length=120, label='Branch name')
    branch_address = forms.CharField(max_length=200, required=False,
                                     label='Branch address')

    def clean_slug(self):
        slug = self.cleaned_data['slug'].strip().lower()
        validate_subdomain_slug(slug)   # raises ValidationError with message
        return slug

    def clean_owner_username(self):
        username = self.cleaned_data['owner_username'].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError('This username is already taken.')
        return username

    @transaction.atomic
    def save(self, lead=None):
        """Create Company + first Branch + owner User + Membership atomically.
        Returns (company, branch, user, password) — password is plaintext for
        one-time display only."""
        d = self.cleaned_data
        company = Company.objects.create(
            name=d['name'], slug=d['slug'], tagline=d['tagline'],
            phone=d['phone'], email=d['email'], instagram=d['instagram'],
            facebook=d['facebook'], tiktok=d['tiktok'],
            menu_theme=d['menu_theme'], menu_layout=d['menu_layout'],
            package=d['package'], status=d['status'])
        branch = Branch.all_objects.create(
            company=company, name=d['branch_name'],
            slug='main', address=d['branch_address'])
        password = d['owner_password'] or secrets.token_urlsafe(9)
        user = User.objects.create_user(
            username=d['owner_username'], email=d['owner_email'],
            password=password)
        Membership.objects.create(user=user, company=company,
                                  role=Membership.ROLE_OWNER)
        if lead is not None:
            lead.status = 'converted'
            lead.company = company
            lead.save(update_fields=['status', 'company'])
        return company, branch, user, password
