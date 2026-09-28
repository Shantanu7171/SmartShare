from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend

class UnverifiedSMTPEmailBackend(DjangoEmailBackend):
    pass
