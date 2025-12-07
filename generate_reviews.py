import requests
import os
from bs4 import BeautifulSoup
import datetime
import re

# === SECURE KEY HANDLING ===
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is not set. Add it as a GitHub secret or set it locally for testing.")

AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "snapxacc-20")

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
    return ""

def get_trending_products(num=5):
    prompt = f"""
    It's December 07, 2025. Give exactly {num} currently trending Amazon products (viral gadgets, cozy items, kitchen tools, etc.).
    Format ONLY:
    Product Name | Exact Amazon Search Term (4-8 words)
    Example:
    Ninja Air Fryer | ninja air fryer max xl
    """
    response = generate_with_groq(prompt)
    products = []
    for line in response.split("\n"):
        if "|" in line:
            parts = [p.strip() for p in line.split("|", 1)]
            if len(parts) == 2:
                products.append(parts)
    return products

def get_amazon_product_details(search_term):
    """Fetch the top Amazon result's direct URL and main image."""
    search_url = f"https://www.amazon.com/s?k={search_term.replace(' ', '+')}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        first_result = soup.find("div", {"data-component-type": "s-search-result"})
        if not first_result:
            return None, None

        # Get direct product link
        link_tag = first_result.find("a", class_="a-link-normal s-no-outline")
        if link_tag and link_tag.get("href"):
            product_url = "https://www.amazon.com" + link_tag["href"].split("/ref")[0]
            product_url = product_url + f"?tag={AFFILIATE_TAG}"

        # Get main image
        img_tag = first_result.find("img", class_="s-image")
        image_url = img_tag["src"] if img_tag and img_tag.get("src") else ""

        return product_url, image_url
    except:
        return None, None

def generate_review(product_name, search_term):
    product_url, image_url = get_amazon_product_details(search_term)
    if not product_url:
        product_url = f"https://www.amazon.com/s?k={search_term.replace(' ', '+')}&tag={AFFILIATE_TAG}"
        image_url = "https://via.placeholder.com/600x600/eee?text=Product+Image"

    prompt = f"""
    Write a full 800-1200 word SEO-optimized review for the Amazon product "{product_name}" in December 2025.
    Use the clean SnapReviews style: honest, fun, satisfying.
    Sections with <h2>: Why It's Trending, Pros & Cons (bullets), Features, Who It's For, Verdict.
    End with a big blue button using this exact link: {product_url}
    """
    content = generate_with_groq(prompt)

    filename = f"{product_name.lower().replace(' ', '-').replace('/', '-')}.html"
    filepath = os.path.join(REVIEWS_DIR, filename)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{product_name} Review 2025 – SnapReviews</title>
    <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>{product_name} Review 2025</h1>
            <p>Published {datetime.date.today()}</p>
        </header>
        <main>
            <img src="{image_url}" alt="{product_name}" style="width:100%;max-width:600px;border-radius:12px;margin:30px 0;">
            {content}
            <a href="{product_url}" class="btn" rel="nofollow">Check Price on Amazon →</a>
        </main>
        <footer>
            <p>Affiliate link – may earn commission</p>
        </footer>
    </div>
</body>
</html>"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filename, product_name, image_url

def update_homepage(new_reviews):
    homepage = os.path.join(SITE_DIR, "index.html")
    with open(homepage, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    grid = soup.find("div", id="reviews")
    for filename, name, img in reversed(new_reviews):
        card = soup.new_tag("div", attrs={"class": "review-card"})
        img_tag = soup.new_tag("img", src=img, alt=name)
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
print("All done! Commit & push – your site now has real product images and direct links.")
