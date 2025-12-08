#!/usr/bin/env python3
"""
generate_reviews.py - Rewritten with robust PA-API parsing and local image saving.

Generates product review pages using:
 - GROQ (LLM) for review copy
 - Amazon Product Advertising API (PA-API) v5 for product data

Environment variables required:
 - GROQ_API_KEY
 - PA_ACCESS_KEY
 - PA_SECRET_KEY
 - AFFILIATE_TAG (optional; default 'snapxacc-20')
"""

import os
import time
import json
import hashlib
import hmac
import datetime
import requests
import urllib.parse
from bs4 import BeautifulSoup
from pathlib import Path
import re
from typing import List, Tuple, Optional

# -------------------------
# Configuration / Secrets
# -------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PA_ACCESS_KEY = os.getenv("PA_ACCESS_KEY")
PA_SECRET_KEY = os.getenv("PA_SECRET_KEY")
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "snapxacc-20")

if not all([GROQ_API_KEY, PA_ACCESS_KEY, PA_SECRET_KEY]):
    raise ValueError("Missing required secrets: GROQ_API_KEY, PA_ACCESS_KEY, PA_SECRET_KEY")

SITE_DIR = Path(".")
REVIEWS_DIR = SITE_DIR / "reviews"
IMAGES_DIR = REVIEWS_DIR / "images"
REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------
# Utilities
# -------------------------
def slugify(text: str, max_length: int = 100) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)          # remove punctuation
    text = re.sub(r"\s+", "-", text)              # spaces -> dash
    text = re.sub(r"-+", "-", text)               # collapse multiple dashes
    return text[:max_length].strip("-")

def retryable(max_attempts=3, backoff=1.0):
    def deco(fn):
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    sleep = backoff * (2 ** (attempt - 1))
                    print(f"Attempt {attempt} failed: {e}. Retrying in {sleep:.1f}s...")
                    time.sleep(sleep)
        return wrapper
    return deco

def safe_filename_from_url(url: str, fallback: str = "image") -> str:
    # Return a safe filename based on the URL or fallback name
    try:
        parsed = urllib.parse.urlparse(url)
        name = Path(parsed.path).name
        if not name:
            name = fallback
        # ensure extension; if none, add .jpg
        if "." not in name:
            name = name + ".jpg"
        # sanitize
        name = re.sub(r"[^\w\.-]", "-", name)
        return name[:120]
    except Exception:
        return f"{fallback}.jpg"

# -------------------------
# GROQ LLM generation
# -------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

@retryable(max_attempts=3, backoff=1.0)
def generate_with_groq(prompt: str, max_tokens: int = 1200, temperature: float = 0.7) -> str:
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Groq API error {resp.status_code}: {resp.text}")
    j = resp.json()
    try:
        return j["choices"][0]["message"]["content"].strip()
    except Exception:
        raise RuntimeError("Unexpected Groq response structure: " + json.dumps(j)[:1000])

# -------------------------
# PA-API v5 (AWS SigV4 signing)
# -------------------------
PA_HOST = "webservices.amazon.com"
PA_ENDPOINT = f"https://{PA_HOST}/paapi5/searchitems"
PA_REGION = "us-east-1"
PA_SERVICE = "ProductAdvertisingAPI"

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def _get_signature_key(secret_key: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing

@retryable(max_attempts=3, backoff=1.0)
def pa_api_search_items(keywords: str, item_count: int = 1) -> dict:
    payload = {
        "Keywords": keywords,
        "SearchIndex": "All",
        "ItemCount": item_count,
        "PartnerTag": AFFILIATE_TAG,
        "PartnerType": "Associates",
        "Marketplace": "www.amazon.com",
        "Resources": [
            "ItemInfo.Title",
            "Images.Primary.Medium",
            "Images.Primary.Large",
            "Images.Primary.Small",
            "ItemInfo.ByLineInfo",
            "Offers.Listings.Price",
            "DetailPageURL"
        ]
    }
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    t = datetime.datetime.utcnow()
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    datestamp = t.strftime("%Y%m%d")

    canonical_uri = "/paapi5/searchitems"
    canonical_querystring = ""
    canonical_headers = f"content-type:application/json\nhost:{PA_HOST}\nx-amz-date:{amz_date}\n"
    signed_headers = "content-type;host;x-amz-date"
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    canonical_request = "\n".join([
        "POST",
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers,
        payload_hash
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{datestamp}/{PA_REGION}/{PA_SERVICE}/aws4_request"
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    ])

    signing_key = _get_signature_key(PA_SECRET_KEY, datestamp, PA_REGION, PA_SERVICE)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        f"{algorithm} Credential={PA_ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Content-Type": "application/json",
        "X-Amz-Date": amz_date,
        "Authorization": authorization_header,
        "Host": PA_HOST
    }

    resp = requests.post(PA_ENDPOINT, data=payload_json.encode("utf-8"), headers=headers, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"PA-API error {resp.status_code}: {resp.text}")
    return resp.json()

