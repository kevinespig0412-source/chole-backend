"""
Chole News Fetcher
Fetches mining news from RSS feeds, curates with AI, generates expert bullets
Runs daily at 6 AM ET via GitHub Actions
"""

import os
import json
import feedparser
import requests
from datetime import datetime, timedelta
from openai import OpenAI
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
def init_firebase():
    if not firebase_admin._apps:
        # For GitHub Actions, use service account from secrets
        service_account = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT', '{}'))
        if service_account:
            cred = credentials.Certificate(service_account)
        else:
            # Local development - use default credentials
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    return firestore.client()

# Initialize OpenAI
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# RSS Feed Sources for Mining News
RSS_FEEDS = [
    # Major Mining News
    {"url": "https://www.mining.com/feed/", "name": "Mining.com"},
    {"url": "https://www.kitco.com/news/rss/mining.rss", "name": "Kitco Mining"},
    {"url": "https://www.reuters.com/news/archive/miningNews?view=rss", "name": "Reuters Mining"},
    {"url": "https://www.bloomberg.com/feeds/bpol/sitemap_news.xml", "name": "Bloomberg"},
    
    # Junior Mining
    {"url": "https://ceo.ca/api/sedi/rss", "name": "CEO.CA"},
    {"url": "https://www.juniorminingnetwork.com/feed", "name": "Junior Mining Network"},
    
    # Commodity Specific
    {"url": "https://www.gold.org/feed/rss.xml", "name": "World Gold Council"},
    {"url": "https://www.silverinstitute.org/feed/", "name": "Silver Institute"},
]

# Keywords for commodity filtering
COMMODITY_KEYWORDS = {
    "gold": ["gold", "aurum", "au", "bullion", "precious metal", "gold mining", "gold producer"],
    "silver": ["silver", "ag", "silver mining", "silver producer"],
    "copper": ["copper", "cu", "copper mining", "red metal"],
    "critical_minerals": ["lithium", "nickel", "cobalt", "manganese", "graphite", "battery metal", "ev metal"],
    "uranium": ["uranium", "nuclear", "u3o8", "yellowcake", "nuclear fuel"],
    "rare_earth": ["rare earth", "ree", "neodymium", "praseodymium", "dysprosium", "lanthanide"]
}

# Region keywords
REGION_KEYWORDS = {
    "usa": ["united states", "usa", "us", "nevada", "arizona", "alaska", "colorado", "utah", "wyoming", "american"],
    "canada": ["canada", "canadian", "ontario", "quebec", "british columbia", "bc", "yukon", "nunavut", "tsx", "tsxv"],
    "australia": ["australia", "australian", "asx", "western australia", "queensland", "nsw"],
    "china": ["china", "chinese", "beijing", "shanghai", "inner mongolia"],
    "latin_america": ["chile", "peru", "argentina", "brazil", "mexico", "colombia", "latin america", "south america"],
    "africa": ["africa", "african", "congo", "drc", "south africa", "mali", "ghana", "tanzania", "zambia", "namibia"]
}


def fetch_all_feeds():
    """Fetch articles from all RSS feeds"""
    all_articles = []
    
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:20]:  # Limit per feed
                # Parse date
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published = datetime(*entry.updated_parsed[:6])
                else:
                    published = datetime.now()
                
                # Only include articles from last 24 hours
                if datetime.now() - published > timedelta(hours=36):
                    continue
                
                article = {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", entry.get("description", ""))[:500],
                    "source": feed_info["name"],
                    "published": published.isoformat(),
                    "image": extract_image(entry)
                }
                all_articles.append(article)
        except Exception as e:
            print(f"Error fetching {feed_info['name']}: {e}")
    
    return all_articles


def extract_image(entry):
    """Extract image URL from feed entry"""
    # Try media:content
    if hasattr(entry, 'media_content') and entry.media_content:
        return entry.media_content[0].get('url', '')
    
    # Try enclosures
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if 'image' in enc.get('type', ''):
                return enc.get('href', '')
    
    # Try to extract from summary/content
    import re
    if hasattr(entry, 'summary'):
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', entry.summary)
        if img_match:
            return img_match.group(1)
    
    # Default placeholder
    return "https://images.unsplash.com/photo-1578319439584-104c94d37305?w=800"


