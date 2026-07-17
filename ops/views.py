import secrets

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db.models import Count
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models import Lead
from menu.dashboard.utils import generate_qr_for_branch
from menu.models import Company, Membership

from .forms import TenantCreateForm
from .permissions import platform_admin_required


def generate_password():
    return secrets.token_urlsafe(9)   # ~12 chars, URL-safe


def _stats():
    return {
        'new_leads': Lead.objects.filter(status='new').count(),
        'total_leads': Lead.objects.count(),
        'active_tenants': Company.objects.filter(status='active').count(),
        'suspended_tenants': Company.objects.filter(status='suspended').count(),
    }


@platform_admin_required
def index(request):
    """/platform/ → leads (the decorator bounces anonymous visitors to login)."""
    return redirect('ops:leads')


def login_view(request):
    if getattr(request, 'company', None) is not None:
        raise Http404
    error = ''
    if request.method == 'POST':
        user = authenticate(request,
                            username=request.POST.get('username', ''),
                            password=request.POST.get('password', ''))
        if user is not None and user.is_superuser:
            login(request, user)
            return redirect('ops:leads')
        # Same message for bad password and valid-but-not-superuser: no probing.
        error = 'Invalid credentials.'
    return render(request, 'ops/login.html', {'error': error})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('ops:login')


@platform_admin_required
def leads(request):
    status = request.GET.get('status', '')
    qs = Lead.objects.select_related('company').order_by('-created_at')
    valid = {k for k, _ in Lead.STATUS_CHOICES}
    if status in valid:
        qs = qs.filter(status=status)
    return render(request, 'ops/leads.html', {
        'stats': _stats(), 'active': 'leads',
        'leads': qs, 'status_filter': status,
        'statuses': Lead.STATUS_CHOICES,
    })


@require_POST
@platform_admin_required
def lead_status(request, lead_id):
    lead = get_object_or_404(Lead, pk=lead_id)
    new_status = request.POST.get('status', '')
    if new_status not in {k for k, _ in Lead.STATUS_CHOICES}:
        return HttpResponseBadRequest('bad status')
    lead.status = new_status
    lead.save(update_fields=['status'])
    back = request.POST.get('next', '')
    # Same-site relative paths only (the form sends request.get_full_path).
    if not url_has_allowed_host_and_scheme(back, allowed_hosts=None):
        back = reverse('ops:leads')
    return redirect(back)


@platform_admin_required
def tenants(request):
    # Branch's default manager is tenant-scoped and fail-closed; from the apex
    # host there is no tenant context, so count via annotation, never c.branches.
    companies = (Company.objects.order_by('-created_at')
                 .annotate(branch_count=Count('branches')))
    password_note = request.session.pop('ops_password_note', None)
    return render(request, 'ops/tenants.html', {
        'stats': _stats(), 'active': 'tenants',
        'companies': companies, 'base_domain': settings.BASE_DOMAIN,
        'password_note': password_note,
    })


@require_POST
@platform_admin_required
def tenant_toggle(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    company.status = 'active' if company.status == 'suspended' else 'suspended'
    company.save(update_fields=['status'])
    return redirect('ops:tenants')


@require_POST
@platform_admin_required
def tenant_reset_password(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    owner_membership = (company.memberships
                        .filter(role=Membership.ROLE_OWNER)
                        .select_related('user').first())
    if owner_membership is None:
        return HttpResponseBadRequest('company has no owner')
    new_password = generate_password()
    owner_membership.user.set_password(new_password)
    owner_membership.user.save(update_fields=['password'])
    request.session['ops_password_note'] = {
        'company': company.name,
        'username': owner_membership.user.username,
        'password': new_password,
    }
    return redirect('ops:tenants')


@platform_admin_required
def tenant_new(request):
    lead = None
    lead_id = request.GET.get('lead', '')
    if lead_id.isdigit():
        lead = Lead.objects.filter(pk=lead_id).first()
    if request.method == 'POST':
        form = TenantCreateForm(request.POST)
        if form.is_valid():
            company, branch, user, password = form.save(lead=lead)
            base_url = f"{request.scheme}://{company.slug}.{settings.BASE_DOMAIN}"
            generate_qr_for_branch(branch, base_url)
            request.session['ops_created_note'] = {
                'company_id': company.id, 'username': user.username,
                'password': password,
            }
            return redirect('ops:tenant_created', company_id=company.id)
    else:
        initial = {}
        if lead is not None:
            initial = {'name': lead.venue_name, 'phone': lead.phone,
                       'email': lead.email}
        form = TenantCreateForm(initial=initial)
    return render(request, 'ops/tenant_form.html', {
        'stats': _stats(), 'active': 'new', 'form': form, 'lead': lead,
    })


@platform_admin_required
def tenant_created(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    note = request.session.pop('ops_created_note', None)
    if note and note.get('company_id') != company.id:
        note = None
    return render(request, 'ops/tenant_created.html', {
        'stats': _stats(), 'active': 'tenants', 'company': company,
        'base_domain': settings.BASE_DOMAIN, 'note': note,
    })
