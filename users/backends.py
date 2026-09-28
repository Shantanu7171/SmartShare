from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

UserModel = get_user_model()

class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate against either email or username with password.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        lookup = username or kwargs.get('email') or kwargs.get('username')
        if not lookup or not password:
            return None
            
        try:
            user = UserModel.objects.get(Q(email__iexact=lookup) | Q(username__iexact=lookup))
        except UserModel.DoesNotExist:
            return None
        except UserModel.MultipleObjectsReturned:
            # Fallback to exact match on email then username
            user = UserModel.objects.filter(email__iexact=lookup).first() or UserModel.objects.filter(username__iexact=lookup).first()
            if not user:
                return None
            
        if user.check_password(password):
            return user
        return None

    def user_can_authenticate(self, user):
        """
        Allow inactive users to pass authentication so we can detect them in the view
        and prompt for OTP verification without doing a double password check.
        """
        return True
