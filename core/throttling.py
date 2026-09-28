from django.core.cache import cache
from django.http import JsonResponse
from django.contrib import messages
from django.shortcuts import redirect
from functools import wraps
from rest_framework.throttling import SimpleRateThrottle


# -------------------------------------------------------------
# 1. DRF API THROTTLES (Standard DRF SimpleRateThrottle)
# -------------------------------------------------------------

class AuthAttemptRateThrottle(SimpleRateThrottle):
    """Limits login and OTP verification attempts (e.g. 5/min)"""
    scope = 'auth_attempt'

    def get_cache_key(self, request, view):
        return self.get_ident(request)


class OTPRequestRateThrottle(SimpleRateThrottle):
    """Limits OTP generation / resending requests (e.g. 3/min)"""
    scope = 'otp_request'

    def get_cache_key(self, request, view):
        return self.get_ident(request)


class AIGenerationRateThrottle(SimpleRateThrottle):
    """Limits AI quiz generation and bot calls (e.g. 15/hour)"""
    scope = 'ai_generation'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"ai_user_{request.user.pk}"
        return self.get_ident(request)


class ResourceUploadRateThrottle(SimpleRateThrottle):
    """Limits resource uploads to prevent spam (e.g. 20/hour)"""
    scope = 'resource_upload'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"upload_user_{request.user.pk}"
        return self.get_ident(request)


# -------------------------------------------------------------
# 2. WEB VIEW RATE LIMITER (Simple Cache Counter for HTML/AJAX)
# -------------------------------------------------------------

def is_rate_limited(request, scope, limit=5, timeout=60):
    """
    Checks if an IP has exceeded the allowed requests count in cache.
    Returns True if blocked, False if allowed.
    """
    from django.conf import settings
    # In development/debug mode, never throttle local requests
    if getattr(settings, 'DEBUG', False):
        return False

    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '127.0.0.1')).split(',')[0].strip()
    cache_key = f"web_rate_{scope}_{ip}"

    attempts = cache.get(cache_key, 0)
    if attempts >= limit:
        return True

    cache.set(cache_key, attempts + 1, timeout=timeout)
    return False


def ratelimit(scope='general', limit=5, timeout=60):
    """
    Simple decorator for web views. Blocks spam and returns user-friendly messages.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.method == 'POST' and is_rate_limited(request, scope, limit=limit, timeout=timeout):
                msg = f"Too many requests! Please wait {timeout} seconds before trying again."
                is_ajax = (
                    request.headers.get('x-requested-with') == 'XMLHttpRequest' or
                    request.content_type == 'application/json' or
                    request.POST.get('ajax') == 'true'
                )

                if is_ajax:
                    res = JsonResponse({'status': 'error', 'detail': msg}, status=429)
                    res['Retry-After'] = str(timeout)
                    return res

                messages.error(request, msg)
                res = redirect(request.path)
                res.status_code = 302
                return res

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