# -------------------------
# Image download helper
# -------------------------
@retryable(max_attempts=2, backoff=0.5)
def download_image_to_reviews(url: str, fallback_basename: str = "product") -> Optional[str]:
    """
    Downloads an image URL into reviews/images/ and returns the filename (relative to reviews/).
    On failure, returns None.
    """
    if not url:
        return None
    try:
        resp = requests.get(url, stream=True, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            raise RuntimeError(f"Bad status {resp.status_code}")
        content_type = resp.headers.get("Content-Type", "")
        ext = None
        if "jpeg" in content_type:
            ext = ".jpg"
        elif "png" in content_type:
            ext = ".png"
        elif "gif" in content_type:
            ext = ".gif"
        else:
            # try to extract from URL
            parsed_name = safe_filename_from_url(url, fallback_basename)
            ext = Path(parsed_name).suffix or ".jpg"
        fname = safe_filename_from_url(url, fallback_basename)
        # if fname has no extension, append ext
        if not Path(fname).suffix:
            fname = fname + ext
        out_path = IMAGES_DIR / fname
        # If already exists, skip writing
        if not out_path.exists():
            with open(out_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return fname  # filename relative to reviews/
    except Exception as e:
        print(f"Failed to download image {url}: {e}")
        return None

# -------------------------
# Product discovery
# -------------------------
def get_trending_products(num: int = 5) -> List[Tuple[str, str]]:
    prompt = f"""
    Give exactly {num} completely different trending Amazon products right now (December 2025). Mix categories: gadgets, beauty, kitchen, cozy, fitness.
    NEVER number them. NEVER use dashes or bullets at the start.
    Format ONLY:
    Product Name | Amazon Search Term (exact, 4-8 words)
    Example:
    Cordless Water Flosser | cordless water flosser
    """
    raw = generate_with_groq(prompt, max_tokens=400)
    products = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        if line[0].isdigit() or line.startswith(("-", "•", "*")):
            continue
        parts = [p.strip() for p in line.split("|", 1)]
        if len(parts) == 2:
            products.append((parts[0], parts[1]))
            if len(products) >= num:
                break
    if not products:
        raise RuntimeError("No products returned from GROQ. Raw response:\n" + raw)
    return products

# -------------------------
# Generate a single review
# -------------------------
def generate_review(product_name: str, search_term: str) -> Tuple[str, str, str]:
    """
    Returns (review_filename, title, homepage_image_path)
    - review_filename: e.g. "smart-plug-power-strip.html" (file in reviews/)
    - homepage_image_path: path used in index.html (e.g. "reviews/images/abc.jpg")
    The review HTML uses images relative to the review file (images/<file>).
    """
    print(f"Fetching product data for search term: {search_term}")
    api_result = None
    try:
        api_result = pa_api_search_items(search_term, item_count=1)
    except Exception as e:
        print(f"PA-API failed for '{search_term}': {e}. Falling back to placeholder data.")

    # Defaults
    title = product_name
    placeholder_url = "https://via.placeholder.com/800x600/0d6efd/ffffff.png?text=No+Image"
    # default image filename (will be used as fallback)
    placeholder_fname = None

    # Parse items robustly
    item = None
    if api_result:
        # Check multiple possible result locations
        items = (
            api_result.get("SearchResult", {}).get("Items")
            or api_result.get("ItemsResult", {}).get("Items")
            or api_result.get("Items")
            or []
        )
        # If items is a dict wrapper, try to unwrap common shapes
        if isinstance(items, dict):
            # e.g., {"Item": [...]} or {"Items": [...]}
            items = items.get("Item") or items.get("Items") or list(items.values())

        if isinstance(items, list) and len(items) > 0:
            item = items[0]
        elif isinstance(items, dict):
            item = items

    image_url_taken_from_api = None
    direct_link = f"https://www.amazon.com/s?k={urllib.parse.quote_plus(search_term)}&tag={AFFILIATE_TAG}"

    if item:
        try:
            # Title
            title = (
                item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue")
                or item.get("ItemInfo", {}).get("Title", {}).get("Title")
                or item.get("ASIN")
                or title
            )

            # Detail page
            direct_link = item.get("DetailPageURL") or direct_link

            # Robust image extraction (try many candidate fields)
            images = item.get("Images", {}) or {}
            primary = images.get("Primary", {}) or {}
            # Try many fields in order of preference
            candidates = [
                primary.get("Large", {}).get("URL"),
                primary.get("Large", {}).get("AmazonHosted"),
                primary.get("Large", {}).get("ImageUrl"),
                primary.get("HighRes", {}).get("URL") if isinstance(primary.get("HighRes", {}), dict) else None,
                primary.get("Medium", {}).get("URL"),
                primary.get("Small", {}).get("URL"),
            ]
            # Also consider common alternate wrappers
            if not any(candidates):
                # Sometimes PA-API returns nested Assets or Variants
                variants = images.get("Variants") or images.get("AlternateImages") or []
                if isinstance(variants, list) and variants:
                    # try first variant large
                    v = variants[0] or {}
                    candidates.extend([
                        v.get("Large", {}).get("URL"),
                        v.get("Medium", {}).get("URL")
                    ])

            # Flatten and choose first non-empty
            image_url_taken_from_api = next((c for c in candidates if c), None)
        except Exception as e:
            print("Warning: unexpected PA-API item structure:", e)

    # If no image from API, try scraping the detail page (best-effort fallback)
    if not image_url_taken_from_api and direct_link and direct_link.startswith("http"):
        try:
            # lightweight fetch with UA; some amazon pages block real scrapers — this is best-effort
            r = requests.get(direct_link, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                # Common meta tags
                og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
                if og and og.get("content"):
                    image_url_taken_from_api = og.get("content")
                # try twitter card
                if not image_url_taken_from_api:
                    tc = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
                    if tc and tc.get("content"):
                        image_url_taken_from_api = tc.get("content")
        except Exception as e:
            print(f"Detail page fetch failed (best-effort): {e}")

    # Try to download the image locally
    downloaded_fname = None
    if image_url_taken_from_api:
        downloaded_fname = download_image_to_reviews(image_url_taken_from_api, fallback_basename=slugify(title) or "product")
    else:
        # try to download the placeholder once (store locally)
        placeholder_fname = "placeholder-no-image.png"
        placeholder_path = IMAGES_DIR / placeholder_fname
        if not placeholder_path.exists():
            try:
                # download placeholder image into images folder
                resp = requests.get(placeholder_url, timeout=10)
                if resp.status_code == 200:
                    with open(placeholder_path, "wb") as f:
                        f.write(resp.content)
                    placeholder_fname = placeholder_fname
                else:
                    placeholder_fname = None
            except Exception:
                placeholder_fname = None
        downloaded_fname = placeholder_fname

    # Build paths used in pages:
    # - For review page (file inside reviews/): image path should be 'images/<fname>'
    # - For homepage (index.html at project root): image path should be 'reviews/images/<fname>'
    if downloaded_fname:
        review_image_src = f"images/{downloaded_fname}"
        homepage_image_src = f"reviews/images/{downloaded_fname}"
    else:
        # fallback to remote placeholder if download failed
        review_image_src = placeholder_url
        homepage_image_src = placeholder_url

    # Generate review content via GROQ
    prompt = f"""
    Write a fun, honest 800-1200 word review for "{title}" as @snapreviews_.
    Sections with <h2>: Why It's Trending, Pros & Cons (bullets), Features, Who It's For, Verdict.
    End with a big blue button link to {direct_link}.
    NEVER number anything.
    """
    print(f"Generating review content for title: {title}")
    try:
        content = generate_with_groq(prompt, max_tokens=1600)
    except Exception as e:
        print(f"Groq generation failed: {e}. Using short fallback review.")
        content = (
            f"<h2>Why It's Trending</h2><p>A trending find for shoppers.</p>"
            "<h2>Pros & Cons</h2><ul><li>Pro: Great value</li><li>Con: Limited stock</li></ul>"
            "<h2>Features</h2><p>Basic features described.</p>"
            "<h2>Who It's For</h2><p>Anyone who wants convenience.</p>"
            "<h2>Verdict</h2><p>Solid pick for the money.</p>"
            f'<p><a href="{direct_link}" class="btn" rel="nofollow">Check Price on Amazon →</a></p>'
        )

    # Build safe filename for review HTML
    filename_base = slugify(title) or slugify(product_name)
    filename = f"{filename_base[:80]}.html"
    filepath = REVIEWS_DIR / filename

    # Basic HTML template (review page). Note: image src is relative to reviews/ (images/<file>)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{title} Review 2025 – SnapReviews</title>
  <link rel="stylesheet" href="../assets/style.css" />
</head>
<body>
  <div class="container">
    <header>
      <h1>{title} Review 2025</h1>
      <p>Published {datetime.date.today()}</p>
    </header>
    <main>
      <img src="{review_image_src}" alt="{title}" style="width:100%;max-width:800px;border-radius:16px;margin:30px 0;box-shadow:0 8px 30px rgba(0,0,0,0.15);" />
      {content}
      <p><a href="{direct_link}" class="btn" rel="nofollow">Check Price on Amazon →</a></p>
    </main>
    <footer>
      <p>Affiliate link – may earn commission</p>
    </footer>
  </div>
</body>
</html>
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved review to: {filepath}")

    # Return name + title + homepage image path (to be used by update_homepage)
    return filename, title, homepage_image_src

# -------------------------
# Update homepage
# -------------------------
def update_homepage(new_reviews: List[Tuple[str, str, str]]):
    homepage = SITE_DIR / "index.html"
    if not homepage.exists():
        print("index.html not found - skipping homepage update.")
        return

    with open(homepage, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    grid = soup.find("div", id="reviews")
    if grid is None:
        print("No <div id='reviews'> found in index.html - skipping homepage update.")
        return

    for filename, name, img in reversed(new_reviews):
        card = soup.new_tag("div", attrs={"class": "review-card"})
        img_tag = soup.new_tag("img", src=img, alt=name)
        img_tag["style"] = "width:100%;height:400px;object-fit:cover;border-radius:16px;"
        card.append(img_tag)

        h2 = soup.new_tag("h2")
        h2.string = name
        card.append(h2)

        p = soup.new_tag("p")
        p.string = "Honest review of this viral Amazon find"
        card.append(p)

        a = soup.new_tag("a", href=f"reviews/{filename}", attrs={"class": "btn"})
        a.string = "Read Full Review"
        card.append(a)

        grid.insert(0, card)

    with open(homepage, "w", encoding="utf-8") as f:
        f.write(soup.prettify())
    print("Homepage updated with new reviews.")

# -------------------------
# Main
# -------------------------
def main():
    print("Starting review generation...")
    try:
        products = get_trending_products(5)
    except Exception as e:
        print("Failed to fetch trending products:", e)
        return

    new_reviews = []
    for name, term in products:
        try:
            filename, title, img = generate_review(name, term)
            new_reviews.append((filename, title, img))
            print(f"Created: {title}")
            time.sleep(1.2)
        except Exception as e:
            print(f"Failed to create review for {name} ({term}): {e}")

    if new_reviews:
        try:
            update_homepage(new_reviews)
        except Exception as e:
            print("Failed to update homepage:", e)

    print("Done. Created", len(new_reviews), "reviews.")

if __name__ == "__main__":
    main()
