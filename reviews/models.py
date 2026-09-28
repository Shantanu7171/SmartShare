from django.conf import settings
from django.db import models
from django.db.models import Avg


class Review(models.Model):
    resource = models.ForeignKey(
        'resources.Resource',
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    rating = models.IntegerField()
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('resource', 'user')

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Recalculate resource average rating
        avg = self.resource.reviews.aggregate(Avg('rating'))['rating__avg']
        self.resource.avg_rating = avg or 0.0
        self.resource.save(update_fields=['avg_rating'])

        # Give user who reviewed +2 points (only on creation)
        if is_new:
            self.user.points += 2
            self.user.save(update_fields=['points'])

    def __str__(self):
        return f"{self.user.username}'s review on {self.resource.title} - {self.rating} stars"
