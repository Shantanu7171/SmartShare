import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.core.cache import cache
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from resources.models import Resource
from reviews.models import Review
from ai_quiz.models import GeneratedQuiz
from core.throttling import ratelimit
from users.views import create_and_send_otp, validate_user_otp


# =====================================================================
# HELPER FUNCTIONS: AUTH & REQUEST PARSING
# =====================================================================

def get_tokens_for_user(user):
    """User ke liye JWT access aur refresh token banata hai."""
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def parse_request_input(request):
    """
    Request AJAX/JSON hai ya standard form POST, dono se data extract karta hai.
    Returns: (data_dict, is_ajax_bool)
    """
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.content_type == 'application/json' or
        request.POST.get('ajax') == 'true' or
        request.GET.get('ajax') == 'true'
    )

    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except Exception:
            data = {}
    else:
        data = request.POST

    return data, is_ajax


def set_jwt_cookies(response, tokens):
    """Response object me JWT tokens ko secure cookies ke roop me set karta hai."""
    response.set_cookie('jwt_access', tokens['access'], max_age=86400, httponly=False, samesite='Lax')
    response.set_cookie('jwt_refresh', tokens['refresh'], max_age=86400 * 7, httponly=False, samesite='Lax')
    return response


# =====================================================================
# 1. PUBLIC BROWSING VIEWS (HOME, FEED, RESOURCE DETAIL)
# =====================================================================

def home_view(request):
    """
    Landing page view:
    Trending notes, newly added notes, aur top contributors dikhata hai.
    Performance ke liye data 5 minutes (300s) ke liye cache hota hai.
    """
    data = cache.get('web_home_page_data')
    if not data:
        approved = Resource.objects.filter(status='approved').select_related('uploaded_by')
        trending_resources = list(approved.order_by('-downloads')[:6])
        new_resources = list(approved.order_by('-created_at')[:6])
        hero_resources = list(trending_resources[:3])
        top_contributors = list(
            User.objects.filter(is_active=True)
            .annotate(total_uploads=Count('uploaded_resources'))
            .order_by('-points')[:3]
        )

        data = {
            'trending_resources': trending_resources,
            'new_resources': new_resources,
            'hero_resources': hero_resources,
            'top_contributors': top_contributors,
        }
        cache.set('web_home_page_data', data, timeout=300)

    return render(request, 'home.html', data)


