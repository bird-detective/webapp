from django.shortcuts import render

from .models import Visit


def index(request):
    visits = Visit.objects.order_by("-created")[:10]
    return render(request, "colony/index.html", {"visits": visits})
