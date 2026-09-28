from django.conf import settings
from django.db import models


class Resource(models.Model):
    BRANCH_CHOICES = (
        ('CSE', 'Computer Science and Engineering'),
        ('IT', 'Information Technology'),
        ('ECE', 'Electronics and Communication Engineering'),
        ('MECH', 'Mechanical Engineering'),
        ('CIVIL', 'Civil Engineering'),
    )

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    FILE_TYPE_CHOICES = (
        ('pdf', 'PDF'),
        ('doc', 'Document (Word/Writer)'),
        ('image', 'Image'),
        ('ppt', 'PowerPoint'),
        ('other', 'Other'),
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    file = models.FileField(upload_to='resources/')
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES, default='other')
    subject = models.CharField(max_length=100)
    branch = models.CharField(max_length=10, choices=BRANCH_CHOICES)
    semester = models.IntegerField()
    tags = models.CharField(max_length=255, blank=True, default='', help_text='Comma-separated tags')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='uploaded_resources'
    )
    downloads = models.IntegerField(default=0)
    avg_rating = models.FloatField(default=0.0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='approved')
    bookmarked_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='bookmarks',
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