def feed_view(request):
    """
    Resource Feed / Dashboard:
    Branch, Semester, File Type aur Search Query ke hisab se notes filter karta hai.
    Results 12 per page paginate hote hain.
    """
    search_query = request.GET.get('search', '').strip()
    selected_branch = request.GET.get('branch', '').strip()
    selected_semester = request.GET.get('semester', '').strip()
    selected_file_type = request.GET.get('file_type', '').strip()
    ordering = request.GET.get('ordering', '-created_at')

    # Check if this is the default initial feed (cacheable)
    is_default_feed = (
        not search_query and not selected_branch and not selected_semester and
        not selected_file_type and request.GET.get('page', '1') == '1' and
        ordering == '-created_at'
    )

    if is_default_feed:
        cached_context = cache.get('feed_default_page_context')
        if cached_context:
            return render(request, 'dashboard.html', cached_context)

    # Filter approved resources
    resources = Resource.objects.filter(status='approved').select_related('uploaded_by').prefetch_related('bookmarked_by')

    if search_query:
        resources = resources.filter(
            Q(title__icontains=search_query) |
            Q(subject__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(tags__icontains=search_query) |
            Q(branch__icontains=search_query)
        )

    if selected_branch:
        resources = resources.filter(branch=selected_branch)

    if selected_semester and selected_semester.isdigit():
        resources = resources.filter(semester=int(selected_semester))

    if selected_file_type:
        resources = resources.filter(file_type=selected_file_type)

    # Ordering validation
    valid_orderings = ['-created_at', 'created_at', '-downloads', '-avg_rating']
    if ordering not in valid_orderings:
        ordering = '-created_at'
    resources = resources.order_by(ordering)

    # Pagination: 12 notes per page
    paginator = Paginator(resources, 12)
    page_number = request.GET.get('page', 1)
    resources_page = paginator.get_page(page_number)

    context = {
        'resources_page': resources_page,
        'search_query': search_query,
        'selected_branch': selected_branch,
        'selected_semester': selected_semester,
        'selected_file_type': selected_file_type,
        'ordering': ordering,
        'semesters_list': range(1, 9),
    }

    if is_default_feed:
        cache.set('feed_default_page_context', context, timeout=180)

    return render(request, 'dashboard.html', context)


def resource_detail_view(request, pk):
    """
    Ek specific resource ka detailed page: PDF preview, description, ratings, aur comments.
    """
    resource = get_object_or_404(
        Resource.objects.select_related('uploaded_by').prefetch_related('bookmarked_by'),
        pk=pk
    )
    reviews = resource.reviews.select_related('user').order_by('-created_at')

    return render(request, 'resource_detail.html', {
        'resource': resource,
        'reviews': reviews,
    })


@login_required
def submit_review_view(request, pk):
    """
    Resource par review aur star rating submit karta hai. User ko +2 points reward milta hai.
    """
    if request.method == 'POST':
        resource = get_object_or_404(Resource, pk=pk)
        try:
            rating = int(request.POST.get('rating', 5))
        except (ValueError, TypeError):
            rating = 5

        comment = request.POST.get('comment', '').strip()

        if comment:
            Review.objects.update_or_create(
                resource=resource,
                user=request.user,
                defaults={'rating': rating, 'comment': comment}
            )
            messages.success(request, "Your review was submitted! You earned +2 points.")
        else:
            messages.error(request, "Please enter a comment for your review.")

    return redirect('resource_detail', pk=pk)


# =====================================================================
# 2. UPLOAD & LEADERBOARD VIEWS
# =====================================================================

@login_required
@ratelimit(scope='upload', limit=20, timeout=3600)
def upload_view(request):
    """
    Study material (notes, question papers, syllabus) upload karne ka view.
    Upload hone par user ko +5 contributor points milte hain.
    """
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subject = request.POST.get('subject', '').strip()
        branch = request.POST.get('branch', '').strip()
        semester = request.POST.get('semester', '').strip()
        file_type = request.POST.get('file_type', 'other').strip()
        description = request.POST.get('description', '').strip()
        tags = request.POST.get('tags', '').strip()
        file = request.FILES.get('file')

        if not file or not branch or not semester or not title or not subject:
            messages.error(request, "Please fill in all required fields and choose a file.")
            return render(request, 'upload.html')

        try:
            resource = Resource.objects.create(
                title=title,
                subject=subject,
                branch=branch,
                semester=int(semester),
                file_type=file_type,
                description=description,
                tags=tags,
                file=file,
                uploaded_by=request.user,
                status='approved'  # Instant peer availability
            )

            # Contributor points reward
            request.user.points += 5
            request.user.save(update_fields=['points'])

            # Invalidate caches
            cache.delete('web_home_page_data')
            cache.delete('feed_default_page_context')
            cache.delete('web_leaderboard_leaders')

            messages.success(request, f"'{resource.title}' uploaded successfully! +5 contributor points awarded.")
            return redirect('feed')
        except Exception as e:
            messages.error(request, f"Upload error: {str(e)}")

    return render(request, 'upload.html')


def leaderboard_view(request):
    """
    Top 50 contributors ka leaderboard rank list dikhata hai.
    """
    leaders = cache.get('web_leaderboard_leaders')
    if not leaders:
        leaders = list(
            User.objects.filter(is_active=True)
            .annotate(total_uploads=Count('uploaded_resources'))
            .order_by('-points')[:50]
        )
        cache.set('web_leaderboard_leaders', leaders, timeout=300)

    return render(request, 'leaderboard.html', {'leaders': leaders})


# =====================================================================
# 3. PROFILE & CHAT & QUIZ VIEWS
# =====================================================================

@login_required
def profile_view(request):
    """
    Current logged-in user ki profile: User ke uploads aur saved bookmarks dikhata hai.
    """
    my_uploads = list(Resource.objects.filter(uploaded_by=request.user).select_related('uploaded_by').order_by('-created_at'))
    my_bookmarks = list(request.user.bookmarks.all().select_related('uploaded_by').order_by('-created_at'))

    context = {
        'my_uploads': my_uploads,
        'my_bookmarks': my_bookmarks,
    }

    if request.user.role == 'admin' or request.user.is_superuser:
        context['pending_count'] = Resource.objects.filter(status='pending').count()
        context['total_resources_count'] = Resource.objects.count()
        context['total_users_count'] = User.objects.count()

    return render(request, 'profile.html', context)


@login_required
def update_profile_view(request):
    """
    User apni basic details (bio, branch, sem, college, avatar) update kar sakta hai.
    """
    if request.method == 'POST':
        user = request.user
        user.bio = request.POST.get('bio', user.bio)
        user.branch = request.POST.get('branch', user.branch)

        semester_val = request.POST.get('semester')
        if semester_val and semester_val.isdigit():
            user.semester = int(semester_val)

        user.college = request.POST.get('college', user.college)
        user.university = request.POST.get('university', user.university)

        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']

        user.save()
        messages.success(request, "Your profile was updated successfully.")

    return redirect('profile')


@login_required
def user_profile_view(request, pk):
    """
    Kisi doosre user ki public profile aur uske uploaded resources dekhne ke liye.
    """
    target_user = get_object_or_404(User, pk=pk)
    user_resources = Resource.objects.filter(uploaded_by=target_user, status='approved')
    viewer = request.user

    can_moderate = (
        viewer.role == 'admin' or
        (viewer.role == 'faculty' and target_user.role == 'student' and target_user.university == viewer.university)
    ) and viewer.id != target_user.id

    return render(request, 'user_profile.html', {
        'target_user': target_user,
        'user_resources': user_resources,
        'can_moderate': can_moderate,
    })


@login_required
def chat_view(request):
    """Peer Lounge AI Chatbot interface."""
    return render(request, 'chat.html')


@login_required
def ai_quiz_view(request):
    """AI Quiz generator aur user ke created quizzes ki list."""
    quizzes = GeneratedQuiz.objects.filter(created_by=request.user).order_by('-created_at')
    available_resources = Resource.objects.filter(status='approved')
    return render(request, 'ai_quiz.html', {
        'quizzes': quizzes,
        'available_resources': available_resources,
    })


# =====================================================================
# 4. ADMIN & FACULTY MODERATION PANELS
# =====================================================================

@login_required
def admin_panel_view(request):
    """Admin Dashboard: Pending materials, sabhi resources, aur users list."""
    if request.user.role != 'admin' and not request.user.is_superuser:
        messages.error(request, "Access restricted to administrators.")
        return redirect('feed')

    pending_resources = list(Resource.objects.filter(status='pending').select_related('uploaded_by').order_by('-created_at'))
    all_resources = list(Resource.objects.all().select_related('uploaded_by').order_by('-created_at'))
    users_list = list(User.objects.all().order_by('-date_joined'))

    return render(request, 'admin_panel.html', {
        'pending_resources': pending_resources,
        'all_resources': all_resources,
        'users_list': users_list,
        'pending_count': len(pending_resources),
        'all_count': len(all_resources),
        'users_count': len(users_list),
    })


@login_required
def admin_approve_resource_view(request, pk):
    """Admin resource ko approve ya reject karta hai (+10 points on approval)."""
    if request.user.role != 'admin' and not request.user.is_superuser:
        return redirect('feed')

    if request.method == 'POST':
        resource = get_object_or_404(Resource, pk=pk)
        new_status = request.POST.get('status', 'approved')
        resource.status = new_status
        resource.save(update_fields=['status'])

        cache.delete('web_home_page_data')
        cache.delete('feed_default_page_context')

        if new_status == 'approved':
            resource.uploaded_by.points += 10
            resource.uploaded_by.save(update_fields=['points'])
            messages.success(request, f"Resource '{resource.title}' approved! +10 points awarded.")
        else:
            messages.info(request, f"Resource '{resource.title}' rejected.")

    return redirect('admin_panel')


@login_required
def admin_delete_resource_view(request, pk):
    """Admin kisi resource ko permanently delete karta hai."""
    if request.user.role != 'admin' and not request.user.is_superuser:
        return redirect('feed')

    if request.method == 'POST':
        resource = Resource.objects.filter(pk=pk).first()
        if resource:
            resource.delete()
            cache.delete('web_home_page_data')
            cache.delete('feed_default_page_context')
            messages.success(request, "Resource permanently deleted.")
        else:
            messages.warning(request, "Resource not found.")

    return redirect('admin_panel')


@login_required
def admin_update_user_role_view(request, pk):
    """Admin user ka role (Student / Faculty / Admin) aur University change kar sakta hai."""
    if request.user.role != 'admin' and not request.user.is_superuser:
        return redirect('feed')

    if request.method == 'POST':
        target_user = get_object_or_404(User, pk=pk)
        new_role = request.POST.get('role')
        university = request.POST.get('university', '').strip()
        college = request.POST.get('college', '').strip()

        if new_role in ['student', 'faculty', 'admin']:
            target_user.role = new_role
            target_user.is_staff = (new_role == 'admin')
            if new_role == 'faculty':
                target_user.is_approved_faculty = True

            if university:
                target_user.university = university
            if college:
                target_user.college = college

            target_user.save()
            messages.success(request, f"User '{target_user.username}' updated to {new_role}.")

    return redirect('admin_panel')


@login_required
def delete_user_admin_view(request, pk):
    """Admin ya Faculty kisi user/student ko delete kar sakte hain."""
    viewer = request.user
    target_user = User.objects.filter(pk=pk).first()

    redirect_target = 'admin_panel' if (viewer.role == 'admin' or viewer.is_superuser) else 'faculty_panel'

    if not target_user:
        messages.warning(request, "This user no longer exists.")
        return redirect(redirect_target)

    # Faculty can only delete students of their own university
    can_delete = (
        viewer.role == 'admin' or
        viewer.is_superuser or
        (viewer.role == 'faculty' and target_user.role == 'student' and viewer.university and target_user.university == viewer.university)
    ) and viewer.id != target_user.id

    if not can_delete:
        messages.error(request, "Permission denied.")
        return redirect('feed')

    if request.method == 'POST':
        uname = target_user.username
        target_user.delete()
        messages.success(request, f"User '{uname}' removed successfully.")

    return redirect(redirect_target)


@login_required
def faculty_panel_view(request):
    """Faculty portal: Faculty apni university ke resources aur students ko moderate kar sakti hai."""
    if request.user.role != 'faculty':
        messages.error(request, "Access restricted to faculty members.")
        return redirect('feed')

    university = request.user.university
    if not university:
        messages.warning(request, "No university assigned to your profile. Please contact an admin.")
        university_resources = []
        students_list = []
    else:
        university_resources = list(Resource.objects.filter(uploaded_by__university=university).select_related('uploaded_by').order_by('-created_at'))
        students_list = list(User.objects.filter(university=university, role='student').order_by('-points'))

    return render(request, 'faculty_panel.html', {
        'university': university,
        'university_resources': university_resources,
        'students_list': students_list,
    })


@login_required
def faculty_approve_resource_view(request, pk):
    """Faculty member apni university ke resource ko approve/reject karta hai."""
    if request.user.role != 'faculty':
        return redirect('feed')

    if request.method == 'POST':
        resource = get_object_or_404(Resource, pk=pk)
        if not request.user.university or resource.uploaded_by.university != request.user.university:
            messages.error(request, "Permission denied: You can only moderate resources from your own university.")
            return redirect('faculty_panel')

        status_val = request.POST.get('status', 'approved')
        resource.status = status_val
        resource.save(update_fields=['status'])
        messages.success(request, f"Submission updated to {status_val}.")

    return redirect('faculty_panel')


@login_required
def faculty_delete_resource_view(request, pk):
    """Faculty member apni university ke resource ko delete karta hai."""
    if request.user.role != 'faculty':
        return redirect('feed')

    if request.method == 'POST':
        resource = Resource.objects.filter(pk=pk).first()
        if not resource:
            messages.warning(request, "Resource no longer exists.")
            return redirect('faculty_panel')

        if not request.user.university or resource.uploaded_by.university != request.user.university:
            messages.error(request, "Permission denied: You can only delete resources from your own university.")
            return redirect('faculty_panel')

        title = resource.title
        resource.delete()
        messages.success(request, f"Resource '{title}' deleted successfully.")

    return redirect('faculty_panel')


# =====================================================================
# 5. AUTHENTICATION & OTP WEB FLOWS (LOGIN, SIGNUP, VERIFY, RESET)
# =====================================================================

@ratelimit(scope='login', limit=5, timeout=60)
def login_view(request):
    """User Sign In: Form submit aur AJAX/JSON login dono support karta hai."""
    if request.user.is_authenticated:
        return redirect('feed')

    if request.method == 'POST':
        data, is_ajax = parse_request_input(request)
        identifier = data.get('email', '').strip() or data.get('username', '').strip()
        password = data.get('password', '')

        if not identifier or not password:
            msg = "Please provide both username/email and password."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'login.html')

        user = authenticate(request, username=identifier, password=password)
        if user is not None:
            # Agar user ne abhi tak email verify nahi kiya hai:
            if not user.is_active:
                msg = "This account is inactive. Please verify your email first."
                request.session['pending_verification_email'] = user.email
                if is_ajax:
                    return JsonResponse({
                        'status': 'unverified',
                        'detail': msg,
                        'email': user.email,
                        'redirect_url': f'/verify-otp/?email={user.email}'
                    }, status=403)
                messages.warning(request, msg)
                return redirect(f'/verify-otp/?email={user.email}')

            # User authenticated: Login and issue JWT tokens
            login(request, user, backend='users.backends.EmailOrUsernameModelBackend')
            tokens = get_tokens_for_user(user)

            if is_ajax:
                res = JsonResponse({
                    'status': 'success',
                    'detail': f'Welcome back, {user.username}!',
                    'access': tokens['access'],
                    'refresh': tokens['refresh'],
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'role': user.role,
                        'points': user.points,
                    },
                    'redirect_url': '/feed/'
                })
                return set_jwt_cookies(res, tokens)

            messages.success(request, f"Welcome back, {user.username}!")
            res = redirect('feed')
            return set_jwt_cookies(res, tokens)

        else:
            msg = "Invalid username/email or password."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=401)
            messages.error(request, msg)

    return render(request, 'login.html')


