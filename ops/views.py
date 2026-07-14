from django.contrib.auth import authenticate, login, logout
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Lead
from menu.models import Company

from .permissions import platform_admin_required


def _stats():
    return {
        'new_leads': Lead.objects.filter(status='new').count(),
        'total_leads': Lead.objects.count(),
        'active_tenants': Company.objects.filter(status='active').count(),
        'suspended_tenants': Company.objects.filter(status='suspended').count(),
    }


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
    back = request.POST.get('next', '') or reverse('ops:leads')
    return redirect(back)
