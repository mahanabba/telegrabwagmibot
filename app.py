import asyncio
import datetime
import logging
import aiosqlite
import nest_asyncio
from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    ContextTypes
)

# Apply nest_asyncio to allow nested event loops.
nest_asyncio.apply()

# SQLite database path
DB_PATH = 'invites.db'
BOT_TOKEN = "7672094667:AAE0KZYq0QY3z5hCa_iaIr94vaRbJSAyjnU"  # Replace with your actual bot token

# ----- Database Initialization -----
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS link_to_inviter (
                invite_link TEXT PRIMARY KEY,
                inviter_display TEXT,
                chat_id INTEGER
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS invite_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                inviter_display TEXT,
                user_id INTEGER,
                join_date TEXT
            )
        ''')
        await db.commit()

# ----- Helper Function -----
def get_inviter_display(user) -> str:
    """Return the display name for a user (username if available, else first name)."""
    return f"@{user.username}" if user.username else user.full_name

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Welcome to the Invite Tracker Bot!\n\n"
        "Available commands:\n"
        "/getinvite - Generate a public invite link (with join requests)\n"
        "/getinviteprivate - Generate a private invite link (with join requests, valid for 7 days)\n"
        "/leaderboard - Display the leaderboard of valid invites\n"
        "/myinvites - Show your personal invite statistics\n"
        "/getchatid - (Admins only) Retrieve the chat ID\n"
        "/help - Show this help message\n"
    )
    await update.message.reply_text(help_text)

# ----- Command to Get a Public Invite Link -----
async def get_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    inviter_display = get_inviter_display(update.effective_user)
    try:
        # Create a permanent invite link with join requests enabled.
        invite_link_obj = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            creates_join_request=True
        )
        invite_link = invite_link_obj.invite_link
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT OR REPLACE INTO link_to_inviter (invite_link, inviter_display, chat_id)
                VALUES (?, ?, ?)
            ''', (invite_link, inviter_display, chat_id))
            await db.commit()
        await update.message.reply_text(f"Public invite link (with join requests):\n{invite_link}")
    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        await update.message.reply_text(f"Failed to create invite link: {e}")

# ----- Command to Get a Private Invite Link (Expires in 7 Days) -----
async def get_invite_link_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    inviter_display = get_inviter_display(update.effective_user)
    try:
        # Set expiration for 7 days from now (as Unix timestamp)
        expire_date = int((datetime.datetime.now() + datetime.timedelta(days=7)).timestamp())
        invite_link_obj = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            creates_join_request=True,
            expire_date=expire_date
        )
        invite_link = invite_link_obj.invite_link
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT OR REPLACE INTO link_to_inviter (invite_link, inviter_display, chat_id)
                VALUES (?, ?, ?)
            ''', (invite_link, inviter_display, chat_id))
            await db.commit()
        await update.message.reply_text(
            f"Private invite link (with join requests, valid for 7 days):\n{invite_link}"
        )
    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        await update.message.reply_text(f"Failed to create invite link: {e}")

# ----- Handler for Join Requests -----
async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    user = request.from_user
    chat_id = request.chat.id

    if request.invite_link is None:
        inviter_display = "Unknown"
    else:
        invite_link_str = request.invite_link.invite_link
        logging.info(f"Join request received. Invite link: {invite_link_str}")
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT inviter_display FROM link_to_inviter WHERE invite_link = ?', (invite_link_str,)
            ) as cursor:
                row = await cursor.fetchone()
                inviter_display = row[0] if row else "Unknown"
        logging.info(f"Retrieved inviter: {inviter_display} for invite link: {invite_link_str}")

    await context.bot.approve_chat_join_request(chat_id, user.id)
    await context.bot.send_message(chat_id, f"✅ {user.first_name} has joined!")
    join_date = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO invite_stats (chat_id, inviter_display, user_id, join_date)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, inviter_display, user.id, join_date))
        await db.commit()
    logging.info(f"User {user.id} joined via invite from {inviter_display} in chat {chat_id}")

# ----- Handler for Chat Member Events (Join/Leave Notifications) -----
async def join_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    user = chat_member.new_chat_member.user
    chat_id = chat_member.chat.id
    if chat_member.new_chat_member.status == ChatMember.MEMBER:
        await context.bot.send_message(chat_id, f"👋 Welcome {user.first_name}!")
    elif chat_member.new_chat_member.status in [ChatMember.LEFT, ChatMember.KICKED]:
        await context.bot.send_message(chat_id, f"❌ {user.first_name} has left.")

# ----- Command to Display the Leaderboard -----
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    leaderboard_text = await generate_leaderboard_message(chat_id, context)
    await update.message.reply_text(leaderboard_text)

# ----- Command to Show Personal Invite Stats -----
async def my_invites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    key = get_inviter_display(update.effective_user)
    now = datetime.datetime.now()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT user_id, join_date FROM invite_stats
            WHERE chat_id = ? AND inviter_display = ?
        ''', (chat_id, key)) as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await update.message.reply_text("You haven't invited anyone yet.")
        return
    message_lines = [f"Invite stats for you ({key}):"]
    valid_count = 0
    for user_id, join_date_str in rows:
        join_date = datetime.datetime.fromisoformat(join_date_str)
        days_in = (now - join_date).days
        valid_count += 1
        message_lines.append(f"- User {user_id} joined {days_in} day(s) ago. (Valid)")
    message_lines.append(f"Total valid invites: {valid_count}")
    await update.message.reply_text("\n".join(message_lines))