@ratelimit(scope='register', limit=5, timeout=60)
def register_view(request):
    """User Registration: Naya student account banata hai aur verification OTP email bhejta hai."""
    if request.user.is_authenticated:
        return redirect('feed')

    if request.method == 'POST':
        data, is_ajax = parse_request_input(request)

        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        password2 = data.get('password2', '')
        branch = data.get('branch', '').strip()
        semester = data.get('semester')
        college = data.get('college', '').strip()
        university = data.get('university', '').strip()

        # Input validations
        if not email or not username or not password:
            msg = "Email, username, and password are required."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'signup.html')

        if not branch or not semester:
            msg = "Please select your Department/Branch and Semester."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'signup.html')

        if password != password2:
            msg = "Passwords do not match."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'signup.html')

        if len(password) < 6:
            msg = "Password must be at least 6 characters long."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'signup.html')

        # Clean unverified accounts with same email or username
        User.objects.filter(email__iexact=email, is_active=False).delete()
        User.objects.filter(username=username, is_active=False).delete()

        if User.objects.filter(email__iexact=email, is_active=True).exists():
            msg = "An active account with this email already exists."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'signup.html')

        if User.objects.filter(username__iexact=username, is_active=True).exists():
            msg = "Username is already taken."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'signup.html')

        try:
            sem_int = int(semester) if (semester and str(semester).isdigit()) else None
            user = User.objects.create_user(
                email=email,
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role='student',
                branch=branch,
                semester=sem_int,
                college=college,
                university=university,
                is_active=False,  # OTP verification hone tak inactive rahega
            )

            # OTP generate karke email bhejo
            create_and_send_otp(user, purpose="verification")
            request.session['pending_verification_email'] = user.email

            msg = f"Account registered! We have sent a 6-digit verification code to {user.email}."
            if is_ajax:
                return JsonResponse({
                    'status': 'otp_sent',
                    'detail': msg,
                    'email': user.email,
                    'redirect_url': f'/verify-otp/?email={user.email}'
                }, status=201)

            messages.success(request, msg)
            return redirect(f'/verify-otp/?email={user.email}')

        except Exception as e:
            msg = f"Registration failed: {str(e)}"
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=500)
            messages.error(request, msg)

    return render(request, 'signup.html')


