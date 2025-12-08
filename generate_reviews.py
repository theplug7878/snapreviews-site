import os
from bs4 import BeautifulSoup
import datetime
from amazon_paapi import AmazonApi

# === SECURE CREDENTIALS (from GitHub Secrets) ===
ACCESS_KEY = os.getenv("PA_ACCESS_KEY")
SECRET_KEY = os.getenv("PA_SECRET_KEY")
PARTNER_TAG = os.getenv("AFFILIATE_TAG", "snapxacc-20")

if not ACCESS_KEY or not SECRET_KEY:
    raise ValueError("PA API credentials not set in GitHub secrets")

amazon = AmazonApi(
    key=ACCESS_KEY,
    secret=SECRET_KEY,
    tag=PARTNER_TAG,
    country="US",  # Change if you're in another marketplace
    throttling=1.0  # 1 request per second to stay safe
)

SITE_DIR = "."
REVIEWS_DIR = os.path.join(SITE_DIR, "reviews")
os.makedirs(REVIEWS_DIR, exist_ok=True)

def generate_with_groq(prompt):
    # Your existing Groq code here (unchanged)
    # ... keep your current generate_with_groq function ...

def get_trending_products(num=5):
    prompt = f"""
    Give exactly {num} completely different trending Amazon products right now (December 2025). Mix categories: gadgets, beauty, kitchen, cozy, fitness.
    NEVER number them. Format ONLY:
    Product Name | Amazon Search Term (exact, 4-8 words) | Why It's Trending (1-2 sentences)
    Example:
    Ninja Air Fryer | ninja air fryer max xl | Viral on TikTok for oil-free cooking...
    """
    response = generate_with_groq(prompt)
    products = []
    for line in response.split("\n"):
        line = line.strip()
        if "|" in line and not line[0].isdigit() and not line.startswith(("-", "•", "*")):
            parts = [p.strip() for p in line.split("|", 2)]
            if len(parts) == 3:
                products.append(parts)
    return products[:num]

def generate_review(product_name, search_term, why_trending):
    # Search Amazon for the product
    try:
        result = amazon.search_items(keywords=search_term, item_count=1)
        item = result.items[0] if result.items else None
    except Exception as e:
        print(f"PA API error for {search_term}: {e}")
        item = None

    if item:
        title = item.item_info.title.display_value if item.item_info.title else product_name
        image_url = item.images.primary.large.url if item.images.primary.large else f"https://via.placeholder.com/800x600/0d6efd/ffffff.png?text={product_name.replace(' ', '+')}"
        direct_link = item.detail_page_url  # Already has your affiliate tag
    else:
        title = product_name
        image_url = f"https://via.placeholder.com/800x600/0d6efd/ffffff.png?text={product_name.replace(' ', '+')}"
        direct_link = f"https://www.amazon.com/s?k={search_term.replace(' ', '+')}&tag={AFFILIATE_TAG}"

    prompt = f"""
    Write a full 800-1200 word SEO-optimized review for "{title}" in December 2025.
    Style: honest, fun, satisfying like @snapreviews_.
    Sections with <h2>: Why It's Trending, Pros & Cons (bullets), Features, Who It's For, Verdict.
    Include: {why_trending}
    End with a big blue button link to {direct_link}.
    NEVER number anything in the title or content.
    """
    content = generate_with_groq(prompt)

    filename = f"{title.lower()[:100].replace(' ', '-').replace('/', '-')}.html"  # Safe filename
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
for name, term, trending in products:
    filename, title, img = generate_review(name, term, trending)
    new_reviews.append((filename, title, img))
    print(f"Created: {title}")

update_homepage(new_reviews)
print("All done! Commit & push – your site now has real Amazon product images and direct links.")