def filter_by_commodity(articles, commodity):
    """Filter articles by commodity keywords"""
    keywords = COMMODITY_KEYWORDS.get(commodity, [])
    filtered = []
    
    for article in articles:
        text = (article["title"] + " " + article["summary"]).lower()
        if any(kw.lower() in text for kw in keywords):
            filtered.append(article)
    
    return filtered


def filter_by_region(articles, region):
    """Filter articles by region keywords"""
    keywords = REGION_KEYWORDS.get(region, [])
    filtered = []
    
    for article in articles:
        text = (article["title"] + " " + article["summary"]).lower()
        if any(kw.lower() in text for kw in keywords):
            filtered.append(article)
    
    return filtered


def curate_top_articles(articles, count=5, category="general"):
    """Use AI to select the most important articles"""
    if not articles:
        return []
    
    # Prepare article summaries for AI
    article_list = "\n".join([
        f"{i+1}. {a['title']} ({a['source']})\n   Summary: {a['summary'][:200]}..."
        for i, a in enumerate(articles[:30])
    ])
    
    prompt = f"""You are a mining industry expert editor. Select the {count} most important and newsworthy articles for {category}.

Prioritize:
- Major price movements or market events
- Significant M&A activity
- Important drill results or discoveries
- Policy/regulatory changes affecting mining
- Production updates from major miners

Articles:
{article_list}

Return ONLY a JSON array of the article numbers (1-indexed) you selected, e.g., [1, 5, 12, 18, 23]
Select exactly {count} articles."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )
        
        selected_indices = json.loads(response.choices[0].message.content)
        return [articles[i-1] for i in selected_indices if 0 < i <= len(articles)]
    except Exception as e:
        print(f"AI curation error: {e}")
        # Fallback: return first N articles
        return articles[:count]


def generate_expert_bullets(article):
    """Generate 3 expert-level bullet points for an article"""
    prompt = f"""You are a senior mining industry analyst. Generate exactly 3 expert-level bullet points for this mining news article.

Title: {article['title']}
Source: {article['source']}
Summary: {article['summary']}

Requirements:
- Each bullet should be 2-3 sentences with specific details
- Include numbers, percentages, or specific data when available
- Write for sophisticated investors/industry professionals
- Reference specific companies, projects, or technical details
- Provide context on why this matters to the industry

Return as JSON array of 3 objects with "text" and "source" fields:
[
  {{"text": "First expert bullet point...", "source": "{article['source']}"}},
  {{"text": "Second expert bullet point...", "source": "{article['source']}"}},
  {{"text": "Third expert bullet point...", "source": "{article['source']}"}}
]"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=500
        )
        
        bullets = json.loads(response.choices[0].message.content)
        return bullets
    except Exception as e:
        print(f"Bullet generation error: {e}")
        return [
            {"text": article['summary'][:200], "source": article['source']},
            {"text": "Additional details pending...", "source": article['source']},
            {"text": "Full analysis available in source article.", "source": article['source']}
        ]