@ratelimit(scope='verify_otp', limit=5, timeout=60)
def verify_otp_view(request):
    """User ke email verification OTP ko verify karke account activate karta hai."""
    if request.user.is_authenticated:
        return redirect('feed')

    email = request.GET.get('email', '').strip() or request.session.get('pending_verification_email', '')

    if request.method == 'POST':
        data, is_ajax = parse_request_input(request)
        email = data.get('email', '').strip() or email
        otp_code = data.get('otp', '').strip()

        if not email or not otp_code:
            msg = "Both email and OTP code are required."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'verify_otp.html', {'email': email})

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            msg = "No account found with this email address."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=404)
            messages.error(request, msg)
            return render(request, 'verify_otp.html', {'email': email})

        if user.is_active:
            msg = "Your email is already verified. You can sign in now."
            if is_ajax:
                return JsonResponse({'status': 'success', 'detail': msg, 'redirect_url': '/login/'}, status=200)
            messages.info(request, msg)
            return redirect('login')

        is_valid, err_msg = validate_user_otp(user, otp_code)
        if not is_valid:
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': err_msg}, status=400)
            messages.error(request, err_msg)
            return render(request, 'verify_otp.html', {'email': email})

        # OTP verified successfully!
        user.is_active = True
        user.save()
        user.otps.all().delete()
        request.session.pop('pending_verification_email', None)

        login(request, user, backend='users.backends.EmailOrUsernameModelBackend')
        tokens = get_tokens_for_user(user)

        success_msg = f"Email verified successfully! Welcome to SmartShare, {user.username}."
        if is_ajax:
            res = JsonResponse({
                'status': 'success',
                'detail': success_msg,
                'access': tokens['access'],
                'refresh': tokens['refresh'],
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': user.role,
                    'points': user.points,
                },
                'redirect_url': '/feed/'
            })
            return set_jwt_cookies(res, tokens)

        messages.success(request, success_msg)
        res = redirect('feed')
        return set_jwt_cookies(res, tokens)

    return render(request, 'verify_otp.html', {'email': email})


