import json
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

from components.committees import get_committees
from components.models import Committee


Json = list[dict[str, Optional[str | bool | dict[str, str | bool]]]]
COMMITTEE_ID_RE = re.compile(r"_(J|H|S)\d+\.json$", re.IGNORECASE)


def extract_committee_id(path: Path) -> str | None:
    """Return committee ID like 'J11' from filename 'basic_J11.json'."""
    m = COMMITTEE_ID_RE.search(path.name)
    if m:
        # Normalize capitalization (J11, H33, S48)
        return m.group(0).split("_")[1].replace(".json", "").upper()
    return None


def build_committee_lookup(committees: list[Committee]) -> dict[str, Committee]:
    return {c.id.upper(): c for c in committees}


def find_latest_folder(path: Path) -> Path:
    """Locate the latest folder in YYYY/MM/DD format under the base path.
    """
    base = Path(path)
    years = [
        p
        for p in base.iterdir()
        if p.is_dir() and p.name.isdigit() and len(p.name) == 4
    ]
    if not years:
        raise RuntimeError(f"No YYYY/ folders found under {base}")
    latest_year = max(years, key=lambda y: int(y.name))
    months = [
        p
        for p in latest_year.iterdir()
        if p.is_dir() and p.name.isdigit() and 1 <= int(p.name) <= 12
    ]
    if not months:
        raise RuntimeError(f"No MM/ folders found under {latest_year}")
    latest_month = max(months, key=lambda m: int(m.name))
    days = [
        p
        for p in latest_month.iterdir()
        if p.is_dir() and p.name.isdigit() and 1 <= int(p.name) <= 31
    ]
    if not days:
        raise RuntimeError(f"No DD/ folders found under {latest_month}")
    latest_day = max(days, key=lambda d: int(d.name))
    return latest_day


def load_json_files(folder: Path) -> list[tuple[str, dict]]:
    """Return list of (committee_id, data_object)."""
    json_files = list(folder.glob("*.json"))
    results = []
    for jf in json_files:
        cid = extract_committee_id(jf)
        if not cid:
            print(f"[!] Could not extract committee ID from {jf.name}")
            continue
        try:
            with open(jf, "r", encoding="utf-8") as f:
                results.append((cid, json.load(f)))
        except Exception as e:
            print(f"[!] Could not read {jf}: {e}")
    return results


def extract_non_compliant_bills(loaded: list[tuple[str, dict]]) -> Json:
    dedup = {}
    for committee_id, obj in loaded:
        bills = obj.get("bills", [])
        for bill in bills:
            if bill.get("votes_present") is False and bill.get("state") == "Non-Compliant":
                bill_id = bill.get("bill_id")
                if bill_id in dedup:
                    continue
                new_bill = bill.copy()
                new_bill["committee_id"] = committee_id  # attach
                dedup[bill_id] = new_bill
    return list(dedup.values())


def save_to_csv(bills: Json, outfile="non_compliant_bills.csv") -> None:
    """Save selected bill fields to CSV."""
    header = [
        "Bill Title",
        "Bill URL",
        "Hearing Date",
        "Deadline",
        "State",
        "Reason",
        "Summary URL",
        "Votes URL",
    ]
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for b in bills:
            writer.writerow([
                b.get("bill_title"),
                b.get("bill_url"),
                b.get("hearing_date"),
                b.get("deadline_60"),
                b.get("state"),
                b.get("reason"),
                b.get("summary_url", ""),
                b.get("votes_url", ""),
            ])
    print(f"[>] CSV created: {outfile}")


def categorize_bills(bills: Json) -> dict:
    """
    Categorize bills by title using simple keyword matching.
    Returns:
        {
            "categorized_bills": [...],
            "category_counts": {category: count},
        }
    """
    categories = {
        'Agriculture': [
            'agriculture', 'farm', 'farmer', 'fish', 'fishing', 'seafood', 'pesticide', 'food', 'crop'
        ],
        'Privacy/Tech': [
            'privacy','data','cyber','technology','internet','digital','ai','artificial'
        ],
        'Consumer Protection': [
            'consumer','protection','scam','fraud'
        ],
        'Health': [
            'health','medical','hospital','mental','public health','pharmacy'
        ],
        'Education': [
            'school','education','student','teacher','curriculum','university','college'
        ],
        'Transportation': [
            'transport','traffic','road','vehicle','transit','mbta','highway'
        ],
        'Environment': [
            'environment','climate','energy','waste','water','emissions','pollution'
        ],
        'Housing': [
            'housing','zoning','landlord','tenant','development'
        ],
        'Criminal Justice': [
            'crime','criminal','police','justice','safety','court','correction'
        ],
        'Public Safety': [
            'fire', 'ems', 'emergency', 'disaster', 'preparedness', 'responder', 'safety'
        ],
        'Tax/Finance': [
            'tax','revenue','finance','budget','appropriat'
        ],
        'Elections/Government': [
            'election','voting','government','ethics','public','transparency'
        ],
        'Labor/Workforce': [
            'labor','employment','worker','wage','union'
        ],
        'Utilities/Telecommunication': [
            'utility', 'utilities', 'electric', 'gas', 'broadband', 'grid', 'telecom', 'rate', 'storm'
        ]
    }

    def classify(title: str) -> str:
        if not title:
            return "Other"
        lower = title.lower()
        for category, keys in categories.items():
            if any(k in lower for k in keys):
                return category
        return "Other"
    # Apply classification
    for b in bills:
        b["category"] = classify(b.get("bill_title", ""))
    # Aggregate counts
    counts = {}
    for b in bills:
        cat = b["category"]
        counts[cat] = counts.get(cat, 0) + 1
    return {
        "categorized_bills": bills,
        "category_counts": counts
    }


