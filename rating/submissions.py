import json
import os
import urllib.error
import urllib.request


def pending_submission_url() -> str | None:
    try:
        import streamlit as st

        url = st.secrets.get("pending_submission_url")
        if url and "YOUR_DEPLOYMENT_ID" not in str(url):
            return str(url)
    except Exception:
        pass
    url = os.environ.get("PENDING_SUBMISSION_URL")
    if url and "YOUR_DEPLOYMENT_ID" not in url:
        return url
    return None


def submissions_configured() -> bool:
    return pending_submission_url() is not None


def submit_pending_ranking(player: str, ex_rating: float, date_added: str) -> tuple[bool, str]:
    url = pending_submission_url()
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
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        return False, f"Could not submit: {error}"

    if body.get("success"):
        return True, "Submitted for review. You'll appear on the board once approved."
    return False, body.get("error", "Submission failed.")
