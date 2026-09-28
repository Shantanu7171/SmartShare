from rest_framework import serializers
from users.serializers import UserProfileSerializer
from .models import ChatMessage

class ChatMessageSerializer(serializers.ModelSerializer):
    user = UserProfileSerializer(read_only=True)

    class Meta:
        model = ChatMessage
        fields = ['id', 'user', 'message', 'is_bot', 'created_at']
        read_only_fields = ['id', 'user', 'is_bot', 'created_at']
