from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render


def forbidden(request):
    return render(request, 'dashboard/403.html', status=403)


def get_membership(request):
    return getattr(request, 'membership', None)


def can_manage_branch(membership, branch):
    if membership is None:
        return False
    if membership.is_owner:
        return True
    return membership.branches.filter(pk=branch.pk).exists()


def ensure_can_manage_branch(request, branch):
    if getattr(request.user, 'is_superuser', False):
        return True
    return can_manage_branch(get_membership(request), branch)


def visible_branches(request):
    """Branches this user may see: owners/superusers all (tenant-scoped),
    managers only their assigned branches, everyone else none."""
    from .models import Branch
    m = get_membership(request)
    if getattr(request.user, 'is_superuser', False) or (m and m.is_owner):
        return Branch.objects.all()
    if m:
        return Branch.objects.filter(pk__in=m.branches.values_list('pk', flat=True))
    return Branch.objects.none()


def require_membership(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.is_superuser:
            return view(request, *args, **kwargs)
        if get_membership(request) is None:
            return forbidden(request)
        return view(request, *args, **kwargs)
    return wrapped


def require_owner(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.is_superuser:
            return view(request, *args, **kwargs)
        m = get_membership(request)
        if m is None or not m.is_owner:
            return forbidden(request)
        return view(request, *args, **kwargs)
    return wrapped
