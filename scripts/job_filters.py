KEYWORDS = [
    "python", "pytorch", "scikit", "machine learning", "ml engineer",
    "ai engineer", "artificial intelligence", "llm", "nlp", "rag",
    "typescript", "nestjs", "node.js", "nodejs", "backend",
    "postgresql", "prompt engineering", "software engineer",
    "aprendizaje automatico", "ingeniero de ia",
]

SENIOR_RE = ["senior", "staff", "principal", "lead", "director", "head of", "vp "]
LOCATION_OK_RE = ["remote", "worldwide", "anywhere", "europe", "eu ", "emea", "spain", "espana", "madrid"]
LOCATION_BAD_RE = [
    "usa only", "us only", "u.s. only", "us-only", "us citizen", "united states only",
    "estados unidos", "usa", "canada", "india", "latam", "brazil", "brasil",
    "londres", "london", "nueva york", "new york", "san francisco", "reino unido",
    "united kingdom",
]


def matches_keywords(text):
    text = text.lower()
    return [k for k in KEYWORDS if k in text]


def is_senior(title):
    return any(s in title.lower() for s in SENIOR_RE)


def location_ok(location):
    loc = location.lower()
    if any(b in loc for b in LOCATION_BAD_RE):
        return False
    return any(ok in loc for ok in LOCATION_OK_RE)
