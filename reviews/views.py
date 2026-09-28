from rest_framework import permissions, viewsets
from .models import Review
from .serializers import ReviewSerializer


class ReviewViewSet(viewsets.ModelViewSet):
    """
    Study materials ke reviews aur ratings ke liye ViewSet.
    """
    serializer_class = ReviewSerializer

    def get_permissions(self):
        """Reviews sabhi log dekh sakte hain, par review submit karne ke liye login zaroori hai."""
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """Resource ID ke according reviews filter karke newest-first return karta hai."""
        queryset = Review.objects.all()
        resource_id = self.request.query_params.get('resource')
        if resource_id:
            queryset = queryset.filter(resource_id=resource_id)
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        """Review create karte waqt logged-in user ko associate karta hai."""
        serializer.save(user=self.request.user)