def analyze_keyword_frequencies(
    bills: Json,
    top_n: int = 50
) -> dict:
    """
    Analyze keyword frequencies in bill titles.
    Removes boilerplate like 'An Act', 'relative to', etc.
    Removes English stopwords.
    Returns:
        {
            "freqs": Counter,
            "top": [(keyword, count), ...]  # top N
        }
    """
    # Common legislative boilerplate to REMOVE entirely
    boilerplate_phrases = [
        r"\ban act (?:.*? )?to\b",
        r"\ban act (?:.*? )?relative to\b",
        r"\ban act\b",
        r"\brelative to\b",
        r"\bconcerning\b",
        r"\bregarding\b",
        r"\ban act establishing\b",
        r"\ban act creating\b",
        r"\ban act providing for\b",
    ]
    # Standard English stopwords + some MA-specific fillers
    stopwords = set("""
        a about above after again against all am an and any are as at be because been
        before being below between both but by could did do does doing down during each
        few for from further had has have having he her here hers herself him himself his
        how i if in into is it its itself just me more most my myself no nor not of off on
        once only or other our ours ourselves out over own same she should so some such
        than that the their theirs them themselves then there these they this those through
        to too under until up very was we were what when where which while who whom why will
        with you your yours yourself yourselves
        act bill relative provide providing establish establishing
        massachusetts commonwealth
    """.split())
    # Normalize boilerplate patterns into compiled regex
    boilerplate_regexes = [re.compile(p, flags=re.IGNORECASE) for p in boilerplate_phrases]
    words = []
    for bill in bills:
        title = bill.get("bill_title", "") or ""
        t = title.lower()
        # Strip boilerplate phrases
        for pattern in boilerplate_regexes:
            t = pattern.sub(" ", t)
        # Remove punctuation; keep hyphens as separators
        t = re.sub(r"[^a-z0-9\- ]", " ", t)
        # Split into words
        tokens = t.split()
        # Remove stopwords and tiny words
        tokens = [
            tok for tok in tokens
            if tok not in stopwords and len(tok) > 2
        ]
        # Singularize simple plurals (e.g., bills → bill)
        cleaned = []
        for tok in tokens:
            if tok.endswith("s") and len(tok) > 3:
                cleaned.append(tok[:-1])
            else:
                cleaned.append(tok)
        words.extend(cleaned)
    freqs = Counter(words)
    return {
        "freqs": freqs,
        "top": freqs.most_common(top_n)
    }


