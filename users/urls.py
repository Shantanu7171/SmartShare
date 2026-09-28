from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LeaderboardView,
    LoginView,
    MyBookmarksView,
    ProfileView,
    RegisterView,
    AdminUserDetailView,
    AdminUserListView,
    RegisteredCollegesView,
    RegisteredUniversitiesView,
    FacultyStudentListView,
    VerifyOTPView,
    ResendOTPView,
    ForgotPasswordView,
    ResetPasswordView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='api_register'),
    path('login/', LoginView.as_view(), name='api_login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('profile/', ProfileView.as_view(), name='api_profile'),
    path('leaderboard/', LeaderboardView.as_view(), name='api_leaderboard'),
    path('bookmarks/', MyBookmarksView.as_view(), name='bookmarks'),
    path('users/', AdminUserListView.as_view(), name='admin_user_list'),
    path('users/<int:pk>/', AdminUserDetailView.as_view(), name='admin_user_detail'),
    path('colleges/', RegisteredCollegesView.as_view(), name='colleges'),
    path('universities/', RegisteredUniversitiesView.as_view(), name='universities'),
    path('students/', FacultyStudentListView.as_view(), name='faculty_students'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify_otp'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend_otp'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset_password'),
]
