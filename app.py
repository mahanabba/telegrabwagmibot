import datetime
import logging
from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    ContextTypes
)

# In-memory storage for invite events.
# Mapping: { inviter_display (str): [ { 'user_id': int, 'join_date': datetime }, ... ] }
invite_stats = {}
# Mapping from invite link (str) to inviter's display name (str)
link_to_inviter = {}

BOT_TOKEN = "7672094667:AAE0KZYq0QY3z5hCa_iaIr94vaRbJSAyjnU"        # Replace with your actual bot token.
GROUP_CHAT_ID = "-1002455294618"   # e.g., -1001234567890

def get_inviter_display(user) -> str:
    """Helper: Returns the display name for a user (username if available, else first name)."""
    if user.username:
        return f"@{user.username}"
    else:
        return user.full_name

# --- Command Handlers for generating invite links ---

async def get_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    inviter_display = get_inviter_display(update.effective_user)
    try:
        # Create a permanent invite link with join requests enabled.
        invite_link_obj = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            creates_join_request=True  # New joiners will send a join request.
        )
        invite_link = invite_link_obj.invite_link
        # Map this link to the inviter's display name for tracking later.
        link_to_inviter[invite_link] = inviter_display
        await update.message.reply_text(f"Public invite link (with join requests):\n{invite_link}")
    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        await update.message.reply_text(f"Failed to create invite link: {e}")

async def get_invite_link_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    inviter_display = get_inviter_display(update.effective_user)
    try:
        # Set expiration for 7 days from now (Unix timestamp)
        expire_date = int((datetime.datetime.now() + datetime.timedelta(days=7)).timestamp())
        # Create an invite link with join requests enabled that expires in 7 days.
        invite_link_obj = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            creates_join_request=True,
            expire_date=expire_date
        )
        invite_link = invite_link_obj.invite_link
        # Map this link to the inviter's display name for tracking.
        link_to_inviter[invite_link] = inviter_display
        await update.message.reply_text(f"Private invite link (with join requests, valid for 7 days):\n{invite_link}")
    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        await update.message.reply_text(f"Failed to create invite link: {e}")

# --- Handler for Join Requests ---
async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    user = request.from_user

    # Log the invite link as a string.
    invite_link_obj = request.invite_link
    invite_link_str = invite_link_obj.invite_link  # Extract the URL string.
    logging.info(f"Join request received. Invite link in request: {invite_link_str}")
    logging.info(f"Current link_to_inviter mapping: {link_to_inviter}")

    # Approve the join request.
    await context.bot.approve_chat_join_request(request.chat.id, user.id)
    await context.bot.send_message(request.chat.id, f"✅ {user.first_name} has joined!")

    # Retrieve inviter's display name using the string key.
    inviter_display = link_to_inviter.get(invite_link_str, "Unknown")
    logging.info(f"Retrieved inviter display name: {inviter_display} for invite link: {invite_link_str}")

    # Record the event for the leaderboard.
    if inviter_display not in invite_stats:
        invite_stats[inviter_display] = []
    invite_stats[inviter_display].append({
        'user_id': user.id,
        'join_date': datetime.datetime.now()
    })
    logging.info(f"User {user.id} joined via invite from {inviter_display}.")
    
    # --- Handler for Chat Member Events (join/leave notifications) ---
async def join_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends welcome or farewell messages on chat member events."""
    chat_member = update.chat_member
    user = chat_member.new_chat_member.user

    if chat_member.new_chat_member.status == ChatMember.MEMBER:
        await context.bot.send_message(chat_member.chat.id, f"👋 Welcome {user.first_name}!")
    elif chat_member.new_chat_member.status in [ChatMember.LEFT, ChatMember.KICKED]:
        await context.bot.send_message(chat_member.chat.id, f"❌ {user.first_name} has left.")

# --- Command to display the leaderboard ---
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    leaderboard_text = await generate_leaderboard_message(GROUP_CHAT_ID, context)
    await update.message.reply_text(leaderboard_text)

# --- Command to show personal invite stats ---
async def my_invites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    key = get_inviter_display(user)
    now = datetime.datetime.now()
    events = invite_stats.get(key, [])
    if not events:
        await update.message.reply_text("You haven't invited anyone yet.")
        return
    message_lines = [f"Invite stats for you ({key}):"]
    valid_count = 0
    for event in events:
        days_in = (now - event['join_date']).days
        line = f"- User {event['user_id']} joined {days_in} day(s) ago."
        valid_count += 1
        line += " (Valid)"
        message_lines.append(line)
    message_lines.append(f"Total valid invites: {valid_count}")
    await update.message.reply_text("\n".join(message_lines))

# --- Helper function to generate leaderboard text ---
async def generate_leaderboard_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    now = datetime.datetime.now()
    leaderboard = {}
    for inviter_display, events in invite_stats.items():
        valid_count = 0
        for event in events:
            # Check if the invited user is still a member.
            try:
                member = await context.bot.get_chat_member(chat_id, event['user_id'])
                if member.status in ['member', 'administrator', 'creator']:
                    valid_count += 1
            except Exception as e:
                logging.error(f"Error checking user {event['user_id']}: {e}")
        leaderboard[inviter_display] = valid_count

    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    message_lines = ["Leaderboard of valid invites:"]
    if not sorted_board:
        message_lines.append("No invite data available yet.")
    else:
        for rank, (inviter_display, count) in enumerate(sorted_board, start=1):
            message_lines.append(f"{rank}. Inviter {inviter_display}: {count} valid invites")
    return "\n".join(message_lines)

# --- Daily job to send the leaderboard automatically ---
async def send_daily_leaderboard(context: ContextTypes.DEFAULT_TYPE) -> None:
    leaderboard_text = await generate_leaderboard_message(GROUP_CHAT_ID, context)
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text="Daily Leaderboard:\n" + leaderboard_text
    )

def main():
    global BOT_TOKEN, GROUP_CHAT_ID
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers for join requests and chat member events.
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    app.add_handler(ChatMemberHandler(join_event_handler, ChatMemberHandler.CHAT_MEMBER))
    # Command handlers.
    app.add_handler(CommandHandler("getinvite", get_invite_link))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("myinvites", my_invites))
    # Schedule daily leaderboard posting.
    app.job_queue.run_daily(
        send_daily_leaderboard,
        time=datetime.time(hour=0, minute=0, second=0),
        chat_id=GROUP_CHAT_ID
    )

    app.run_polling()

if __name__ == '__main__':
    main()
