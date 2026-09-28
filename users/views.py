import random
import threading
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.shortcuts import redirect
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from core.throttling import AuthAttemptRateThrottle, OTPRequestRateThrottle
from .models import EmailOTP
from .serializers import (
    AdminUserSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserProfileSerializer,
)

User = get_user_model()


# =====================================================================
# OTP EMAIL & VERIFICATION HELPERS (EASY & REUSABLE)
# =====================================================================

def send_otp_email_async(user, otp_code, purpose="verification"):
    """
    Background thread me email bhejta hai taaki API response fast rahe.
    Brevo API (agar configured ho) ya default Django send_mail use karta hai.
    """
    def _send():
        try:
            if purpose == "password_reset":
                subject = 'Password Reset OTP - SmartShare'
                message = f"Hello {user.username},\n\nYour Password Reset OTP is: {otp_code}\n\nThis OTP is valid for 10 minutes."
            else:
                subject = 'Verify Your Account - SmartShare'
                message = f"Welcome {user.username}!\n\nYour Account Verification OTP is: {otp_code}\n\nThis OTP is valid for 10 minutes."

            # Agar Brevo API Key ho toh API se bhejo, warna Django SMTP/Console mail
            if getattr(settings, 'BREVO_API_KEY', None):
                import requests
                requests.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": settings.BREVO_API_KEY,
                        "Content-Type": "application/json"
                    },
                    json={
                        "sender": {"name": "SmartShare", "email": settings.DEFAULT_FROM_EMAIL},
                        "to": [{"email": user.email}],
                        "subject": subject,
                        "textContent": message
                    },
                    timeout=10
                )
            else:
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send email to {user.email}: {e}")

    threading.Thread(target=_send, daemon=True).start()


def create_and_send_otp(user, purpose="verification"):
    """
    6-digit random OTP generate karta hai, database me save karta hai, aur email bhejta hai.
    """
    otp_code = str(random.randint(100000, 999999))
    EmailOTP.objects.create(user=user, otp_code=otp_code)
    send_otp_email_async(user, otp_code, purpose=purpose)
    return otp_code


def validate_user_otp(user, otp_code):
    """
    User ka latest OTP check karta hai:
    - Kya OTP exist karta hai?
    - Kya OTP expire ho chuka hai?
    - Kya code sahi hai?
    Returns: (is_valid, error_message)
    """
    otp_record = user.otps.order_by('-created_at').first()
    if not otp_record:
        return False, "No OTP found. Please request a new one."
    if otp_record.is_expired():
        return False, "OTP has expired. Please request a new code."
    if otp_record.otp_code != str(otp_code).strip():
        return False, "Invalid OTP code. Please try again."
    return True, None


# =====================================================================
# AUTHENTICATION VIEWS: REGISTER & LOGIN
# =====================================================================

class RegisterView(generics.CreateAPIView):
    """
    Naye student ka registration karta hai. Unverified accounts ko pehle clean karta hai.
    """
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAttemptRateThrottle]

    def get(self, request, *args, **kwargs):
        return redirect('signup')

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        username = request.data.get('username')

        # Agar pehle se koi inactive registration ho iss email/username se toh use delete karo
        if email:
            User.objects.filter(email__iexact=email, is_active=False).delete()
        if username:
            User.objects.filter(username=username, is_active=False).delete()

        return super().post(request, *args, **kwargs)


