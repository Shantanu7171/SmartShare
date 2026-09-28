from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    total_uploads = serializers.SerializerMethodField()
    total_downloads = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'role', 'branch', 
            'semester', 'avatar', 'bio', 'points', 'university', 'college', 
            'is_approved_faculty', 'total_uploads', 'total_downloads'
        ]
        read_only_fields = ['id', 'username', 'email', 'role', 'points', 'is_approved_faculty', 'total_uploads', 'total_downloads']

    def get_total_uploads(self, obj):
        # Count related resources uploaded by this user
        return obj.uploaded_resources.count()

    def get_total_downloads(self, obj):
        from django.db.models import Sum
        return obj.uploaded_resources.aggregate(Sum('downloads'))['downloads__sum'] or 0

    def update(self, instance, validated_data):
        if instance.role == 'admin':
            validated_data['branch'] = None
            validated_data['semester'] = None
        return super().update(instance, validated_data)


class AdminUserSerializer(serializers.ModelSerializer):
    total_uploads = serializers.SerializerMethodField()
    total_downloads = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'role', 'branch', 
            'semester', 'avatar', 'bio', 'points', 'university', 'college', 
            'is_approved_faculty', 'total_uploads', 'total_downloads'
        ]
        read_only_fields = ['id', 'username', 'email', 'total_uploads', 'total_downloads']

    def get_total_uploads(self, obj):
        return obj.uploaded_resources.count()

    def get_total_downloads(self, obj):
        from django.db.models import Sum
        return obj.uploaded_resources.aggregate(Sum('downloads'))['downloads__sum'] or 0

    def update(self, instance, validated_data):
        role = validated_data.get('role', instance.role)
        if role == 'admin':
            validated_data['branch'] = None
            validated_data['semester'] = None
            if not instance.is_superuser:
                instance.is_staff = True
        elif role == 'faculty':
            validated_data['semester'] = None
            validated_data['is_approved_faculty'] = True
            if not instance.is_superuser:
                instance.is_staff = False
        else:
            if not instance.is_superuser:
                instance.is_staff = False
        return super().update(instance, validated_data)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    password2 = serializers.CharField(write_only=True, min_length=6)
    first_name = serializers.CharField(write_only=True, required=True)
    last_name = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password', 'password2', 'role', 'branch', 'semester', 'university', 'college']
        extra_kwargs = {
            'username': {'required': False, 'read_only': True}
        }

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError({"password2": "Passwords must match."})
        # Enforce student-only self-registration; Admin assigns faculty role
        data['role'] = 'student'
        
        # Auto-generate a unique username
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        
        import re
        base_username = re.sub(r'[^a-zA-Z0-9_]', '', f"{first_name}_{last_name}".lower())
        if not base_username:
            base_username = "user"
            
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1
            
        data['username'] = username
        return data

    def create(self, validated_data):
        import random
        from django.core.mail import send_mail
        from django.conf import settings
        from .models import EmailOTP

        validated_data.pop('password2')
        role = validated_data.get('role', 'student')
        branch = None if role == 'admin' else validated_data.get('branch')
        semester = None if role in ['admin', 'faculty'] else validated_data.get('semester')
        is_staff = True if role == 'admin' else False

        user = User.objects.create_user(
            email=validated_data['email'],
            username=validated_data['username'],
            password=validated_data['password'],
            role=role,
            branch=branch,
            semester=semester,
            university=validated_data.get('university', ''),
            college=validated_data.get('college', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            is_staff=is_staff,
            is_active=False
        )

        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        EmailOTP.objects.create(user=user, otp_code=otp_code)

        # Send OTP code via helper function
        from .views import send_otp_email_async
        send_otp_email_async(user, otp_code, purpose="verification")

        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(required=False)
    username = serializers.CharField(required=False)
    password = serializers.CharField(write_only=True)
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = UserProfileSerializer(read_only=True)

    def validate(self, data):
        lookup = data.get('email') or data.get('username')
        password = data.get('password')

        if not lookup or not password:
            raise serializers.ValidationError("Both username/email and password are required.")

        from django.db.models import Q
        user_obj = User.objects.filter(Q(email__iexact=lookup) | Q(username__iexact=lookup)).first()
        if user_obj and user_obj.check_password(password) and not user_obj.is_active:
            raise serializers.ValidationError("User account is inactive. Please verify your email first.")

        user = authenticate(username=lookup, password=password)
        if not user:
            raise serializers.ValidationError("Invalid credentials. Please check your username/email and password.")

        refresh = RefreshToken.for_user(user)

        return {
            'user': user,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