@ratelimit(scope='resend_otp', limit=3, timeout=60)
def resend_otp_view(request):
    """User ke email par naya verification OTP resend karta hai."""
    data, is_ajax = parse_request_input(request) if request.method == 'POST' else ({}, request.GET.get('ajax') == 'true')
    email = data.get('email', '').strip() if request.method == 'POST' else request.GET.get('email', '').strip()

    if not email:
        email = request.session.get('pending_verification_email', '')

    if not email:
        msg = "Email address is required."
        if is_ajax:
            return JsonResponse({'status': 'error', 'detail': msg}, status=400)
        messages.error(request, msg)
        return redirect('signup')

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        msg = "No account found with this email."
        if is_ajax:
            return JsonResponse({'status': 'error', 'detail': msg}, status=404)
        messages.error(request, msg)
        return redirect('signup')

    if user.is_active:
        msg = "Account is already verified. Please sign in."
        if is_ajax:
            return JsonResponse({'status': 'info', 'detail': msg, 'redirect_url': '/login/'}, status=200)
        messages.info(request, msg)
        return redirect('login')

    create_and_send_otp(user, purpose="verification")
    msg = f"A fresh OTP code has been sent to {user.email}."

    if is_ajax:
        return JsonResponse({'status': 'success', 'detail': msg})

    messages.success(request, msg)
    return redirect(f'/verify-otp/?email={user.email}')