class LoginView(APIView):
    """
    User login verify karta hai aur JWT access + refresh tokens return karta hai.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAttemptRateThrottle]

    def get(self, request, *args, **kwargs):
        return redirect('login')

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        user_data = UserProfileSerializer(user, context={'request': request}).data

        return Response({
            'user': user_data,
            'access': serializer.validated_data['access'],
            'refresh': serializer.validated_data['refresh']
        }, status=status.HTTP_200_OK)


# =====================================================================
# OTP VIEWS: VERIFY, RESEND, FORGOT & RESET PASSWORD
# =====================================================================

class VerifyOTPView(APIView):
    """
    Signup ke baad user ka email OTP verify karta hai aur account activate karta hai.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAttemptRateThrottle]

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        otp_code = request.data.get('otp')

        if not email or not otp_code:
            return Response({"detail": "Both email and OTP code are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({"detail": "User with this email does not exist."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_active:
            return Response({"detail": "Account is already verified and active."}, status=status.HTTP_400_BAD_REQUEST)

        # OTP validation helper se check karo
        is_valid, err_msg = validate_user_otp(user, otp_code)
        if not is_valid:
            return Response({"detail": err_msg}, status=status.HTTP_400_BAD_REQUEST)

        # User activate karo aur purane OTP records delete karo
        user.is_active = True
        user.save()
        user.otps.all().delete()

        # Automatic login ke liye JWT tokens generate karo
        refresh = RefreshToken.for_user(user)
        user_data = UserProfileSerializer(user, context={'request': request}).data

        return Response({
            'detail': 'Email verified successfully!',
            'user': user_data,
            'access': str(refresh.access_token),
            'refresh': str(refresh)
        }, status=status.HTTP_200_OK)


class ResendOTPView(APIView):
    """
    Naya verification OTP generate karke email bhejta hai.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPRequestRateThrottle]

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({"detail": "User with this email does not exist."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_active:
            return Response({"detail": "Account is already verified and active."}, status=status.HTTP_400_BAD_REQUEST)

        create_and_send_otp(user, purpose="verification")
        return Response({"detail": "New OTP code sent to your email."}, status=status.HTTP_200_OK)


class ForgotPasswordView(APIView):
    """
    Password reset ke liye user ke email par 6-digit OTP bhejta hai.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPRequestRateThrottle]

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({"detail": "User with this email does not exist."}, status=status.HTTP_404_NOT_FOUND)

        create_and_send_otp(user, purpose="password_reset")
        return Response({"detail": "Password reset OTP sent to your email."}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    """
    OTP verify karke naya password set karta hai.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAttemptRateThrottle]

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        otp_code = request.data.get('otp')
        new_password = request.data.get('new_password')

        if not email or not otp_code or not new_password:
            return Response({"detail": "Email, OTP, and new password are required."}, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 6:
            return Response({"detail": "Password must be at least 6 characters long."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({"detail": "User with this email does not exist."}, status=status.HTTP_404_NOT_FOUND)

        is_valid, err_msg = validate_user_otp(user, otp_code)
        if not is_valid:
            return Response({"detail": err_msg}, status=status.HTTP_400_BAD_REQUEST)

        # Naya password set karo aur account activate karo
        user.set_password(new_password)
        user.is_active = True
        user.save()
        user.otps.all().delete()

        return Response({"detail": "Password reset successfully! You can now log in with your new password."}, status=status.HTTP_200_OK)


# =====================================================================
# USER PROFILE & LEADERBOARD VIEWS
# =====================================================================

class ProfileView(generics.RetrieveUpdateAPIView):
    """
    Logged-in user apni profile view aur update kar sakta hai.
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class LeaderboardView(generics.ListAPIView):
    """
    Top 10 contributors (points aur uploads ke hisab se) return karta hai.
    Result ko 60 seconds ke liye cache karta hai taaki DB load kam ho.
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return (
            User.objects.exclude(role='admin')
            .exclude(is_staff=True)
            .exclude(is_superuser=True)
            .annotate(num_uploads=Count('uploaded_resources'))
            .filter(Q(points__gt=0) | Q(num_uploads__gt=0))
            .order_by('-points', '-num_uploads')[:10]
        )

    def list(self, request, *args, **kwargs):
        cached_data = cache.get('api_leaderboard_data')
        if cached_data is not None:
            return Response(cached_data)

        response = super().list(request, *args, **kwargs)
        cache.set('api_leaderboard_data', response.data, timeout=60)
        return response


class MyBookmarksView(generics.ListAPIView):
    """
    Current user ke bookmarked resources ki list return karta hai.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        from resources.serializers import ResourceSerializer
        return ResourceSerializer

    def get_queryset(self):
        return self.request.user.bookmarks.filter(status='approved')


# =====================================================================
# ADMIN & FACULTY MANAGEMENT VIEWS
# =====================================================================

class AdminUserListView(generics.ListAPIView):
    """
    Admin sabhi users ki list dekh sakta hai.
    """
    queryset = User.objects.all().order_by('username')
    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None


class AdminUserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    User detail view, update, ya delete karne ke liye (Role permissions ke sath).
    """
    queryset = User.objects.all()
    serializer_class = AdminUserSerializer

    def get_permissions(self):
        if self.request.method in ['GET', 'DELETE']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        viewer = request.user

        # Admin ya staff sabhi profiles dekh sakta hai
        if viewer.role == 'admin' or viewer.is_staff:
            return super().retrieve(request, *args, **kwargs)

        # Faculty apne university ke students ko dekh sakti hai
        if viewer.role == 'faculty' and instance.role == 'student' and instance.university == viewer.university:
            if not viewer.college or instance.college == viewer.college:
                return super().retrieve(request, *args, **kwargs)

        # User apni khud ki profile dekh sakta hai
        if instance == viewer:
            return super().retrieve(request, *args, **kwargs)

        raise PermissionDenied("You do not have permission to view this profile.")

    def perform_destroy(self, instance):
        viewer = self.request.user
        if instance == viewer:
            raise ValidationError("You cannot delete your own account.")

        if viewer.role == 'admin' or viewer.is_staff:
            instance.delete()
            return

        if viewer.role == 'faculty' and instance.role == 'student' and instance.university == viewer.university:
            if not viewer.college or instance.college == viewer.college:
                instance.delete()
                return

        raise PermissionDenied("You do not have permission to delete this user.")


class FacultyStudentListView(generics.ListAPIView):
    """
    Faculty ke liye unke university/college ke students ki list.
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if user.role != 'faculty':
            return User.objects.none()

        qs = User.objects.filter(role='student', university=user.university)
        if user.college:
            qs = qs.filter(college=user.college)
        return qs.order_by('username')


class RegisteredCollegesView(APIView):
    """
    System me registered unique colleges ki list return karta hai (cached).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        cached_colleges = cache.get('api_registered_colleges')
        if cached_colleges is not None:
            return Response(cached_colleges)

        colleges = sorted(list(set(User.objects.exclude(college='').values_list('college', flat=True).distinct())))
        cache.set('api_registered_colleges', colleges, timeout=300)
        return Response(colleges)


class RegisteredUniversitiesView(APIView):
    """
    System me registered unique universities ki list return karta hai (cached).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        cached_unis = cache.get('api_registered_unis')
        if cached_unis is not None:
            return Response(cached_unis)

        unis = sorted(list(set(User.objects.exclude(university='').values_list('university', flat=True).distinct())))
        cache.set('api_registered_unis', unis, timeout=300)
        return Response(unis)
