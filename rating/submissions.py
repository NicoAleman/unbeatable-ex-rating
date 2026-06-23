import json
import os
import socket
import urllib.error
import urllib.request

SUBMISSION_TIMEOUT_SECONDS = 60
SUBMISSION_TIMEOUT_MESSAGE = (
    "The submission server did not respond in time. "
    "Your rating may still have been saved — refresh the leaderboard to check."
)


def submission_url() -> str | None:
    try:
        import streamlit as st

        for key in ("submission_url", "pending_submission_url"):
            url = st.secrets.get(key)
            if url and "YOUR_DEPLOYMENT_ID" not in str(url):
                return str(url)
    except Exception:
        pass

    for env_key in ("SUBMISSION_URL", "PENDING_SUBMISSION_URL"):
        url = os.environ.get(env_key)
        if url and "YOUR_DEPLOYMENT_ID" not in url:
            return url
    return None


def pending_submission_url() -> str | None:
    """Backward-compatible alias for submission_url()."""
    return submission_url()


def submissions_configured() -> bool:
    return submission_url() is not None


def submit_ranking(player: str, ex_rating: float, date_added: str) -> tuple[bool, str]:
    url = submission_url()
    if not url:
        return False, "Submissions are not configured yet."

    payload = json.dumps(
        {
            "player": player,
            "ex_rating": ex_rating,
            "date_added": date_added,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "UnbeatableEXRating/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=SUBMISSION_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except TimeoutError:
        return False, SUBMISSION_TIMEOUT_MESSAGE
    except urllib.error.URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            return False, SUBMISSION_TIMEOUT_MESSAGE
        return False, f"Could not submit: {error}"
    except json.JSONDecodeError:
        return False, "Received an invalid response from the submission server."

    if body.get("success"):
        return True, str(body.get("message", "Submitted successfully."))
    return False, str(body.get("error", "Submission failed."))


def submit_pending_ranking(player: str, ex_rating: float, date_added: str) -> tuple[bool, str]:
    """Backward-compatible alias for submit_ranking()."""
    return submit_ranking(player, ex_rating, date_added)
