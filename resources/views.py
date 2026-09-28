from django.db.models import Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Resource
from .serializers import ResourceSerializer
from core.throttling import ResourceUploadRateThrottle


class ResourceViewSet(viewsets.ModelViewSet):
    """
    Study Materials (Notes, Question Papers, Books) ke liye ViewSet.
    Search, filter, upload, download, bookmark, aur moderation support karta hai.
    """
    queryset = Resource.objects.all()
    serializer_class = ResourceSerializer
    filterset_fields = ['branch', 'semester', 'subject', 'file_type', 'status', 'uploaded_by', 'uploaded_by__university', 'uploaded_by__college']
    search_fields = ['title', 'description', 'subject', 'tags']
    ordering_fields = ['created_at', 'downloads', 'avg_rating']

    def get_throttles(self):
        """Upload spam rokne ke liye create action par rate limit lagata hai."""
        if self.action in ['create']:
            return [ResourceUploadRateThrottle()]
        return super().get_throttles()

    def get_permissions(self):
        """Browse aur download sabhi kar sakte hain, upload aur manage ke liye login zaroori hai."""
        if self.action in ['list', 'retrieve', 'download']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Role-based access filtering:
        - Admin: Sabhi resources dekh sakta hai (approved, pending, rejected).
        - Faculty: Approved notes + apne uploads + apni university ke notes dekh sakti hai.
        - Students / Public: Sirf 'approved' resources aur apne khud ke uploads dekh sakte hain.
        """
        user = self.request.user
        base_qs = Resource.objects.select_related('uploaded_by').prefetch_related('bookmarked_by')

        if user and user.is_authenticated:
            if user.role == 'admin' or user.is_staff:
                return base_qs.all()

            if user.role == 'faculty':
                return base_qs.filter(
                    Q(status='approved') |
                    Q(uploaded_by=user) |
                    Q(uploaded_by__university=user.university)
                )

            return base_qs.filter(Q(status='approved') | Q(uploaded_by=user))

        return base_qs.filter(status='approved')

    def perform_create(self, serializer):
        """Resource save karta hai aur contributor ko +10 points award karta hai."""
        serializer.save(uploaded_by=self.request.user, status='approved')

        uploader = self.request.user
        uploader.points += 10
        uploader.save(update_fields=['points'])

    def destroy(self, request, *args, **kwargs):
        """
        Resource delete karta hai:
        - Uploader, Admin, ya matching University ka Faculty hi delete kar sakta hai.
        - Agar approved note tha, toh uploader ke 10 points deduct hote hain.
        """
        resource = self.get_object()
        user = request.user
        is_faculty_for_uploader = (
            user.role == 'faculty' and
            user.university and
            user.university == resource.uploaded_by.university
        )

        if resource.uploaded_by != user and not (user.role == 'admin' or user.is_staff or is_faculty_for_uploader):
            return Response({'detail': 'You do not have permission to delete this resource.'}, status=status.HTTP_403_FORBIDDEN)

        if resource.status == 'approved':
            uploader = resource.uploaded_by
            uploader.points = max(0, uploader.points - 10)
            uploader.save(update_fields=['points'])

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def bookmark(self, request, pk=None):
        """Resource ko bookmark ya unbookmark (toggle) karta hai."""
        resource = self.get_object()
        if resource.bookmarked_by.filter(id=request.user.id).exists():
            resource.bookmarked_by.remove(request.user)
            bookmarked = False
        else:
            resource.bookmarked_by.add(request.user)
            bookmarked = True
        return Response({'bookmarked': bookmarked}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[permissions.AllowAny])
    def download(self, request, pk=None):
        """Download counter badhata hai (+1) aur file ka download URL return karta hai."""
        resource = self.get_object()
        resource.downloads += 1
        resource.save(update_fields=['downloads'])

        file_url = resource.file.url
        if not file_url.startswith('http'):
            file_url = request.build_absolute_uri(file_url)

        return Response({'download_url': file_url}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], permission_classes=[permissions.IsAuthenticated])
    def approve(self, request, pk=None):
        """
        Resource ko approve ya reject karta hai (Admin ya University Faculty).
        Approve hone par uploader ko +10 points award karta hai.
        """
        user = request.user
        resource = self.get_object()

        is_faculty_for_uploader = (
            user.role == 'faculty' and
            user.university and
            user.university == resource.uploaded_by.university
        )
        if not (user.role == 'admin' or user.is_staff or is_faculty_for_uploader):
            return Response({'detail': 'You do not have permission to approve resources.'}, status=status.HTTP_403_FORBIDDEN)

        status_val = request.data.get('status')
        if status_val not in ['approved', 'rejected', 'pending']:
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        old_status = resource.status
        resource.status = status_val
        resource.save(update_fields=['status'])

        points_awarded = False
        if status_val == 'approved' and old_status != 'approved':
            uploader = resource.uploaded_by
            uploader.points += 10
            uploader.save(update_fields=['points'])
            points_awarded = True

        return Response({
            'status': resource.status,
            'points_awarded': points_awarded
        }, status=status.HTTP_200_OK)
