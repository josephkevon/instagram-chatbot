from instagrapi import Client
from openai import OpenAI
import time
import random
import os
import json
from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, RateLimitError

USERNAME = # your Instagram username
PASSWORD = # your Instagram password

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="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",
)

# Shortened system prompt
SYSTEM_PROMPT = """You are a master salesman helping me respond to potential clients. I'm selling an AI bot that sends Instagram DMs and books meetings automatically.

Key points about my service:
- Bot finds ideal customers on Instagram using keywords/competitor scraping
- Sends hundreds of DMs automatically
- AI handles conversations and books meetings when people reply
- Client gets qualified meetings without any manual work

Your job:
- Reply in 1-2 sentences + ask a question
- Match their tone, sound like an old friend helping them
- Don't be pushy or salesy
- Goal is to book a meeting (but take your time)
- Use simple 5th grade level words
- Handle objections by asking "can I ask a question?" or "can I make a suggestion?"

Common objections: "need to think", "not interested", "tried before", "sounds too good"
Handle with: "Before I lose you, is it that you're unsure this will work?" / "Let's do a quick 5-10 min call"

Reply only with the response, nothing else."""

def chat(prompt, conversation_log=""):
    # Limit conversation log to last 400 characters to save tokens
    if len(conversation_log) > 400:
        conversation_log = "..." + conversation_log[-400:]

    full_prompt = f"{SYSTEM_PROMPT}\n\nConversation history: {conversation_log}\n\nTheir message: {prompt}\n\nYour reply:"

    try:
        completion = client.chat.completions.create(
            model="gpt-5",
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=150  # Reduced from 200 to save credits
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        error_msg = str(e).lower()
        if "402" in error_msg or "credits" in error_msg:
            print("❌ OpenRouter credits exhausted! Please add credits at https://openrouter.ai/settings/credits")
            return "Thanks for your message! I'll get back to you soon."
        else:
            print(f"❌ Chat API error: {e}")
            return "Thanks for reaching out! Let me get back to you with more details."

def safe_get_username(cl, user_id, max_retries=3):
    """Safely get username with fallback and retry logic"""
    for attempt in range(max_retries):
        try:
            user_info = cl.user_info(user_id)
            return user_info.username
        except KeyError as e:
            if 'data' in str(e):
                print(f"⚠️ Instagram GraphQL 'data' key error (attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    time.sleep(random.randint(10, 30))  # Wait before retry
                    continue
        except Exception as e:
            print(f"⚠️ Error fetching user info (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(random.randint(5, 15))
                continue
    
    # Fallback to user ID if all attempts fail
    return f"user_{user_id}"

def safe_instagram_login():
    """Login with better error handling and session management"""
    cl = Client()
    SETTINGS_PATH = "insta_session.json"

    # Configure client settings for better stability
    cl.delay_range = [3, 6]  # Increased delays between requests

    # Try loading session
    if os.path.exists(SETTINGS_PATH):
        try:
            print("🔄 Loading saved session...")
            cl.load_settings(SETTINGS_PATH)
            cl.login(USERNAME, PASSWORD)
            print("✅ Session loaded successfully")
            return cl
        except Exception as e:
            print(f"⚠️ Failed to load session: {e}")
            print("🔄 Logging in fresh...")

    # Fresh login with retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            cl.login(USERNAME, PASSWORD)
            cl.dump_settings(SETTINGS_PATH)
            print("✅ Fresh login successful")
            return cl
        except Exception as e:
            print(f"❌ Login attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 30
                print(f"⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                raise e

def get_threads_with_retry(cl, max_retries=3):
    """Get threads with exponential backoff retry"""
    for attempt in range(max_retries):
        try:
            threads = cl.direct_threads(amount=5)
            return threads
        except Exception as e:
            error_msg = str(e).lower()

            if "500" in error_msg or "server" in error_msg:
                wait_time = (2 ** attempt) * 10 + random.randint(5, 15)  # Exponential backoff
                print(f"🔄 Instagram server error (attempt {attempt + 1}). Waiting {wait_time}s...")
                time.sleep(wait_time)
            elif "rate limit" in error_msg or "429" in error_msg:
                wait_time = 300 + random.randint(60, 180)  # 5-8 minutes for rate limits
                print(f"⏱️ Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ Unexpected error: {e}")
                time.sleep(60)

            if attempt == max_retries - 1:
                raise e

def send_message_with_retry(cl, message, user_ids, max_retries=3):
    """Send message with retry logic"""
    for attempt in range(max_retries):
        try:
            cl.direct_send(message, user_ids)
            return True
        except Exception as e:
            error_msg = str(e).lower()

            if "500" in error_msg:
                wait_time = (attempt + 1) * 15
                print(f"🔄 Send failed (attempt {attempt + 1}). Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ Send error: {e}")
                time.sleep(30)

            if attempt == max_retries - 1:
                print("❌ Failed to send message after all retries")
                return False

# Initialize Instagram client
cl = safe_instagram_login()

# Store already replied message IDs
seen_messages = set()

# Adaptive polling intervals
base_interval = 180  # Increased to 3 minutes to reduce API calls
max_interval = 600   # Max 10 minutes
current_interval = base_interval
consecutive_errors = 0

print("🤖 Live Instagram DM bot is now running...")
print(f"⏱️ Checking for messages every {current_interval} seconds")
print("💳 Note: Check OpenRouter credits at https://openrouter.ai/settings/credits")

while True:
    try:
        # Get latest threads with retry
        threads = get_threads_with_retry(cl)

        # Reset error counter on success
        consecutive_errors = 0
        current_interval = max(base_interval, current_interval - 30)  # Gradually reduce interval

        message_found = False

        for thread in threads:
            if not thread.messages:
                continue

            message = thread.messages[0]  # Most recent message only
            msg_id = message.id
            msg_text = message.text.lower() if message.text else ""

            # Ignore your own messages
            if message.user_id == cl.user_id:
                continue

            # Only reply to new messages
            if msg_id not in seen_messages:
                seen_messages.add(msg_id)
                message_found = True

                # Use safe username fetching
                sender = safe_get_username(cl, message.user_id)

                print(f"💬 {sender} said: {msg_text}")

                # Handle log files
                log_filename = f"{sender}log.txt"
                if not os.path.exists(log_filename):
                    with open(log_filename, "w") as initial_msg:
                        initial_msg.write("""Hey, are you guys able to handle more clients? 

 we are doing a free 14-day service for businesses like yours.
 our system sends 150 DMs a day to people likely to need your service.
 are you open to that?
""")

                # Log the incoming message
                with open(log_filename, "a") as log_file:
                    log_file.write(f"{sender}: {msg_text}\n")

                if sender == USERNAME:
                    print("Skipping own message.")
                    continue

                if msg_text == "exit":
                    continue

                # Read conversation log
                try:
                    with open(log_filename, "r") as log_file:
                        log_content = log_file.read()
                        if len(log_content) > 800:  # Reduced from 1000 to save tokens
                            log_content = "..." + log_content[-800:]
                except FileNotFoundError:
                    log_content = ""

                # Generate reply
                try:
                    reply = chat(msg_text, log_content)
                    print("🤖 Bot:", reply)

                    # Send reply with retry
                    if send_message_with_retry(cl, reply, [message.user_id]):
                        # Log the reply only if sent successfully
                        with open(log_filename, "a") as log_file:
                            log_file.write(f"Bot: {reply}\n")
                        print("✅ Message sent successfully")
                    else:
                        print("❌ Failed to send message")

                except Exception as e:
                    print(f"❌ Error generating/sending reply: {e}")

                # Add delay between processing messages
                time.sleep(random.randint(10, 20))  # Increased delay

        if message_found:
            print(f"✅ Processed messages. Next check in {current_interval} seconds")
        else:
            print(f"📭 No new messages. Next check in {current_interval} seconds")

        # Wait before checking again
        time.sleep(current_interval)

    except Exception as e:
        consecutive_errors += 1
        error_msg = str(e).lower()

        if "500" in error_msg:
            # Instagram server issues - increase interval significantly
            current_interval = min(max_interval, current_interval + 60)
            wait_time = current_interval + random.randint(30, 120)
            print(f"🔴 Instagram server issues detected. Waiting {wait_time} seconds...")
            print(f"📈 Increased polling interval to {current_interval} seconds")
        elif "login" in error_msg or "challenge" in error_msg:
            print("🔐 Login issue detected. Attempting re-login...")
            try:
                cl = safe_instagram_login()
                wait_time = 60
            except Exception as login_error:
                print(f"❌ Re-login failed: {login_error}")
                wait_time = 600  # Wait 10 minutes before trying again
        else:
            wait_time = min(300, 30 * consecutive_errors)  # Cap at 5 minutes
            print(f"⚠️ Error (#{consecutive_errors}): {e}")
            print(f"⏳ Waiting {wait_time} seconds before retry...")


        time.sleep(wait_time)
