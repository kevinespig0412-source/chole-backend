"""
Chole Podcast Generator
Creates daily 3-minute mining news briefing
Generates script with GPT-4, converts to audio with OpenAI TTS
Runs daily at 6 AM ET via GitHub Actions
"""

import os
import json
from datetime import datetime
from openai import OpenAI
import firebase_admin
from firebase_admin import credentials, firestore, storage

# Initialize Firebase
def init_firebase():
    if not firebase_admin._apps:
        service_account = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT', '{}'))
        if service_account:
            cred = credentials.Certificate(service_account)
        else:
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'chole-mining.firebasestorage.app'
        })
    return firestore.client()

# Initialize OpenAI
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))


def get_todays_news(db):
    """Fetch today's news from Firestore"""
    try:
        doc = db.collection("daily_news").document("latest").get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error fetching news: {e}")
        return None


def generate_podcast_script(news_data):
    """Generate a 3-minute podcast script from today's news"""
    
    # Prepare news summaries
    today_news = news_data.get("today", [])[:5]
    
    news_items = "\n".join([
        f"- {article['headline']} ({article['source']}): {article.get('summary', '')}"
        for article in today_news
    ])
    
    prompt = f"""You are the host of "Chole Mining Briefing", a daily 3-minute podcast for mining industry professionals and investors.

Today's date: {datetime.now().strftime("%B %d, %Y")}

Today's top mining news:
{news_items}

Write a podcast script that:
1. Opens with a brief, professional greeting (5 seconds)
2. Covers the top 3-4 most important stories with expert analysis (2.5 minutes)
3. Closes with a brief sign-off (10 seconds)

Style guidelines:
- Professional but engaging tone
- Include specific numbers, percentages, and company names
- Provide context on why each story matters
- Natural speaking rhythm with occasional pauses marked as "..."
- Target 450-500 words (approximately 3 minutes when spoken)
- Do NOT include sound effects, music cues, or production notes
- Write in natural spoken English, not overly formal

Begin the script directly with the greeting, no titles or headers."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=800
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Script generation error: {e}")
        return None


def generate_audio(script, output_path):
    """Convert script to audio using OpenAI TTS"""
    try:
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice="onyx",  # Deep, professional male voice
            input=script,
            speed=1.0
        )
        
        # Save to file
        response.stream_to_file(output_path)
        print(f"Audio saved to {output_path}")
        return True
    except Exception as e:
        print(f"TTS error: {e}")
        return False


def upload_to_storage(local_path, remote_path):
    """Upload file to Firebase Storage"""
    try:
        bucket = storage.bucket()
        blob = bucket.blob(remote_path)
        blob.upload_from_filename(local_path)
        
        # Make publicly accessible
        blob.make_public()
        
        print(f"Uploaded to {blob.public_url}")
        return blob.public_url
    except Exception as e:
        print(f"Upload error: {e}")
        return None


def save_podcast_metadata(db, date, script, audio_url, duration_seconds=180):
    """Save podcast metadata to Firestore"""
    data = {
        "date": date,
        "title": f"Mining Daily Briefing - {datetime.now().strftime('%B %d, %Y')}",
        "script": script,
        "audioUrl": audio_url,
        "duration": duration_seconds,
        "durationFormatted": f"{duration_seconds // 60}:{duration_seconds % 60:02d}",
        "createdAt": firestore.SERVER_TIMESTAMP
    }
    
    try:
        # Save by date
        db.collection("daily_media").document(date).set(data)
        # Save as latest
        db.collection("daily_media").document("latest").set(data)
        print(f"Metadata saved for {date}")
    except Exception as e:
        print(f"Metadata save error: {e}")


def main():
    """Main execution function"""
    print(f"Starting Chole Podcast Generator at {datetime.now().isoformat()}")
    
    # Initialize
    db = init_firebase()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Get today's news
    print("Fetching today's news...")
    news_data = get_todays_news(db)
    
    if not news_data:
        print("No news data found. Exiting.")
        return
    
    # Generate script
    print("Generating podcast script...")
    script = generate_podcast_script(news_data)
    
    if not script:
        print("Script generation failed. Exiting.")
        return
    
    print("\n--- PODCAST SCRIPT ---")
    print(script)
    print("--- END SCRIPT ---\n")
    
    # Generate audio
    print("Generating audio...")
    local_audio_path = f"/tmp/podcast_{today}.mp3"
    
    if generate_audio(script, local_audio_path):
        # Upload to Firebase Storage
        print("Uploading to Firebase Storage...")
        remote_path = f"podcasts/{today}/briefing.mp3"
        audio_url = upload_to_storage(local_audio_path, remote_path)
        
        if audio_url:
            # Save metadata
            save_podcast_metadata(db, today, script, audio_url)
            print(f"\nPodcast published successfully!")
            print(f"Audio URL: {audio_url}")
        else:
            print("Failed to upload audio")
    else:
        print("Failed to generate audio")
    
    # Cleanup
    if os.path.exists(local_audio_path):
        os.remove(local_audio_path)
    
    print(f"\nCompleted at {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
