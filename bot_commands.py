from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from user_management import get_user, create_user, update_coins, set_language
from scraper import scrape_website, process_downloaded_file, extract_text_from_image, extract_text_from_docx, download_file, extract_links_from_page, fetch_page_content
from utils import translate_text, is_rate_limited
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
import logging
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Access environment variables
MONGO_URI = os.getenv("MONGO_URI")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Connect to MongoDB
def connect_to_mongodb(retries=3):
    """Connect to MongoDB with retry logic."""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
        client.admin.command('ping')
        logging.info("Connected to MongoDB successfully.")
        return client
    except ServerSelectionTimeoutError as e:
        if retries > 0:
            logging.error(f"Failed to connect to MongoDB: {e}. Retrying ({retries} attempts left)...")
            return connect_to_mongodb(retries - 1)
        else:
            logging.error("Maximum retries reached. Unable to connect to MongoDB.")
            raise
    except Exception as e:
        logging.error(f"Unexpected MongoDB error: {e}")
        raise

# Initialize MongoDB client
client = connect_to_mongodb()
db = client["telegram-bot-cluster"]

# States for conversation handling
ASK_LANGUAGE, ASK_SUBJECT, ASK_LEVEL, ASK_PAPER, PROCESS_QUESTION, SELECT_SIMILAR = range(6)

# SQLite Cache Functions
def cache_data(key, value, context):
    """Cache data using SQLite."""
    sqlite_conn = context.bot_data["sqlite_conn"]
    cursor = sqlite_conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)", (key, value))
    sqlite_conn.commit()

def get_cached_data(key, context):
    """Retrieve cached data from SQLite."""
    sqlite_conn = context.bot_data["sqlite_conn"]
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT value FROM cache WHERE key = ?", (key,))
    result = cursor.fetchone()
    return result[0] if result else None

def start(update, context):
    user_id = update.message.from_user.id
    logging.info(f"User {user_id} started the bot.")
    
    user = get_user(user_id)
    if not user:
        create_user(user_id)
        update.message.reply_text("Welcome! You've been awarded 10 free coins.")
    else:
        update.message.reply_text(f"Welcome back! You have {user['coins']} coins.")
    
    return ask_language(update, context)

def ask_language(update, context):
    keyboard = [
        [InlineKeyboardButton("English", callback_data="en")],
        [InlineKeyboardButton("French", callback_data="fr")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Please choose your preferred language:", reply_markup=reply_markup)
    return ASK_LANGUAGE

def ask_subject(update, context):
    query = update.callback_query
    query.answer()
    language = query.data
    context.user_data["language"] = language
    set_language(query.from_user.id, language)
    
    keyboard = [
        [InlineKeyboardButton("Mathematics", callback_data="Mathematics")],
        [InlineKeyboardButton("Physics", callback_data="Physics")],
        [InlineKeyboardButton("Chemistry", callback_data="Chemistry")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Please choose your subject:", reply_markup=reply_markup)
    return ASK_SUBJECT

def ask_level(update, context):
    query = update.callback_query
    query.answer()
    subject = query.data
    context.user_data["subject"] = subject
    
    keyboard = [
        [InlineKeyboardButton("O-Level", callback_data="O-Level")],
        [InlineKeyboardButton("A-Level", callback_data="A-Level")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Please choose your level:", reply_markup=reply_markup)
    return ASK_LEVEL

def ask_paper(update, context):
    query = update.callback_query
    query.answer()
    level = query.data
    context.user_data["level"] = level
    
    keyboard = [
        [InlineKeyboardButton("Paper 1", callback_data="Paper 1")],
        [InlineKeyboardButton("Paper 2", callback_data="Paper 2")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Please choose the paper type:", reply_markup=reply_markup)
    return ASK_PAPER

def process_question(update, context):
    query = update.callback_query
    query.answer()
    paper = query.data
    context.user_data["paper"] = paper
    query.edit_message_text("Please enter your question:")
    return PROCESS_QUESTION

def handle_question(update, context):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    if user["coins"] <= 0:
        update.message.reply_text("You don't have enough coins to ask a question.")
        return ConversationHandler.END

    question = update.message.text.strip()
    subject = context.user_data.get("subject")
    level = context.user_data.get("level")
    paper = context.user_data.get("paper")

    if not all([subject, level, paper]):
        update.message.reply_text("Please complete the selection process before asking a question.")
        return ConversationHandler.END

    # Check cache first
    cache_key = f"{question}:{subject}:{level}:{paper}"
    cached_answer = get_cached_data(cache_key, context)
    if cached_answer:
        update.message.reply_text(f"Cached answer: {cached_answer}")
        update_coins(user_id, -1)  # Deduct coins for premium feature
        return ConversationHandler.END

    # Scrape past papers
    try:
        past_papers = scrape_past_papers(subject, level, paper)
        if not past_papers:
            update.message.reply_text("No past papers found for the selected subject, level, and paper.")
            return ConversationHandler.END

        match = find_similar_questions(question, past_papers)
        if match:
            update.message.reply_text(f"Exact match found: {match[0]['answer']}")
            cache_data(cache_key, match[0]["answer"], context)
        else:
            similar_questions = find_similar_questions(question, past_papers, threshold=0.8)
            if similar_questions:
                update.message.reply_text("The following question was found:")
                update.message.reply_text(similar_questions[0]["question"])
                update.message.reply_text(similar_questions[0]["answer"])
                cache_data(cache_key, similar_questions[0]["answer"], context)
                context.user_data["similar_questions"] = similar_questions
                list_similar_questions(update, context, similar_questions)
            else:
                update.message.reply_text("No matching or similar questions found.")

        update_coins(user_id, -1)  # Deduct coins for premium feature
    except Exception as e:
        logging.error(f"Error handling question: {e}")
        update.message.reply_text("An error occurred while processing your request.")
    
    return SELECT_SIMILAR

def list_similar_questions(update, context, similar_questions):
    keyboard = [
        [InlineKeyboardButton(f"{i+1}. {q['question']}", callback_data=str(i))]
        for i, q in enumerate(similar_questions[:5])  # Limit to 5 similar questions
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Here are some similar questions:", reply_markup=reply_markup)

def select_similar(update, context):
    query = update.callback_query
    query.answer()
    index = int(query.data)
    similar_questions = context.user_data.get("similar_questions", [])
    if 0 <= index < len(similar_questions):
        selected_question = similar_questions[index]
        query.edit_message_text(f"Answer: {selected_question['answer']}")
        list_similar_questions(update, context, similar_questions)
    else:
        query.edit_message_text("Invalid selection.")
    return SELECT_SIMILAR