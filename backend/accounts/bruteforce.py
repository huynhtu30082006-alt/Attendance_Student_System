"""Brute-force protection (NFR): 5 consecutive failed logins for the same username within 10 minutes
-> every login for that username is rejected for 15 minutes, even with the correct password."""
from datetime import timedelta

from django.utils import timezone

from .models import LoginAttempt

MAX_FAILS = 5
WINDOW = timedelta(minutes=10)
LOCK_DURATION = timedelta(minutes=15)
KEEP_HISTORY = timedelta(days=1)


def lockout_until(username, now=None):
    """Return the time the lockout ends if the username is locked out, otherwise None."""
    now = now or timezone.now()
    horizon = now - (WINDOW + LOCK_DURATION)
    attempts = LoginAttempt.objects.filter(username=username)

    # "Consecutive": a successful login resets the count
    last_success = attempts.filter(succeeded=True).order_by("-attempted_at").first()
    fails = attempts.filter(succeeded=False, attempted_at__gte=horizon)
    if last_success:
        fails = fails.filter(attempted_at__gt=last_success.attempted_at)
    times = list(fails.order_by("attempted_at").values_list("attempted_at", flat=True))

    lock_until = None
    for i in range(len(times) - MAX_FAILS + 1):
        if times[i + MAX_FAILS - 1] - times[i] <= WINDOW:
            lock_until = times[i + MAX_FAILS - 1] + LOCK_DURATION
    if lock_until and lock_until > now:
        return lock_until
    return None


def record_attempt(username, succeeded):
    LoginAttempt.objects.create(username=username, succeeded=succeeded)


def purge_old_attempts(now=None):
    """Keep the table small: attempts older than a day can no longer influence a lockout."""
    now = now or timezone.now()
    LoginAttempt.objects.filter(attempted_at__lt=now - KEEP_HISTORY).delete()
