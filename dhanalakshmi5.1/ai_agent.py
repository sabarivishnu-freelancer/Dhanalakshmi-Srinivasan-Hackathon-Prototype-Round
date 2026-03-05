import re
from typing import List, Tuple, Optional
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def analyze_petition(text: str):
    """Return (category, priority, reason, confidence).

    Keeps simple keyword rules but also returns a short reason and confidence score (0-1).
    """
    text = (text or "").lower()
    if len(text) < 20:
        return "Spam", "Low", "Too short to be a valid petition.", 0.35

    # rules with simple confidence
    rules = [
        (("water", "safety", "hazard", "broken"), ("Facility", "High", 0.95)),
        (("wifi", "internet", "network", "slow connection"), ("IT", "Medium", 0.85)),
        (("library", "books", "study"), ("Education", "Medium", 0.8)),
        (("exam", "grade", "marks", "assessment"), ("Academic", "High", 0.9)),
    ]

    for keys, (cat, pri, conf) in rules:
        for k in keys:
            if k in text:
                reason = f"Matched keyword '{k}'"
                return cat, pri, reason, conf

    # fallback
    return "Other", "Low", "No strong keywords found", 0.5


def find_similar(text: str, candidates: List[str], threshold: float = 0.75) -> Tuple[Optional[str], float]:
    """Return (matching_candidate, similarity_score) if above threshold.

    Uses TF-IDF + cosine similarity for semantic comparison.
    """
    if not candidates:
        return None, 0.0
    # vectorize input and candidates together
    tfidf = TfidfVectorizer().fit_transform([text] + candidates)
    sims = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()
    best_idx = sims.argmax()
    best_score = sims[best_idx]
    if best_score >= threshold:
        return candidates[best_idx], best_score
    return None, best_score
