import requests
import os
from bs4 import BeautifulSoup
import datetime

# === SECURE KEY HANDLING ===
# Key comes from GitHub Secrets (or local environment for testing)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is not set. Add it as a GitHub secret or set it locally for testing.")

AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "snapxacc-20")  # fallback if not set as secret

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
    It's December 07, 2025. Based on current viral Amazon trends (TikTok gadgets, cozy essentials, kitchen tools, etc.),
    give exactly {num} trending products in this format only:
    Product Name | Amazon Search Term (exact, 4-8 words) | Why It's Trending (1-2 sentences)
    Example:
    Stanley Quencher Tumbler | stanley quencher tumbler 40 oz | Still the #1 hydration status symbol on TikTok...
    """
    response = generate_with_groq(prompt)
    products = []
    for line in response.split("\n"):
        if "|" in line:
            parts = [p.strip() for p in line.split("|", 2)]
            if len(parts) == 3:
                products.append(parts)
    return products

def generate_review(product_name, search_term, why_trending):
    prompt = f"""
    Write a full 800-1200 word SEO-optimized review for the Amazon product "{product_name}" in December 2025.
    Use the clean SnapReviews style: honest, fun, satisfying.
    Sections with <h2>: Why It's Trending, Pros & Cons (bullets), Features, Who It's For, Verdict.
    Include the trending reason: {why_trending}
    End with a big blue button link [AFFILIATE_LINK].
    Use real-sounding opinions like @snapreviews_.
    """
    content = generate_with_groq(prompt)
    link = f"https://www.amazon.com/s?k={search_term.replace(' ', '+')}&tag={AFFILIATE_TAG}"
    content = content.replace("[AFFILIATE_LINK]", link)

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
            <div style="background:#eee;height:400px;margin:30px 0;border-radius:12px;text-align:center;padding-top:180px;color:#999;font-size:1.2rem;">
                Product Image/Video Here
            </div>
            {content}
            <a href="{link}" class="btn" rel="nofollow">Check Price on Amazon →</a>
        </main>
        <footer>
            <p>Affiliate link – may earn commission</p>
        </footer>
    </div>
</body>
</html>"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filename, product_name

def update_homepage(new_reviews):
    homepage = os.path.join(SITE_DIR, "index.html")
    with open(homepage, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    grid = soup.find("div", id="reviews")
    for filename, name in reversed(new_reviews):  # newest on top
        card = soup.new_tag("div", attrs={"class": "review-card"})
        placeholder = soup.new_tag("div", style="background:#eee;height:400px;border-radius:12px;")
        card.append(placeholder)
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
products = get_trending_products(5)  # Change number here
new_reviews = []
for name, term, trending in products:
    filename, title = generate_review(name, term, trending)
    new_reviews.append((filename, title))
    print(f"Created: {title}")

update_homepage(new_reviews)
print("All done! Commit & push – your site will update automatically.")
