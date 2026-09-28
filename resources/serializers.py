from rest_framework import serializers

from users.serializers import UserProfileSerializer
from .models import Resource


class ResourceSerializer(serializers.ModelSerializer):
    uploaded_by = UserProfileSerializer(read_only=True)
    is_bookmarked = serializers.SerializerMethodField()
    tags_list = serializers.SerializerMethodField()

    class Meta:
        model = Resource
        fields = [
            'id', 'title', 'description', 'file', 'file_type',
            'subject', 'branch', 'semester', 'tags', 'uploaded_by',
            'downloads', 'avg_rating', 'status', 'created_at',
            'is_bookmarked', 'tags_list'
        ]
        read_only_fields = ['id', 'uploaded_by', 'downloads', 'avg_rating', 'status', 'created_at']

    def get_is_bookmarked(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return obj.bookmarked_by.filter(id=request.user.id).exists()
        return False

    def get_tags_list(self, obj):
        if obj.tags:
            return [tag.strip() for tag in obj.tags.split(',') if tag.strip()]
        return []