def logout_view(request):
    """User ko safely sign out karta hai aur session + cookies delete karta hai."""
    logout(request)
    messages.info(request, "You have been securely signed out.")
    response = redirect('login')
    response.delete_cookie('jwt_access')
    response.delete_cookie('jwt_refresh')
    return response


@ratelimit(scope='forgot_password', limit=3, timeout=60)
def forgot_password_view(request):
    """Password reset request: User ke email par reset OTP bhejta hai."""
    if request.user.is_authenticated:
        return redirect('feed')

    email = request.GET.get('email', '').strip()

    if request.method == 'POST':
        data, is_ajax = parse_request_input(request)
        email = data.get('email', '').strip() or email

        if not email:
            msg = "Email address is required."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'forgot_password.html', {'email': email})

        try:
            user = User.objects.get(email__iexact=email)
            create_and_send_otp(user, purpose="password_reset")
        except User.DoesNotExist:
            msg = "No account found with this email address."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=404)
            messages.error(request, msg)
            return render(request, 'forgot_password.html', {'email': email})

        msg = f"Password reset OTP has been sent to {user.email}."
        if is_ajax:
            return JsonResponse({
                'status': 'success',
                'detail': msg,
                'email': user.email,
                'redirect_url': f'/reset-password/?email={user.email}'
            })

        messages.success(request, msg)
        return redirect(f'/reset-password/?email={user.email}')

    return render(request, 'forgot_password.html', {'email': email})