# ----- Helper to Generate Leaderboard Text -----
async def generate_leaderboard_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    leaderboard = {}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT inviter_display, user_id, join_date FROM invite_stats
            WHERE chat_id = ?
        ''', (chat_id,)) as cursor:
            rows = await cursor.fetchall()
    now = datetime.datetime.now()
    for inviter_display, user_id, join_date_str in rows:
        join_date = datetime.datetime.fromisoformat(join_date_str)
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ['member', 'administrator', 'creator']:
                leaderboard[inviter_display] = leaderboard.get(inviter_display, 0) + 1
        except Exception as e:
            logging.error(f"Error checking user {user_id}: {e}")
    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    message_lines = ["Leaderboard of valid invites:"]
    if not sorted_board:
        message_lines.append("No invite data available yet.")
    else:
        for rank, (inviter, count) in enumerate(sorted_board, start=1):
            message_lines.append(f"{rank}. {inviter}: {count} valid invites")
    return "\n".join(message_lines)

# ----- Command to Get Chat ID (Admins Only) -----
async def get_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    member = await context.bot.get_chat_member(chat_id, user_id)
    if member.status not in ['administrator', 'creator']:
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    await update.message.reply_text(f"The Chat ID is: {chat_id}")

# ----- Daily Job to Send Leaderboard -----
async def send_daily_leaderboard(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT DISTINCT chat_id FROM invite_stats') as cursor:
            rows = await cursor.fetchall()
    for (chat_id,) in rows:
        leaderboard_text = await generate_leaderboard_message(chat_id, context)
        await context.bot.send_message(chat_id=chat_id, text="Daily Leaderboard:\n" + leaderboard_text)

# ----- Main Function -----
async def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    await init_db()  # Initialize SQLite database.
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # Add handlers for join requests and chat member events.
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    app.add_handler(ChatMemberHandler(join_event_handler, ChatMemberHandler.CHAT_MEMBER))
    # Add command handlers.
    app.add_handler(CommandHandler("getinvite", get_invite_link))
    app.add_handler(CommandHandler("getinviteprivate", get_invite_link_private))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("myinvites", my_invites))
    app.add_handler(CommandHandler("getchatid", get_chatid))
    app.add_handler(CommandHandler("help", help_command))
    # Schedule daily leaderboard posting (at midnight).
    app.job_queue.run_daily(send_daily_leaderboard, time=datetime.time(hour=0, minute=0, second=0))
    # Run polling (this call blocks until the bot is stopped).
    await app.run_polling()

if __name__ == '__main__':
    # Instead of asyncio.run, we use the running loop directly:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
