import base64
import json
import logging
import os
import re
import requests
from io import BytesIO
from decouple import config

from django.db import transaction
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from resources.models import Resource
from core.throttling import AIGenerationRateThrottle
from .models import GeneratedQuiz, QuizQuestion, QuizAttempt
from .serializers import GeneratedQuizSerializer, QuizAttemptSerializer

try:
    import pypdf
except ImportError:
    pypdf = None

logger = logging.getLogger(__name__)




# HELPER FUNCTIONS: FILE PROCESSING (PDF, TXT, IMAGES)
def extract_text_from_pdf(file_input):
     # Text extraction from pdf
     
    if pypdf is None:
        logger.warning("pypdf installed nahi hai, PDF extract nahi ho sakta.")
        return ""

    try:
        reader = pypdf.PdfReader(file_input)
        pages_text = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages_text).strip()
    except Exception as e:
        logger.warning(f"PDF text extraction error: {e}")
        return ""


def read_file_content(file_obj, filename=""):
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    
    # 1. Plain text files
    if ext in ['txt', 'md', 'doc', 'docx']:
        try:
            content = file_obj.read()
            if isinstance(content, bytes):
                return content.decode('utf-8', errors='ignore'), None, None
            return str(content), None, None
        except Exception:
            return "", None, None

    # 2. Image files
    if ext in ['png', 'jpg', 'jpeg', 'webp']:
        file_bytes = file_obj.read()
        b64_data = base64.b64encode(file_bytes).decode('utf-8')
        mime = f"image/{'jpeg' if ext == 'jpg' else ext}"
        return "", b64_data, mime

    # 3. PDF files
    if ext == 'pdf':
        extracted_text = extract_text_from_pdf(file_obj)
        # Agar text kafi hai (>= 50 chars), directly text use karo
        if len(extracted_text) >= 50:
            return extracted_text, None, None

        # Agar scanned PDF hai or text kam hai, toh binary base64 banakar AI ko do
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        file_bytes = file_obj.read()
        b64_data = base64.b64encode(file_bytes).decode('utf-8')
        return "", b64_data, "application/pdf"

    # Fallback: Read as text
    try:
        content = file_obj.read()
        text = content.decode('utf-8', errors='ignore') if isinstance(content, bytes) else str(content)
        return text, None, None
    except Exception:
        return "", None, None



# HELPER FUNCTIONS: GEMINI AI API CALL
def call_gemini_quiz_api(api_key, prompt_text, notes_text="", b64_file_data=None, mime_type=None):

    # JSON Quiz generation using Google Gemini
    # Primary model: gemini-2.5-flash, sath me automatic fallbacks hain.
    
    parts = [{"text": prompt_text}]

    # Multimodal file ya plain text  prompt ke sath
    if b64_file_data and mime_type:
        parts.append({
            "inlineData": {
                "mimeType": mime_type,
                "data": b64_file_data
            }
        })
    else:
        parts.append({
            "text": f"Study Material Notes:\n\n{notes_text[:25000]}"
        })

    # Expected JSON schema for questions
    schema = {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "questions": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "question": {"type": "STRING"},
                        "option_a": {"type": "STRING"},
                        "option_b": {"type": "STRING"},
                        "option_c": {"type": "STRING"},
                        "option_d": {"type": "STRING"},
                        "correct_answer": {"type": "STRING", "enum": ["A", "B", "C", "D"]},
                        "explanation": {"type": "STRING"}
                    },
                    "required": ["question", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation"]
                }
            }
        },
        "required": ["title", "questions"]
    }

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    # Available models in order of priority
    models = ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-3.8-flash']
    last_error = ""

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=45)
            if res.status_code == 200:
                candidates = res.json().get('candidates', [])
                if candidates:
                    content_parts = candidates[0].get('content', {}).get('parts', [])
                    if content_parts and "text" in content_parts[0]:
                        raw_text = content_parts[0]["text"].strip()
                        # Markdown clean karo (```json ... ```)
                        clean_text = re.sub(r'^```(json)?\s*', '', raw_text, flags=re.MULTILINE)
                        clean_text = re.sub(r'\s*```$', '', clean_text, flags=re.MULTILINE).strip()
                        
                        try:
                            parsed_data = json.loads(clean_text)
                            if parsed_data.get('questions'):
                                return parsed_data, None
                        except json.JSONDecodeError:
                            # Agar direct json parse na ho toh regex se JSON object dhoondo
                            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
                            if match:
                                parsed_data = json.loads(match.group(0))
                                if parsed_data.get('questions'):
                                    return parsed_data, None
            else:
                last_error = f"{model} returned {res.status_code}: {res.text[:200]}"
                logger.warning(last_error)
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Error calling {model}: {e}")

    return None, last_error



