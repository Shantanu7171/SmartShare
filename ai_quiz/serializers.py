from rest_framework import serializers
from .models import GeneratedQuiz, QuizQuestion, QuizAttempt


class QuizQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizQuestion
        fields = [
            'id', 'question_text', 'option_a', 'option_b',
            'option_c', 'option_d', 'correct_answer', 'explanation'
        ]


class GeneratedQuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    attempts = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedQuiz
        fields = [
            'id', 'title', 'created_by', 'created_by_username',
            'resource', 'created_at', 'questions', 'attempts'
        ]
        read_only_fields = ['created_by', 'created_at']

    def get_attempts(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            attempts = QuizAttempt.objects.filter(quiz=obj, user=request.user)
            return QuizAttemptSerializer(attempts, many=True).data
        return []


class QuizAttemptSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'quiz', 'quiz_title', 'user', 'username',
            'score', 'total_questions', 'completed_at'
        ]
        read_only_fields = ['user', 'completed_at']
