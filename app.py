import datetime
import logging
from telegram import Update, Bot, ChatMember
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    ContextTypes
)

# In-memory storage for invite events.
# We'll use the inviter's display name as key: { inviter_display_name (str): [ { 'user_id': int, 'join_date': datetime }, ... ] }
invite_stats = {}
# Mapping from persistent invite link (str) to inviter's display name (str)
link_to_inviter = {}
global BOT_TOKEN, GROUP_CHAT_ID
BOT_TOKEN = "7672094667:AAE0KZYq0QY3z5hCa_iaIr94vaRbJSAyjnU"        # Replace with your actual bot token.
GROUP_CHAT_ID = "-1002455294618"   # e.g., -1001234567890

# --- Handler for Join Requests (e.g., in private groups) ---

async def get_invite_link_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    inviter_id = str(update.effective_user.id)
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
        
        # Map this link to the inviter's ID for tracking later.
        link_to_inviter[invite_link] = inviter_id
        
        await update.message.reply_text(f"Private invite link (with join requests, valid for 7 days):\n{invite_link}")
    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        await update.message.reply_text(f"Failed to create invite link: {e}")

async def get_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    inviter_id = str(update.effective_user.id)
    try:
        # Create a permanent invite link with join requests enabled.
        invite_link_obj = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            creates_join_request=True
            # No expire_date provided; link remains permanent.
        )
        invite_link = invite_link_obj.invite_link
        
        # Map this link to the inviter's ID for tracking later.
        link_to_inviter[invite_link] = inviter_id
        
        await update.message.reply_text(f"Public invite link (with join requests):\n{invite_link}")
    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        await update.message.reply_text(f"Failed to create invite link: {e}")


async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approves join requests & correctly tracks who invited the user."""
    request = update.chat_join_request
    user = request.from_user
    invite_link = request.invite_link

    # Approve the request
    await context.bot.approve_chat_join_request(request.chat.id, user.id)
    await context.bot.send_message(request.chat.id, f"✅ {user.first_name} has joined!")

    # Retrieve the inviter’s name
    inviter_display = link_to_inviter.get(invite_link, "Unknown")

    # Store invite tracking
    if inviter_display not in invite_stats:
        invite_stats[inviter_display] = []

    invite_stats[inviter_display].append({
        'user_id': user.id,
        'join_date': datetime.datetime.now()
    })

async def join_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles new users joining and users leaving."""
    chat_member = update.chat_member
    user = chat_member.new_chat_member.user

    if chat_member.new_chat_member.status == ChatMember.MEMBER:
        await context.bot.send_message(chat_member.chat.id, f"👋 Welcome {user.first_name}!")

    elif chat_member.new_chat_member.status in [ChatMember.LEFT, ChatMember.KICKED]:
        await context.bot.send_message(chat_member.chat.id, f"❌ {user.first_name} has left.")
# --- Command to display the leaderboard ---
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    leaderboard_text = await generate_leaderboard_message(chat_id, context)
    await update.message.reply_text(leaderboard_text)

# --- Command to show personal invite stats ---
async def my_invites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    # Use the display name we stored when generating the link.
    if user.username:
        key = f"@{user.username}"
    else:
        key = user.full_name

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
        if days_in >= 0:
            valid_count += 1
            line += " (Valid)"
        else:
            line += " (Not yet valid)"
        message_lines.append(line)
    message_lines.append(f"Total valid invites: {valid_count}")
    await update.message.reply_text("\n".join(message_lines))


async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approves join requests & tracks who invited the user."""
    request = update.chat_join_request
    user = request.from_user

    # Approve the join request
    await context.bot.approve_chat_join_request(request.chat.id, user.id)
    await context.bot.send_message(request.chat.id, f"✅ {user.first_name} has joined!")

    # Track who invited this user
    invite_link = request.invite_link
    inviter_display = link_to_inviter.get(invite_link, "Unknown")

    if inviter_display not in invite_stats:
        invite_stats[inviter_display] = []

    invite_stats[inviter_display].append({
        'user_id': user.id,
        'join_date': datetime.datetime.now()
    })

    logging.info(f"User {user.id} joined via invite from {inviter_display}.")


async def join_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles new users joining and existing users leaving."""
    chat_member = update.chat_member
    user = chat_member.new_chat_member.user

    if chat_member.new_chat_member.status == ChatMember.MEMBER:
        await context.bot.send_message(chat_member.chat.id, f"👋 Welcome {user.first_name}!")

    elif chat_member.new_chat_member.status in [ChatMember.LEFT, ChatMember.KICKED]:
        await context.bot.send_message(chat_member.chat.id, f"❌ {user.first_name} has left.")
# --- Helper function to generate leaderboard text ---
async def generate_leaderboard_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    now = datetime.datetime.now()
    leaderboard = {}
    for inviter_display, events in invite_stats.items():
        valid_count = 0
        for event in events:
            if (now - event['join_date']).days >= 0:
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
    # Remove the erroneous call to reply_text:
    # await Update.message.reply_text("\n".join(message_lines))
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
    BOT_TOKEN = "7672094667:AAE0KZYq0QY3z5hCa_iaIr94vaRbJSAyjnU"        # Replace with your actual bot token.
    GROUP_CHAT_ID = "-1002455294618"   # e.g., -1001234567890


    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handler for join requests.
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    # Add handler for direct join events.
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
