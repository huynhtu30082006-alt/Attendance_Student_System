from django.db import IntegrityError, transaction
from django.shortcuts import render


def render_confirm(request, title, message, cancel_url, button="Confirm"):
    """Confirmation page for destructive / irreversible actions (NFR Action Confirmation)."""
    return render(request, "confirm.html", {
        "title": title, "message": message,
        "cancel_url": cancel_url, "button": button,
    })


def next_code(model, field, prefix, width=4):
    """Next free code such as CL0007 (largest existing number + 1)."""
    numbers = [
        int(code[len(prefix):])
        for code in model.objects.filter(**{f"{field}__startswith": prefix})
        .values_list(field, flat=True)
        if code[len(prefix):].isdigit()
    ]
    return f"{prefix}{(max(numbers) if numbers else 0) + 1:0{width}d}"


def create_with_code(model, field, prefix, width=4, attempts=5, **kwargs):
    """Create an object whose primary key is a generated code. If two requests pick the same code at
    the same moment, the loser retries with the next number instead of failing."""
    for _ in range(attempts):
        code = next_code(model, field, prefix, width)
        try:
            with transaction.atomic():
                return model.objects.create(**{field: code}, **kwargs)
        except IntegrityError:
            if not model.objects.filter(**{field: code}).exists():
                raise  # not a code collision: another constraint failed, so do not hide it
    raise IntegrityError(f"Could not generate a unique {field}")
