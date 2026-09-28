# 🎓 Smart College Resource Sharing Platform

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.2+-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.0+-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)

> A modern, full-stack college resource sharing platform designed to enable academic collaboration between students and faculty.

Smart College Resource Sharing Platform provides a centralized platform where students and faculty members can **upload, search, review, bookmark, and download academic resources** such as PDF notes, lecture presentations, previous examination papers, laboratory manuals, and other study materials.

The platform combines **Django, Django REST Framework, React, Tailwind CSS, PostgreSQL, JWT authentication, and Cloudinary** to provide a complete academic resource-sharing ecosystem.

---

## 📑 Table of Contents

- [✨ Key Features](#-key-features)
- [🏗️ System Architecture](#️-system-architecture)
- [🧩 Resource Management Architecture](#-resource-management-architecture)
- [🔐 Authentication Architecture](#-authentication-architecture)
- [🗄️ Database Architecture](#️-database-architecture)
- [📤 Resource Upload Flow](#-resource-upload-flow)
- [💬 Peer Lounge Architecture](#-peer-lounge-architecture)
- [🏆 Contributor Leaderboard](#-contributor-leaderboard)
- [🤖 AI Quiz Architecture](#-ai-quiz-architecture)
- [🛠️ Tech Stack](#️-tech-stack)
- [📂 Project Structure](#-project-structure)
- [📡 API & Web Endpoints](#-api--web-endpoints)
- [🔌 Database Configuration](#-database-configuration)
- [⚙️ Local Installation](#️-local-installation)
- [🌐 Production Deployment](#-production-deployment)
- [🔒 Security](#-security)
- [📈 Future Improvements](#-future-improvements)
- [👨‍💻 Maintainer](#-maintainer)

---

# ✨ Key Features

### 🔐 Dual-Role Authentication

Secure authentication system supporting:

- 👨‍🎓 Students
- 👨‍🏫 Faculty Members
- 🛡️ Administrators / Moderators

Authentication includes:

- JWT authentication
- Django session authentication
- User registration
- Login
- Password reset using OTP
- Role-based authorization
- Protected API endpoints

---

### 📚 Academic Resource Sharing

Users can upload and share academic resources including:

- 📄 PDF notes
- 📊 PowerPoint presentations
- 📝 Documents
- 🖼️ Images
- 📚 Previous year question papers
- 🧪 Laboratory manuals
- 🎓 Lecture materials

Resources can be categorized by:

- Branch
- Semester
- Subject
- Resource type
- Approval status

---

### 🔍 Advanced Search & Filtering

Users can search and filter resources based on:

- Branch
- Semester
- Subject
- Resource type
- Approval status

Supported branches include:

```text
CSE
IT
ECE
MECH
CIVIL