# VIEWSETS: QUIZ MANAGEMENT & ATTEMPTS
class QuizViewSet(viewsets.ModelViewSet):

    # to  generate and manage AI quiz use ViewSet.
    
    serializer_class = GeneratedQuizSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Quiz created by user only
        return GeneratedQuiz.objects.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['post'], url_path='generate', throttle_classes=[AIGenerationRateThrottle])
    def generate_quiz(self, request):
       
        # Study material se AI Quiz 
      
        user = request.user

        #  Input parameters parse aur validate
        try:
            num_questions = int(request.data.get('num_questions', 5))
        except (ValueError, TypeError):
            num_questions = 5

        if num_questions < 1 or num_questions > 15:
            return Response({'error': 'Number of questions must be between 1 and 15.'}, status=status.HTTP_400_BAD_REQUEST)

        difficulty = request.data.get('difficulty', 'Medium')
        
        # 2. Material content extract karo
        notes_text = ""
        b64_file_data = None
        mime_type = None
        source_resource = None

        text_content = request.data.get('text_content', '').strip()
        uploaded_file = request.FILES.get('file')
        resource_id = request.data.get('resource_id')

        # Scenario A: User ne text paste kiya hai
        if text_content:
            notes_text = text_content

        # Scenario B: User ne file upload ki
        elif uploaded_file:
            notes_text, b64_file_data, mime_type = read_file_content(uploaded_file, uploaded_file.name)

        # Scenario C: Platform ki existing Resource 
        elif resource_id:
            try:
                source_resource = Resource.objects.get(id=resource_id)
                file_obj = source_resource.file

                # Pehle local disk me file check 
                if file_obj and hasattr(file_obj, 'path') and os.path.exists(file_obj.path):
                    with open(file_obj.path, 'rb') as f:
                        notes_text, b64_file_data, mime_type = read_file_content(f, file_obj.name)
                # Agar cloud storage (URL) 
                elif file_obj and getattr(file_obj, 'url', '').startswith('http'):
                    try:
                        res = requests.get(file_obj.url, stream=True, timeout=10)
                        if res.status_code == 200:
                            notes_text, b64_file_data, mime_type = read_file_content(BytesIO(res.content), file_obj.name)
                    except Exception as e:
                        logger.warning(f"Error fetching remote file: {e}")

                # if file se text na mile toh resource ke metadata (title, subject, tags) se quiz 
                if not notes_text and not b64_file_data:
                    meta = f"Subject: {source_resource.subject}\nTopic: {source_resource.title}\nBranch: {source_resource.branch} Sem {source_resource.semester}\n"
                    if source_resource.description:
                        meta += f"Description: {source_resource.description}\n"
                    if source_resource.tags:
                        meta += f"Tags: {source_resource.tags}\n"
                    notes_text = meta

            except Resource.DoesNotExist:
                return Response({'error': 'Selected resource does not exist.'}, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                return Response({'error': f'Resource processing error: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'error': 'Please provide text, upload a file, or select a resource.'}, status=status.HTTP_400_BAD_REQUEST)

        # Content length check (if plain text)
        if not b64_file_data and len(notes_text.strip()) < 30:
            return Response({'error': 'Study material is too short. Please provide at least 30 characters.'}, status=status.HTTP_400_BAD_REQUEST)

        # 3. Gemini API Key check
        api_key = config('GEMINI_API_KEY', default=None)
        if not api_key:
            return Response({'error': 'Gemini API Key is not configured in backend/.env'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 4. System prompt 
        prompt = (
            f"You are a professional university professor. Analyze the provided study material. "
            f"Generate a high-quality academic quiz with exactly {num_questions} multiple-choice questions (MCQs) "
            f"of {difficulty} difficulty based on concepts in the material. "
            f"Each question must have 4 distinct options (option_a, option_b, option_c, option_d), "
            f"a correct_answer ('A', 'B', 'C', or 'D'), and a comprehensive academic explanation."
        )

        # 5. Gemini AI call
        quiz_data, error_detail = call_gemini_quiz_api(
            api_key=api_key,
            prompt_text=prompt,
            notes_text=notes_text,
            b64_file_data=b64_file_data,
            mime_type=mime_type
        )

        if not quiz_data or not quiz_data.get('questions'):
            return Response({
                'error': f'Failed to generate quiz: {error_detail or "AI did not produce valid questions. Please try again."}'
            }, status=status.HTTP_502_BAD_GATEWAY)

        # 6. Database me Quiz aur Questions save karo
        try:
            with transaction.atomic():
                title_val = quiz_data.get('title') or f"Quiz on {difficulty} level"
                generated_quiz = GeneratedQuiz.objects.create(
                    title=title_val,
                    created_by=user,
                    resource=source_resource
                )

                questions = []
                for q in quiz_data.get('questions', []):
                    correct = (q.get('correct_answer') or 'A').strip().upper()
                    if correct not in ['A', 'B', 'C', 'D']:
                        correct = 'A'

                    questions.append(QuizQuestion(
                        quiz=generated_quiz,
                        question_text=q.get('question') or q.get('question_text') or '',
                        option_a=q.get('option_a', ''),
                        option_b=q.get('option_b', ''),
                        option_c=q.get('option_c', ''),
                        option_d=q.get('option_d', ''),
                        correct_answer=correct,
                        explanation=q.get('explanation', '')
                    ))

                QuizQuestion.objects.bulk_create(questions)

            # Response me serialized quiz return karo
            serializer = self.get_serializer(generated_quiz)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Quiz save error: {e}")
            return Response({'error': f'Database save error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='submit')
    def submit_answers(self, request, pk=None):
        """
        User ke quiz answers check karta hai, score calculate karta hai,
        gamification points deta hai (+2 per correct answer), aur attempt save karta hai.
        """
        quiz = self.get_object()
        user = request.user
        answers = request.data.get('answers', {})

        questions = quiz.questions.all()
        total_questions = questions.count()
        if total_questions == 0:
            return Response({'error': 'This quiz has no questions.'}, status=status.HTTP_400_BAD_REQUEST)

        score = 0
        results = []

        # Har question ka answer verify karo
        for q in questions:
            user_ans = answers.get(str(q.id)) or answers.get(q.id)
            user_ans_str = str(user_ans).strip().upper() if user_ans else 'None'
            is_correct = (user_ans_str == q.correct_answer.upper())

            if is_correct:
                score += 1

            results.append({
                'id': q.id,
                'question_id': q.id,
                'question_text': q.question_text,
                'option_a': q.option_a,
                'option_b': q.option_b,
                'option_c': q.option_c,
                'option_d': q.option_d,
                'user_answer': user_ans_str,
                'correct_answer': q.correct_answer,
                'is_correct': is_correct,
                'explanation': q.explanation
            })

        # Attempt record save karo
        attempt = QuizAttempt.objects.create(
            quiz=quiz,
            user=user,
            score=score,
            total_questions=total_questions
        )

        # Gamification: Reward user with +2 points per correct answer
        points_awarded = score * 2
        user.points += points_awarded
        user.save(update_fields=['points'])

        return Response({
            'attempt_id': attempt.id,
            'score': score,
            'total_questions': total_questions,
            'total': total_questions,
            'points_awarded': points_awarded,
            'new_total_points': user.points,
            'results': results
        }, status=status.HTTP_200_OK)


class AttemptViewSet(viewsets.ReadOnlyModelViewSet):
    # User ke purane quiz attempts dekhne ke liye read-only ViewSet.
    serializer_class = QuizAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Current user ke hi attempts
        return QuizAttempt.objects.filter(user=self.request.user)
