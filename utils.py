import sqlite3
from translate import Translator as TranslateLib
import logging
import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables from .env file
dotenv_path = ".env"  # Explicitly specify the path if necessary
if not load_dotenv(dotenv_path):
    print("Failed to load .env file. Ensure it exists and is accessible.")
else:
    print(".env file loaded successfully.")

# Access environment variables
MONGO_URI = os.getenv("MONGO_URI")

# Debug: Print environment variables (for troubleshooting)
print("MONGO_URI:", MONGO_URI)

# Set up logging
def setup_logger():
    """Set up a logger for the bot."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logging.info("Logger initialized successfully.")

# Connect to MongoDB
def get_mongo_client():
    """Initialize and return a MongoDB client."""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
        client.admin.command('ping')
        logging.info("Connected to MongoDB successfully!")
        return client
    except Exception as e:
        logging.error(f"Failed to connect to MongoDB: {e}")
        raise

# Test MongoDB connection
def test_mongo_connection():
    """Test the MongoDB connection."""
    try:
        client = get_mongo_client()
        client.admin.command('ping')
        logging.info("MongoDB connection test passed.")
    except Exception as e:
        logging.error(f"MongoDB connection test failed: {e}")

# Initialize SQLite database
def init_sqlite():
    """
    Initialize the SQLite database and create necessary tables.
    Returns the SQLite connection object.
    """
    conn = sqlite3.connect("cache.db")  # Persistent SQLite database
    cursor = conn.cursor()

    # Create a table for key-value storage (similar to Redis)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT,
            expire_at INTEGER
        )
    """)
    conn.commit()
    return conn

# Cache data in SQLite
def cache_data(key, value, expire=3600, sqlite_conn=None):
    """Cache data in SQLite."""
    sqlite_conn = sqlite_conn or init_sqlite()
    cursor = sqlite_conn.cursor()

    # Calculate expiration timestamp
    expire_at = int(time.time()) + expire if expire else None

    # Insert or update the key-value pair
    cursor.execute("""
        INSERT OR REPLACE INTO cache (key, value, expire_at)
        VALUES (?, ?, ?)
    """, (key, value, expire_at))
    sqlite_conn.commit()

# Retrieve cached data from SQLite
def get_cached_data(key, sqlite_conn=None):
    """Retrieve cached data from SQLite."""
    sqlite_conn = sqlite_conn or init_sqlite()
    cursor = sqlite_conn.cursor()

    # Fetch the value and check expiration
    cursor.execute("SELECT value, expire_at FROM cache WHERE key = ?", (key,))
    result = cursor.fetchone()

    if result:
        value, expire_at = result
        if expire_at is None or int(time.time()) < expire_at:
            return value
        else:
            # Remove expired entry
            delete_cached_data(key, sqlite_conn)
    return None

# Delete cached data from SQLite
def delete_cached_data(key, sqlite_conn=None):
    """Delete cached data from SQLite."""
    sqlite_conn = sqlite_conn or init_sqlite()
    cursor = sqlite_conn.cursor()
    cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
    sqlite_conn.commit()

# Translate text
def translate_text(text, target_language):
    """Translate text using the 'translate' library."""
    try:
        translator = TranslateLib(to_lang=target_language)
        translation = translator.translate(text)
        return translation
    except Exception as e:
        logging.error(f"Translation error: {e}")
        return None

# Rate limiting
def is_rate_limited(user_id, max_requests=10, window_seconds=60, sqlite_conn=None):
    """Check if a user is rate-limited."""
    sqlite_conn = sqlite_conn or init_sqlite()
    key = f"rate_limit:{user_id}"

    # Get current count
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT value, expire_at FROM cache WHERE key = ?", (key,))
    result = cursor.fetchone()

    if result:
        current_count, expire_at = result
        current_count = int(current_count)

        # Check expiration
        if expire_at is None or int(time.time()) < expire_at:
            if current_count >= max_requests:
                return True
        else:
            # Reset count if expired
            delete_cached_data(key, sqlite_conn)
            current_count = 0
    else:
        current_count = 0

    # Increment count and set expiration
    new_count = current_count + 1
    expire_at = int(time.time()) + window_seconds
    cache_data(key, str(new_count), expire=window_seconds, sqlite_conn=sqlite_conn)
    return False

# Test utility functions
if __name__ == "__main__":
    setup_logger()

    try:
        # Test MongoDB connection
        test_mongo_connection()

        # Test SQLite caching
        sqlite_conn = init_sqlite()
        cache_data("test_key", "Hello, SQLite!", expire=3600, sqlite_conn=sqlite_conn)
        print(get_cached_data("test_key", sqlite_conn=sqlite_conn))

        # Test translation
        print(translate_text("Hello, world!", "fr"))  # Should return "Bonjour, le monde!"

        # Test rate limiting
        print(is_rate_limited(123))  # Should return False
        print(is_rate_limited(123))  # Increment count
        print(is_rate_limited(123))  # Increment count again
    except Exception as e:
        logging.error(f"Error during testing: {e}")