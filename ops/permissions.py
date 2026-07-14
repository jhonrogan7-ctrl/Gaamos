from functools import wraps

from django.http import Http404
from django.shortcuts import redirect


def platform_admin_required(view):
    """Apex-host + superuser gate for every platform-ops view. Fail closed."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if getattr(request, 'company', None) is not None:
            raise Http404
        if not (request.user.is_authenticated and request.user.is_superuser):
            return redirect('ops:login')
        return view(request, *args, **kwargs)
    return wrapped
