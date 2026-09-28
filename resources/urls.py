from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ResourceViewSet

router = DefaultRouter()
router.register(r'', ResourceViewSet, basename='resource')

urlpatterns = [
    path('', include(router.urls)),
]
