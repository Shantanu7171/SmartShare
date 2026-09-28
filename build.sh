#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Create admin superuser automatically if environment variables are set (to bypass paid Render Shell restriction securely)
python manage.py shell -c "import os; from django.contrib.auth import get_user_model; User = get_user_model(); email = os.environ.get('ADMIN_EMAIL'); username = os.environ.get('ADMIN_USERNAME'); password = os.environ.get('ADMIN_PASSWORD'); (email and username and password) and (User.objects.filter(email=email).exists() or User.objects.create_superuser(email, username, password) and print('Admin user verified/created successfully'))"
