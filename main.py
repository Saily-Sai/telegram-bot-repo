from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)
from bot_commands import (
    start,
    ask_language,
    ask_subject,
    ask_level,
    ask_paper,
    process_question,
    handle_question,
    select_similar,
)
from utils import setup_logger
import logging
from dotenv import load_dotenv
import os
from pymongo import MongoClient
import sqlite3  # Import SQLite module

# Load environment variables from .env file
load_dotenv()

# Access environment variables with defaults
MONGO_URI = os.getenv("MONGO_URI")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Validate critical environment variables
if not MONGO_URI:
    raise ValueError("MONGO_URI is not set in the .env file")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in the .env file")

# Define conversation states
ASK_LANGUAGE, ASK_SUBJECT, ASK_LEVEL, ASK_PAPER, PROCESS_QUESTION, SELECT_SIMILAR = range(6)

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
            value TEXT
        )
    """)
    conn.commit()
    logging.info("SQLite cache table created or verified successfully.")
    return conn

def main():
    # Set up logging
    setup_logger()
    logging.info("Logger initialized successfully.")

    # Log environment variables for debugging
    logging.debug(f"MONGO_URI: {MONGO_URI}")
    logging.debug(f"TELEGRAM_BOT_TOKEN: {'*' * len(TELEGRAM_BOT_TOKEN)}")  # Mask sensitive data

    # Connect to MongoDB with retry logic
    mongo_client = None
    retries = 3
    while retries > 0:
        try:
            mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=20000)
            mongo_client.admin.command('ping')
            logging.info("Connected to MongoDB successfully!")
            break
        except Exception as e:
            retries -= 1
            logging.error(f"Failed to connect to MongoDB (retries left: {retries}): {e}")
            if retries == 0:
                logging.error("Max retries reached. Exiting...")
                return

    # Initialize SQLite database
    try:
        sqlite_conn = init_sqlite()
        logging.info("SQLite database initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize SQLite database: {e}")
        return

    # Define functions for interacting with SQLite (key-value store)
    def set_value(key, value):
        cursor = sqlite_conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)", (key, value))
        sqlite_conn.commit()
        logging.debug(f"Set value for key: {key}")

    def get_value(key):
        cursor = sqlite_conn.cursor()
        cursor.execute("SELECT value FROM cache WHERE key = ?", (key,))
        result = cursor.fetchone()
        logging.debug(f"Fetched value for key: {key}")
        return result[0] if result else None

    def delete_value(key):
        cursor = sqlite_conn.cursor()
        cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
        sqlite_conn.commit()
        logging.debug(f"Deleted value for key: {key}")

    # Initialize the Telegram bot
    try:
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        logging.info("Telegram bot initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize Telegram bot: {e}")
        return

    # Define conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_LANGUAGE: [CallbackQueryHandler(ask_language)],
            ASK_SUBJECT: [CallbackQueryHandler(ask_subject)],
            ASK_LEVEL: [CallbackQueryHandler(ask_level)],
            ASK_PAPER: [CallbackQueryHandler(ask_paper)],
            PROCESS_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)],
            SELECT_SIMILAR: [CallbackQueryHandler(select_similar)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: "Conversation cancelled.")],
    )

    # Add conversation handler to the application
    application.add_handler(conv_handler)

    # Store SQLite connection and utility functions in application.bot_data
    application.bot_data["sqlite_conn"] = sqlite_conn
    application.bot_data["set_value"] = set_value
    application.bot_data["get_value"] = get_value
    application.bot_data["delete_value"] = delete_value

    # Start the bot
    try:
        logging.info("Starting bot polling...")
        application.run_polling()
    except Exception as e:
        logging.error(f"Error starting the bot: {e}")
    finally:
        # Gracefully close connections
        if mongo_client:
            mongo_client.close()
            logging.info("MongoDB client closed.")
        if sqlite_conn:
            sqlite_conn.close()
            logging.info("SQLite connection closed.")

if __name__ == "__main__":
    main()