def generate_article_summary(article):
    """Generate a concise summary for an article"""
    prompt = f"""Summarize this mining news article in 1-2 sentences for industry professionals:

Title: {article['title']}
Content: {article['summary']}

Be specific and include key numbers or details. Max 150 characters."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except:
        return article['summary'][:150]


def categorize_article(article):
    """Determine the category of an article"""
    text = (article['title'] + " " + article['summary']).lower()
    
    if any(word in text for word in ['drill', 'intercept', 'assay', 'metres', 'meters', 'grade']):
        return "Drill Results"
    elif any(word in text for word in ['acquire', 'merger', 'takeover', 'bid', 'deal', 'm&a']):
        return "M&A"
    elif any(word in text for word in ['price', 'spot', 'futures', 'trading', 'market']):
        return "Markets"
    elif any(word in text for word in ['production', 'output', 'guidance', 'quarterly']):
        return "Production"
    elif any(word in text for word in ['policy', 'regulation', 'government', 'permit', 'approval']):
        return "Policy"
    elif any(word in text for word in ['exploration', 'discovery', 'target', 'prospective']):
        return "Exploration"
    else:
        return "Industry"


def process_articles(articles):
    """Process articles with AI-generated content"""
    processed = []
    
    for article in articles:
        try:
            processed_article = {
                "id": hash(article['link']) % 10**9,
                "headline": article['title'],
                "link": article['link'],
                "source": article['source'],
                "sourceCount": 1,
                "image": article['image'],
                "published": article['published'],
                "category": categorize_article(article),
                "summary": generate_article_summary(article),
                "bullets": generate_expert_bullets(article)
            }
            processed.append(processed_article)
            print(f"Processed: {article['title'][:50]}...")
        except Exception as e:
            print(f"Error processing article: {e}")
    
    return processed


def save_to_firestore(db, collection, data, doc_id=None):
    """Save data to Firestore"""
    try:
        if doc_id:
            db.collection(collection).document(doc_id).set(data)
        else:
            db.collection(collection).add(data)
        print(f"Saved to {collection}/{doc_id or 'auto'}")
    except Exception as e:
        print(f"Firestore save error: {e}")


def main():
    """Main execution function"""
    print(f"Starting Chole News Fetcher at {datetime.now().isoformat()}")
    
    # Initialize
    db = init_firebase()
    
    # Fetch all articles
    print("Fetching RSS feeds...")
    all_articles = fetch_all_feeds()
    print(f"Fetched {len(all_articles)} articles")
    
    # Get today's date for document ID
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Process "Today" - top 5 overall
    print("\nProcessing Today's Top News...")
    today_articles = curate_top_articles(all_articles, count=5, category="mining industry today")
    today_processed = process_articles(today_articles)
    
    # Process each commodity
    commodity_news = {}
    for commodity in COMMODITY_KEYWORDS.keys():
        print(f"\nProcessing {commodity} news...")
        filtered = filter_by_commodity(all_articles, commodity)
        if filtered:
            curated = curate_top_articles(filtered, count=5, category=f"{commodity} mining")
            commodity_news[commodity] = process_articles(curated)
        else:
            commodity_news[commodity] = []
    
    # Process each region
    region_news = {}
    for region in REGION_KEYWORDS.keys():
        print(f"\nProcessing {region} news...")
        filtered = filter_by_region(all_articles, region)
        if filtered:
            curated = curate_top_articles(filtered, count=5, category=f"{region} mining")
            region_news[f"region_{region}"] = process_articles(curated)
        else:
            region_news[f"region_{region}"] = []
    
    # Process Junior Mining news
    print("\nProcessing Junior Mining news...")
    junior_keywords = ["junior", "explorer", "tsx-v", "tsxv", "cse", "asx", "small cap", "drill result"]
    junior_articles = [a for a in all_articles if any(kw in (a['title'] + a['summary']).lower() for kw in junior_keywords)]
    junior_curated = curate_top_articles(junior_articles, count=5, category="junior mining exploration")
    junior_processed = process_articles(junior_curated)
    
    # Save to Firestore
    print("\nSaving to Firestore...")
    
    # Save daily news
    daily_data = {
        "date": today,
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "today": today_processed,
        "junior": junior_processed,
        **commodity_news,
        **region_news
    }
    save_to_firestore(db, "daily_news", daily_data, today)
    
    # Also save as "latest" for easy access
    save_to_firestore(db, "daily_news", daily_data, "latest")
    
    print(f"\nCompleted at {datetime.now().isoformat()}")
    print(f"Processed: {len(today_processed)} today, {len(junior_processed)} junior")
    for commodity, articles in commodity_news.items():
        print(f"  {commodity}: {len(articles)} articles")


if __name__ == "__main__":
    main()
