import logging

from django.contrib.auth import get_user_model
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import RegisterSerializer, UserSerializer

User = get_user_model()
logger = logging.getLogger("apps.accounts")


class EmailTokenObtainPairView(TokenObtainPairView):
    """Email login that ignores a stale bearer token and does not log secrets."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        email = str(request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        if not email or not password:
            logger.warning("Login rejected because the email or password was empty")
            raise AuthenticationFailed("Enter both an email address and a password.")
        user = User.objects.filter(email__iexact=email).order_by("id").first()
        if user is None or not user.check_password(password):
            logger.warning("Login failed for %s", email)
            raise AuthenticationFailed("The email or password is incorrect.")
        if not user.is_active:
            logger.warning("Login rejected for inactive account %s", email)
            raise AuthenticationFailed("This account is inactive.")
        refresh = RefreshToken.for_user(user)
        logger.info("Login succeeded for %s", user.email)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
