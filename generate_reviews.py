import os
import requests
from bs4 import BeautifulSoup
import datetime
import hashlib
import hmac
import base64
import time
import urllib.parse
from urllib.parse import quote

# === SECURE KEYS FROM GITHUB SECRETS ===
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PA_ACCESS_KEY = os.getenv("PA_ACCESS_KEY")
PA_SECRET_KEY = os.getenv("PA_SECRET_KEY")
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "snapxacc-20")

if not all([GROQ_API_KEY, PA_ACCESS_KEY, PA_SECRET_KEY]):
    raise ValueError("Missing required secrets: GROQ_API_KEY, PA_ACCESS_KEY, PA_SECRET_KEY")

SITE_DIR = "."
REVIEWS_DIR = os.path.join(SITE_DIR, "reviews")
os.makedirs(REVIEWS_DIR, exist_ok=True)

def generate_with_groq(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": 0.7
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"].strip()
    print("Groq error:", resp.text)
    return "Review content could not be generated."

def pa_api_signed_request(operation, keywords, item_count=1):
    """Make signed PA API v5 request for SearchItems."""
    endpoint = "webservices.amazon.com"
    uri = "/paapi5/searchitems"
    host = "webservices.amazon.com"
    service = "execute-api"
    region = "us-east-1"  # US marketplace

    # Canonical query string
    params = {
        'Keywords': keywords,
        'Resources': [
            'ItemInfo.Title',
            'Images.Primary.Medium',
            'Images.Primary.Large',
            'DetailPageURL',
            'ItemInfo.ByLineInfo',
            'Offers.Listings.Price'
        ],
        'ItemCount': item_count,
        'PartnerTag': AFFILIATE_TAG,
        'PartnerType': 'Associates',
        'Marketplace': 'www.amazon.com'
    }
    canonical_querystring = '&'.join([f"{k}={quote(v)}" for k, v in sorted(params.items()) if isinstance(v, str)])
    for k, v in params.items():
        if isinstance(v, list):
            for i, val in enumerate(v):
                canonical_querystring += f"&{k}.{i+1}={quote(val)}"
    payload_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 of empty string

    # Canonical headers
    canonical_headers = "host:" + host.lower() + "\n" + "x-amz-date:" + datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S Z') + "\n" + "x-amz-target:" + f"com.amazon.paapi5.v1.ProductAdvertisingAPIv5.{operation}" + "\n"
    signed_headers = "host;x-amz-date;x-amz-target"

    # Canonical request
    canonical_request = "POST\n" + uri + "\n" + canonical_querystring + "\n" + canonical_headers + "\n" + signed_headers + "\n" + payload_hash
    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = datetime.datetime.utcnow().strftime('%Y%m%d') + "/" + region + "/" + service + "/" + "aws4_request"
    string_to_sign = algorithm + "\n" + datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S') + "Z\n" + credential_scope + "\n" + hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()

    # Signing key
    def sign(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
    k_date = sign(("AWS4" + PA_SECRET_KEY).encode('utf-8'), datetime.datetime.utcnow().strftime('%Y%m%d'))
    k_region = sign(k_date, region)
    k_service = sign(k_region, service)
    signing_key = sign(k_service, "aws4_request")

    # Signature
    signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    # Authorization header
    authorization_header = algorithm + " Credential=" + PA_ACCESS_KEY + "/" + credential_scope + ", SignedHeaders=" + signed_headers + ", Signature=" + signature

    # Request
    headers = {
        "Content-Type": "application/json",
        "X-Amz-Date": datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S Z'),
        "X-Amz-Target": f"com.amazon.paapi5.v1.ProductAdvertisingAPIv5.{operation}",
        "Authorization": authorization_header,
        "Host": host
    }

    payload = {"SearchIndex": "All", "Keywords": keywords, "Resources": [
        "ItemInfo.Title", "Images.Primary.Medium", "Images.Primary.Large", "DetailPageURL"
    ], "ItemCount": 1, "PartnerTag": AFFILIATE_TAG, "PartnerType": "Associates", "Marketplace": "www.amazon.com"}

    resp = requests.post(f"https://{host}{uri}", headers=headers, json=payload)
    if resp.status_code == 200:
        return resp.json()
    print("PA API error:", resp.status_code, resp.text)
    return None

def get_trending_products(num=5):
    prompt = f"""
    Give exactly {num} completely different trending Amazon products right now (December 2025). Mix categories: gadgets, beauty, kitchen, cozy, fitness.
    NEVER number them. NEVER use dashes or bullets at the start.
    Format ONLY:
    Product Name | Amazon Search Term (exact, 4-8 words)
    Example:
    Cordless Water Flosser | cordless water flosser
    """
    response = generate_with_groq(prompt)
    products = []
    for line in response.split("\n"):
        line = line.strip()
        if "|" in line and not line[0].isdigit() and not line.startswith(("-", "•", "*")):
            parts = [p.strip() for p in line.split("|", 1)]
            if len(parts) == 2:
                products.append(parts)
    return products[:num]

def generate_review(product_name, search_term):
    # Use PA API to get real product data
    api_result = pa_api_signed_request("SearchItems", search_term, 1)
    if api_result and 'SearchResult' in api_result and api_result['SearchResult'].get('Items'):
        item = api_result['SearchResult']['Items']['Item']
        title = item['ItemInfo']['Title']['DisplayValue']
        image_url = item['Images']['Primary']['Medium']['URL']
        direct_link = item['DetailPageURL']
    else:
        title = product_name
        image_url = "https://via.placeholder.com/800x600/0d6efd/ffffff.png?text=No+Image"
        direct_link = f"https://www.amazon.com/s?k={search_term.replace(' ', '+')}&tag={AFFILIATE_TAG}"

    # Generate review with Groq
    prompt = f"""
    Write a fun, honest 800-1200 word review for "{title}" as @snapreviews_.
    Sections with <h2>: Why It's Trending, Pros & Cons (bullets), Features, Who It's For, Verdict.
    End with a big blue button link to {direct_link}.
    NEVER number anything.
    """
    content = generate_with_groq(prompt)

    filename = f"{title.lower()[:100].replace(' ', '-').replace('/', '-')}.html"
    filepath = os.path.join(REVIEWS_DIR, filename)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} Review 2025 – SnapReviews</title>
    <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>{title} Review 2025</h1>
            <p>Published {datetime.date.today()}</p>
        </header>
        <main>
            <img src="{image_url}" alt="{title}" style="width:100%;max-width:800px;border-radius:16px;margin:30px 0;box-shadow:0 8px 30px rgba(0,0,0,0.15);">
            {content}
            <a href="{direct_link}" class="btn" rel="nofollow">Check Price on Amazon →</a>
        </main>
        <footer>
            <p>Affiliate link – may earn commission</p>
        </footer>
    </div>
</body>
</html>"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filename, title, image_url

def update_homepage(new_reviews):
    homepage = os.path.join(SITE_DIR, "index.html")
    with open(homepage, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    grid = soup.find("div", id="reviews")
    for filename, name, img in reversed(new_reviews):
        card = soup.new_tag("div", attrs={"class": "review-card"})
        img_tag = soup.new_tag("img", src=img, alt=name)
        img_tag['style'] = "width:100%;height:400px;object-fit:cover;border-radius:16px;"
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
        f.write(str(soup.prettify()))

# === RUN IT ===
products = get_trending_products(5)
new_reviews = []
for name, term in products:
    filename, title, img = generate_review(name, term)
    new_reviews.append((filename, title, img))
    print(f"Created: {title}")

update_homepage(new_reviews)
print("All done! Commit & push – real Amazon product images and direct links are now live.")
