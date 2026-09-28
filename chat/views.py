import logging
import requests
from decouple import config
from django.utils import timezone
from django.db.models import Q
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import ChatMessage, ChatClear
from .serializers import ChatMessageSerializer
from resources.models import Resource
from core.throttling import AIGenerationRateThrottle

logger = logging.getLogger(__name__)


class ChatMessageViewSet(viewsets.ModelViewSet):
    """
    Peer Lounge me SmartBot AI Chatbot ke liye ViewSet.
    User ke academic sawalon ke jawab Gemini AI se deta hai,
    study notes dhoondta hai, aur offline fallbacks provide karta hai.
    """
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        """
        Current user ke messages return karta hai.
        Agar user ne chat clear ki ho toh cleared_at ke baad ke messages dikhata hai.
        """
        user = self.request.user
        chat_clear = getattr(user, 'chat_clear', None)
        qs = ChatMessage.objects.filter(user=user)
        if chat_clear:
            qs = qs.filter(created_at__gt=chat_clear.cleared_at)
        else:
            qs = qs.filter(created_at__gte=user.date_joined)
        return qs.order_by('created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, is_bot=False)

    @action(detail=False, methods=['delete'], url_path='clear')
    def clear_chat(self, request):
        """
        User ke liye chat window clear karta hai (cleared_at timestamp update karke).
        """
        user = request.user
        chat_clear, _ = ChatClear.objects.get_or_create(user=user)
        chat_clear.cleared_at = timezone.now()
        chat_clear.save()
        return Response({"detail": "Chat history cleared successfully."}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='ask-bot', throttle_classes=[AIGenerationRateThrottle])
    def ask_bot(self, request):
        """
        User ka message receive karta hai, bot ka response generate karta hai,
        dono ko database me save karta hai, aur response return karta hai.
        """
        query = request.data.get('message', '').strip()
        if not query:
            return Response({'error': 'Message required'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. User ka sawal save karo
        user_msg = ChatMessage.objects.create(user=request.user, message=query, is_bot=False)

        # 2. SmartBot ka jawab generate karo (Greetings / Vault Notes / Gemini AI / Fallback)
        reply_text = self._generate_bot_response(query, request.user)

        # 3. Bot ka answer save karo
        bot_msg = ChatMessage.objects.create(user=request.user, message=reply_text, is_bot=True)

        return Response({
            'user_message': ChatMessageSerializer(user_msg).data,
            'bot_message': ChatMessageSerializer(bot_msg).data,
            'reply': reply_text
        }, status=status.HTTP_200_OK)

    def _generate_bot_response(self, query, user=None):
        """
        Response decide karta hai:
        Step 1: Simple greeting check (hi, hello, namaste)
        Step 2: Notes search check (find notes, pyq, syllabus)
        Step 3: Gemini AI API call
        Step 4: Offline knowledge fallback
        """
        q_lower = query.lower().strip()

        # Step 1: Greeting
        if q_lower in ['hi', 'hello', 'hey', 'start', 'greetings', 'namaste', 'halo']:
            name = user.first_name if user and user.first_name else (user.username if user else "Student")
            return (
                f"Hello {name}! 👋 I'm **SmartBot**, your 24/7 AI Academic Tutor and Study Guide.\n\n"
                "You can ask me **any academic or technical question**, including:\n"
                "• **Concepts & Explanations**: DSA, DBMS, Operating Systems, Computer Networks, AI, Mathematics, Physics\n"
                "• **Code & Debugging**: Python, Java, C++, SQL queries, Web Development\n"
                "• **Exam Preparation**: Formula derivations, important semester questions, and revision tips\n"
                "• **Vault Notes**: Search lecture notes, syllabus blueprints, and previous year papers\n\n"
                "What topic or subject would you like to explore right now?"
            )

        # Step 2: Vault Resource Search
        is_vault_search = any(w in q_lower for w in ['find notes', 'search notes', 'give notes', 'show notes', 'download notes', 'notes for', 'question papers for', 'pyq'])
        if is_vault_search:
            vault_results = self._search_vault_notes(q_lower)
            if vault_results:
                return vault_results

        # Step 3: Call Gemini AI
        ai_response = self._call_gemini_ai(query, user)
        if ai_response:
            return ai_response

        # Step 4: Offline Fallback (agar internet ya AI offline ho)
        return self._generate_fallback_response(q_lower, query)

    def _call_gemini_ai(self, query, user=None):
        """
        Google Gemini AI (gemini-2.5-flash / fallback) ko call karta hai.
        Conversation continuity ke liye pichle 4 messages context me bhejta hai.
        """
        api_key = config('GEMINI_API_KEY', default=None)
        if not api_key:
            logger.warning("GEMINI_API_KEY not configured in backend/.env")
            return None

        system_instruction = (
            "You are SmartBot, an expert academic tutor and study companion on SmartShare.\n"
            "Your mission is to answer ANY academic, engineering, scientific, mathematical, or college syllabus question.\n"
            "Guidelines:\n"
            "1. Answer clearly, accurately, and step-by-step.\n"
            "2. Use formulas, bullet points, real-world examples, and code blocks with syntax highlighting.\n"
            "3. If the student asks in Hindi, Hinglish, or English, reply naturally in easy-to-understand language.\n"
            "4. Format cleanly in Markdown."
        )

        # Previous conversation context
        contents = []
        if user:
            recent_msgs = list(ChatMessage.objects.filter(user=user).order_by('-created_at')[:5])
            recent_msgs.reverse()
            for msg in recent_msgs[:-1]:
                role = "model" if msg.is_bot else "user"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.message[:1000]}]
                })

        # Current query
        contents.append({
            "role": "user",
            "parts": [{"text": query}]
        })

        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 2048}
        }

        models_to_try = ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-3.8-flash']
        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                response = requests.post(url, json=payload, timeout=25)
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
            except Exception as e:
                logger.warning(f"Error querying Gemini model {model_name}: {e}")

        return None

    def _search_vault_notes(self, q_lower):
        """
        Resource database me se query ke hisab se matching notes dhoondta hai.
        """
        stop_words = {'the', 'for', 'and', 'notes', 'need', 'give', 'show', 'find', 'search', 'get', 'download', 'some', 'please', 'any'}
        words = [w for w in q_lower.split() if len(w) > 2 and w not in stop_words]
        if not words:
            return None

        q_filter = Q()
        for word in words[:4]:
            q_filter |= Q(title__icontains=word) | Q(subject__icontains=word) | Q(branch__icontains=word)

        found = Resource.objects.filter(q_filter, status='approved')[:5]
        if found.exists():
            items = "\n".join([f"• [{r.title} ({r.branch} Sem {r.semester} - {r.subject})](/resources/{r.id}/)" for r in found])
            return (
                f"📚 **Study Notes Found in the Vault:**\n\n"
                f"{items}\n\n"
                f"Click any note link above to inspect syllabus topics, read student reviews, or download the full PDF/document."
            )
        return None

    def _generate_fallback_response(self, q_lower, query):
        """
        Internet ya Gemini AI unreachable hone par standard offline answers return karta hai.
        """
        # DSA / Algorithms
        if any(w in q_lower for w in ['dsa', 'algorithm', 'binary search', 'graph', 'tree', 'linked list', 'sorting', 'dp']):
            return (
                f"💡 **DSA Key Concepts regarding your query ({query}):**\n\n"
                "• **Time Complexity**: Big-O hierarchy: `O(1) < O(log N) < O(N) < O(N log N) < O(N²) < O(2ⁿ)`.\n"
                "• **Core Strategy**: Check if the problem maps to Sliding Window, Two Pointers, BFS/DFS Traversal, or Dynamic Programming.\n"
                "• **Tip**: Always analyze input constraints before coding."
            )

        # DBMS / SQL
        if any(w in q_lower for w in ['dbms', 'sql', 'database', 'acid', 'normalization', 'transaction', 'index']):
            return (
                f"💡 **Database Management Essentials ({query}):**\n\n"
                "• **ACID Properties**: Atomicity, Consistency, Isolation, Durability.\n"
                "• **Normalization**: 1NF (atomic) → 2NF (remove partial dep) → 3NF (remove transitive dep) → BCNF.\n"
                "• **Indexes**: B-Tree indexes speed up `WHERE`, `JOIN`, and `ORDER BY` operations."
            )

        # Operating Systems
        if any(w in q_lower for w in ['os', 'operating system', 'process', 'thread', 'deadlock', 'paging', 'virtual memory']):
            return (
                f"💡 **Operating Systems Breakdown ({query}):**\n\n"
                "• **Process vs Thread**: Processes have independent memory; threads share address space and resources.\n"
                "• **Deadlock Conditions**: Mutual Exclusion, Hold and Wait, No Preemption, Circular Wait.\n"
                "• **Virtual Memory**: Implemented via paging and TLB cache."
            )

        # Default response
        return (
            f"Here is an overview for **{query}**:\n\n"
            "This is a key college study topic. For comprehensive preparation:\n"
            "1. Review fundamental concepts, laws, and formulas.\n"
            "2. Practice standard numericals and previous year questions.\n"
            "3. Check verified notes in the [Resource Feed](/feed/) or generate a test with the [AI Quiz Generator](/ai-quiz/)!"
        )