def cluster_bill_topics(
    bills: Json,
    n_clusters: int = 12,
    use_embeddings: bool = True
) -> dict:
    """Perform ML-based topic clustering on bill titles.
    If sentence-transformers is installed, uses embeddings.
    Otherwise falls back to TF-IDF vectors.
    
    Returns:
        {
            "clusters": {
                cluster_id: {
                    "keywords": [...],
                    "bills": [bill_objects],
                },
            },
            "labels": {cluster_id: "human label"},
            "model_used": "embeddings" or "tfidf",
        }
    """
    titles = [b.get("bill_title", "") or "" for b in bills]
    boilerplate_phrases = [
        r"\ban act(?:\s+relative\s+to|\s+establishing|"\
        r"\s+providing\s+for|\s+creating|\s+to)?\b",
        r"\brelative to\b",
        r"\bconcerning\b",
        r"\bregarding\b",
        r"\ba resolve(?: to)?\b",
    ]
    boilerplate_regexes = [
        re.compile(p, flags=re.IGNORECASE) for p in boilerplate_phrases
    ]

    def clean_text(t: str) -> str:
        t = t.lower()
        for pattern in boilerplate_regexes:
            t = pattern.sub(" ", t)
        t = re.sub(r"[^a-z0-9\- ]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    clean_titles = [clean_text(t) for t in titles]
    vectors = None
    model_used = None
    if use_embeddings:
        try:
            model = SentenceTransformer("all-MiniLM-L6-v2")
            vectors = model.encode(clean_titles, show_progress_bar=False)
            model_used = "embeddings"
        except Exception:
            use_embeddings = False
    if not use_embeddings:
        # Fallback: TF-IDF vectors
        vec = TfidfVectorizer(
            stop_words="english",
            max_features=3000,
            ngram_range=(1,2)
        )
        vectors = vec.fit_transform(clean_titles)
        model_used = "tfidf"
    km = KMeans(
        n_clusters=n_clusters,
        random_state=42,
        n_init=10
    )
    labels = km.fit_predict(vectors)
    cluster_keywords = defaultdict(list)
    if model_used == "tfidf":
        # Extract keywords from center → nearest TF-IDF features
        feature_names = vec.get_feature_names_out()
        centers = km.cluster_centers_
        for i in range(n_clusters):
            center = centers[i]
            top_idx = center.argsort()[::-1][:10]
            cluster_keywords[i] = [feature_names[j] for j in top_idx]
    else:
        # Embeddings can't extract feature weights → fallback:
        # Use TF-IDF keywords as labeling vocabulary
        label_vec = TfidfVectorizer(stop_words="english", max_features=2000)
        label_matrix = label_vec.fit_transform(clean_titles)
        feature_names = label_vec.get_feature_names_out()
        # For each cluster, aggregate TF-IDF weights
        for cid in range(n_clusters):
            idxs = [i for i,l in enumerate(labels) if l == cid]
            if not idxs:
                cluster_keywords[cid] = []
                continue
            sub = label_matrix[idxs].sum(axis=0).A1
            top_idx = sub.argsort()[::-1][:10]
            cluster_keywords[cid] = [feature_names[j] for j in top_idx]
    clusters = defaultdict(lambda: {"keywords": [], "bills": []})
    for cid in range(n_clusters):
        clusters[cid]["keywords"] = cluster_keywords[cid]
    for idx, cid in enumerate(labels):
        clusters[cid]["bills"].append(bills[idx])
    human_labels = {
        cid: ", ".join(cluster_keywords[cid][:3]) if cluster_keywords[cid] else "Misc"
        for cid in range(n_clusters)
    }
    return {
        "clusters": clusters,
        "labels": human_labels,
        "model_used": model_used,
    }


def print_missing_votes_by_committee(bills: Json) -> None:
    """Print sorted counts of missing-vote bills grouped by committee name."""
    committees = get_committees(
        "https://malegislature.gov",
        ("Joint", "House", "Senate")
    )
    lookup = build_committee_lookup(committees)
    # Count by committee_id
    counts = Counter()
    for b in bills:
        cid = b.get("committee_id")
        if cid:
            counts[cid] += 1
    # Convert to list of (name, count)
    results = []
    for cid, count in counts.items():
        committee = lookup.get(cid)
        name = committee.name if committee else f"Unknown ({cid})"
        results.append((name, count))
    # Sort from highest → lowest
    results.sort(key=lambda x: x[1], reverse=True)
    print("[>] Missing votes by committee:")
    for name, count in results:
        print(f"    {name}: {count}")


if __name__ == "__main__":
    base_path = Path(__file__).resolve().parent.parent / "out"
    print(f"[?] Searching under: {base_path}")
    try:
        latest_folder = find_latest_folder(base_path)
    except RuntimeError as err:
        print(f"[X] Error: {err}")
        exit(1)
    print(f"[>] Latest folder: {latest_folder}")
    print("[>] Loading JSON files...")
    data_objects = load_json_files(latest_folder)
    print(f"   → Loaded {len(data_objects)} files")
    print("[?] Finding non-compliant bills with missing votes...")
    bills = extract_non_compliant_bills(data_objects)
    print(f"[>] Found {len(bills)} matching bills")
    if bills:
        print("[>] Exporting to CSV...")
        save_to_csv(bills)
    else:
        print("[!] No matching bills found. No CSV created.")
    print("[>] Categorizing bills...")
    cat_result = categorize_bills(bills)
    print("    [>] Category counts:")
    for k, v in cat_result["category_counts"].items():
        print(f"      {k}: {v}")
    print("[>] Generating keyword frequencies...")
    freqs_result = analyze_keyword_frequencies(bills, top_n=40)
    print("    [>] Top keywords:")
    for word, count in freqs_result["top"]:
        print(f"      {word:<20} {count}")
    print("[>] Clustering topics...")
    topics = cluster_bill_topics(bills, n_clusters=12)
    print(f"   [>] Using model: {topics['model_used']}")
    for cid, label in topics["labels"].items():
        print(f"\nCluster {cid}: {label}")
        print("Keywords:", topics["clusters"][cid]["keywords"][:10])
        print(f"Bills: {len(topics['clusters'][cid]['bills'])}")
    print_missing_votes_by_committee(bills)
