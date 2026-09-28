import logging
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed

logger = logging.getLogger(__name__)


class FlexibleJWTAuthentication(JWTAuthentication):
    """
    Enhanced JWT Authentication that allows graceful fallback to SessionAuthentication
    when accessed from browser interfaces where a stale/expired token might exist in localStorage.
    """
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except (InvalidToken, AuthenticationFailed) as e:
            # If the user has a valid Django session cookie, fall through to SessionAuthentication
            django_user = getattr(request._request, 'user', None)
            if django_user and django_user.is_authenticated:
                logger.info(f"JWT expired/invalid for user {django_user.username}; falling back to Django Session authentication.")
                return (django_user, None)
            # If no session either, return None so DRF permission classes handle 401 properly
            return None
