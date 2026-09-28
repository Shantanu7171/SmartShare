from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse
from core import web_views

def health_check(request):
    return JsonResponse({"status": "healthy"})

urlpatterns = [
    # Health check
    path('health/', health_check, name='health_check'),

    # Django Admin
    path('admin/', admin.site.urls),

    # Web Template Views (Server-rendered Jinja/Django frontend)
    path('', web_views.home_view, name='home'),
    path('dashboard/', web_views.feed_view, name='dashboard'),
    path('feed/', web_views.feed_view, name='feed'),
    path('resources/<int:pk>/', web_views.resource_detail_view, name='resource_detail'),
    path('resources/<int:pk>/review/', web_views.submit_review_view, name='submit_review'),
    path('upload/', web_views.upload_view, name='upload'),
    path('leaderboard/', web_views.leaderboard_view, name='leaderboard'),
    path('profile/', web_views.profile_view, name='profile'),
    path('profile/update/', web_views.update_profile_view, name='update_profile'),
    path('user-profile/<int:pk>/', web_views.user_profile_view, name='user_profile'),
    path('chat/', web_views.chat_view, name='chat'),
    path('ai-quiz/', web_views.ai_quiz_view, name='ai_quiz'),

    # Admin and Faculty Moderation Panels
    path('admin-panel/', web_views.admin_panel_view, name='admin_panel'),
    path('admin-panel/resource/<int:pk>/approve/', web_views.admin_approve_resource_view, name='admin_approve_resource'),
    path('admin-panel/resource/<int:pk>/delete/', web_views.admin_delete_resource_view, name='admin_delete_resource'),
    path('admin-panel/user/<int:pk>/role/', web_views.admin_update_user_role_view, name='admin_update_user_role'),
    path('admin-panel/user/<int:pk>/delete/', web_views.delete_user_admin_view, name='delete_user_admin'),
    path('faculty-panel/', web_views.faculty_panel_view, name='faculty_panel'),
    path('faculty-panel/resource/<int:pk>/approve/', web_views.faculty_approve_resource_view, name='faculty_approve_resource'),
    path('faculty-panel/resource/<int:pk>/delete/', web_views.faculty_delete_resource_view, name='faculty_delete_resource'),

    # Authentication Pages
    path('login/', web_views.login_view, name='login'),
    path('signup/', web_views.register_view, name='signup'),
    path('register/', web_views.register_view, name='register'),
    path('verify-otp/', web_views.verify_otp_view, name='verify_otp_web'),
    path('resend-otp/', web_views.resend_otp_view, name='resend_otp_web'),
    path('forgot-password/', web_views.forgot_password_view, name='forgot_password_web'),
    path('reset-password/', web_views.reset_password_view, name='reset_password_web'),
    path('logout/', web_views.logout_view, name='logout'),

    # Existing DRF REST APIs (Preserved 100%)
    path('api/auth/', include('users.urls')),
    path('api/resources/', include('resources.urls')),
    path('api/reviews/', include('reviews.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/ai/', include('ai_quiz.urls')),
]

# Serve media and static files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
