import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
import pytesseract
from PIL import Image
from PyPDF2 import PdfReader
from pdf2image import convert_from_bytes
from io import BytesIO
import sqlite3
from pymongo import MongoClient, monitoring
from pymongo.errors import ServerSelectionTimeoutError
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Load environment variables from .env file
dotenv_path = ".env"  # Explicitly specify the path if necessary
if not load_dotenv(dotenv_path):
    logging.error("Failed to load .env file. Ensure it exists and is accessible.")
    raise FileNotFoundError("Failed to load .env file.")
else:
    logging.info(".env file loaded successfully.")

# Access environment variables
MONGO_URI = os.getenv("MONGO_URI")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Debug: Print environment variables (masked for sensitive data)
logging.debug(f"MONGO_URI: {'*' * len(MONGO_URI)}")
logging.debug(f"TELEGRAM_BOT_TOKEN: {'*' * len(TELEGRAM_BOT_TOKEN)}")

if not MONGO_URI or not TELEGRAM_BOT_TOKEN:
    logging.error("Environment variables MONGO_URI or TELEGRAM_BOT_TOKEN are missing.")
    raise ValueError("Environment variables MONGO_URI or TELEGRAM_BOT_TOKEN are missing.")

# Configure MongoDB client with improved settings
try:
    mongo_client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=30000,  # Increase timeout for server selection
        socketTimeoutMS=30000,           # Increase timeout for socket operations
        connectTimeoutMS=30000,          # Increase timeout for initial connection
        retryWrites=True,                # Enable retryable writes
        appname="telegram-bot-cluster",  # Specify application name
        heartbeatFrequencyMS=10000       # Reduce heartbeat frequency (default is 10 seconds)
    )
    logging.info("MongoDB client initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize MongoDB client: {e}")
    raise

# Test MongoDB connection with retry logic
def test_mongo_connection():
    """Test the MongoDB connection with retry logic."""
    retries = 3
    while retries > 0:
        try:
            mongo_client.admin.command('ping')
            logging.info("Connected to MongoDB successfully!")
            break
        except Exception as e:
            retries -= 1
            logging.error(f"Failed to connect to MongoDB (retries left: {retries}): {e}")
            if retries == 0:
                logging.error("Max retries reached. Exiting...")
                raise

# Initialize SQLite database
def init_sqlite():
    """
    Initialize the SQLite database and create necessary tables.
    Returns the SQLite connection object.
    """
    conn = sqlite3.connect("user_data.db")  # Persistent SQLite database
    cursor = conn.cursor()

    # Create a table for user data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 10,
            language TEXT DEFAULT 'en',
            achievements TEXT DEFAULT '[]'
        )
    """)
    conn.commit()
    return conn

# Initialize SQLite connection
sqlite_conn = init_sqlite()

# User management functions
def get_user(user_id):
    """Fetch user data from MongoDB or SQLite."""
    try:
        # Try fetching from MongoDB
        user = users_collection.find_one({"user_id": user_id})
        if user:
            logging.info(f"User found in MongoDB: {user}")
            return user
    except Exception as e:
        logging.error(f"Error fetching user from MongoDB: {e}")

    # Fallback to SQLite
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user:
        logging.info(f"User found in SQLite: {user}")
        return {
            "user_id": user[0],
            "coins": user[1],
            "language": user[2],
            "achievements": user[3]
        }
    else:
        logging.info("User not found.")
        return None

def create_user(user_id):
    """Create a new user with default values in SQLite."""
    try:
        cursor = sqlite_conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, coins, language, achievements)
            VALUES (?, ?, ?, ?)
        """, (user_id, 10, "en", "[]"))
        sqlite_conn.commit()
        logging.info(f"User created with ID: {user_id}")
    except Exception as e:
        logging.error(f"Error creating user: {e}")

def update_coins(user_id, coins_change):
    """Update user's coin balance in SQLite."""
    try:
        cursor = sqlite_conn.cursor()
        cursor.execute("""
            UPDATE users
            SET coins = coins + ?
            WHERE user_id = ?
        """, (coins_change, user_id))
        sqlite_conn.commit()

        if cursor.rowcount > 0:
            logging.info(f"Updated coins for user {user_id}.")
        else:
            logging.info(f"User {user_id} not found.")
    except Exception as e:
        logging.error(f"Error updating coins: {e}")

def set_language(user_id, language):
    """Set user's preferred language in SQLite."""
    try:
        cursor = sqlite_conn.cursor()
        cursor.execute("""
            UPDATE users
            SET language = ?
            WHERE user_id = ?
        """, (language, user_id))
        sqlite_conn.commit()

        if cursor.rowcount > 0:
            logging.info(f"Language updated for user {user_id}.")
        else:
            logging.info(f"User {user_id} not found.")
    except Exception as e:
        logging.error(f"Error setting language: {e}")

# Gracefully handle program termination
def close_connections():
    """Close both MongoDB and SQLite connections."""
    try:
        mongo_client.close()
        logging.info("MongoDB connection closed successfully.")
    except Exception as e:
        logging.error(f"Error closing MongoDB connection: {e}")

    try:
        sqlite_conn.close()
        logging.info("SQLite connection closed successfully.")
    except Exception as e:
        logging.error(f"Error closing SQLite connection: {e}")

# Command logging for MongoDB
class CommandLogger(monitoring.CommandListener):
    def started(self, event):
        logging.debug(f"Command started: {event.command_name}")

    def succeeded(self, event):
        logging.debug(f"Command succeeded: {event.command_name}")

    def failed(self, event):
        logging.error(f"Command failed: {event.command_name}")

# Register the command logger
monitoring.register(CommandLogger())

# Example usage (optional)
if __name__ == "__main__":
    try:
        # Connect to MongoDB
        test_mongo_connection()

        # Connect to the database and collection in MongoDB
        db = mongo_client["telegram-bot-cluster"]
        users_collection = db["users"]

        # Example user operations
        user_id = 12345
        create_user(user_id)
        update_coins(user_id, 50)
        set_language(user_id, "fr")
        user = get_user(user_id)
        print("Fetched user:", user)

        # Example file download logic
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }

        file_urls = [
            "https://meetlearn.com/images/2019/12/11/13.png",
            "https://meetlearn.com/images/2017/10/07/blog.jpg",
            "https://meetlearn.com/images/2019/12/15/review.png",
        ]

        successful_downloads = 0
        for url in file_urls:
            try:
                logging.info(f"Processing file: {url}")
                response = session.get(url, headers=headers)
                response.raise_for_status()

                # Save the file locally
                filename = url.split("/")[-1]
                with open(filename, "wb") as f:
                    f.write(response.content)
                logging.info(f"Successfully downloaded: {filename}")
                successful_downloads += 1
            except requests.exceptions.HTTPError as e:
                logging.error(f"HTTP error occurred while downloading {url}: {e}")
            except Exception as e:
                logging.error(f"An unexpected error occurred while downloading {url}: {e}")

        logging.info(f"Total files scraped: {successful_downloads}")

    finally:
        # Ensure all connections are closed
        close_connections()