from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import QuizViewSet, AttemptViewSet

router = DefaultRouter()
router.register(r'quizzes', QuizViewSet, basename='quiz')
router.register(r'attempts', AttemptViewSet, basename='attempt')

urlpatterns = [
    path('', include(router.urls)),
]