@ratelimit(scope='reset_password', limit=5, timeout=60)
def reset_password_view(request):
    """OTP verify karke naya password set karta hai."""
    if request.user.is_authenticated:
        return redirect('feed')

    email = request.GET.get('email', '').strip()

    if request.method == 'POST':
        data, is_ajax = parse_request_input(request)
        email = data.get('email', '').strip() or email
        otp_code = data.get('otp', '').strip()
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')

        if not email or not otp_code or not new_password:
            msg = "Email, OTP code, and new password are required."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'reset_password.html', {'email': email})

        if new_password != confirm_password:
            msg = "Passwords do not match."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'reset_password.html', {'email': email})

        if len(new_password) < 6:
            msg = "Password must be at least 6 characters long."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'reset_password.html', {'email': email})

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            msg = "No account found with this email address."
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': msg}, status=404)
            messages.error(request, msg)
            return render(request, 'reset_password.html', {'email': email})

        is_valid, err_msg = validate_user_otp(user, otp_code)
        if not is_valid:
            if is_ajax:
                return JsonResponse({'status': 'error', 'detail': err_msg}, status=400)
            messages.error(request, err_msg)
            return render(request, 'reset_password.html', {'email': email})

        # Set new password
        user.set_password(new_password)
        user.is_active = True
        user.save()
        user.otps.all().delete()

        msg = "Password reset successfully! You can now log in with your new password."
        if is_ajax:
            return JsonResponse({'status': 'success', 'detail': msg, 'redirect_url': '/login/'})

        messages.success(request, msg)
        return redirect('login')

    return render(request, 'reset_password.html', {'email': email})
