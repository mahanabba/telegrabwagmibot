import datetime
import logging
from telegram import Update
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

# --- Handler for Join Requests (e.g., in private groups) ---
async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    join_request = update.chat_join_request
    user_id = join_request.from_user.id
    used_invite_obj = join_request.invite_link  # ChatInviteLink object, if available
    if used_invite_obj:
        invite_url = used_invite_obj.invite_link
        inviter_display = link_to_inviter.get(invite_url)
        if inviter_display:
            join_date = datetime.datetime.now()
            invite_stats.setdefault(inviter_display, []).append({
                'user_id': user_id,
                'join_date': join_date
            })
            logging.info(f"User {user_id} used invite from {inviter_display} at {join_date}")
        else:
            logging.info(f"Invite link {invite_url} not found in mapping.")
    try:
        # Approve join request so user is added
        await context.bot.approve_chat_join_request(
            chat_id=join_request.chat.id,
            user_id=user_id
        )
        logging.info(f"Approved join request for user {user_id}")
    except Exception as e:
        logging.error(f"Error approving join request for user {user_id}: {e}")

# --- Handler for Direct Join Events (e.g., in public groups) ---
async def join_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_member = update.chat_member
    if (chat_member.new_chat_member.status == 'member' and 
        chat_member.old_chat_member.status in ['left', 'kicked']):
        used_invite_obj = chat_member.invite_link  # May be None if no link used
        if used_invite_obj:
            invite_url = used_invite_obj.invite_link
            inviter_display = link_to_inviter.get(invite_url)
            if inviter_display:
                join_date = datetime.datetime.now()
                invite_stats.setdefault(inviter_display, []).append({
                    'user_id': chat_member.new_chat_member.user.id,
                    'join_date': join_date
                })
                logging.info(f"User {chat_member.new_chat_member.user.id} joined via invite from {inviter_display} at {join_date}")
        else:
            logging.info("User joined without using an invite link.")

# --- Command to generate and share a persistent invite link ---
async def get_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    # Build display name: use username if available, else full name.
    if user.username:
        display_name = f"@{user.username}"
    else:
        display_name = user.full_name

    try:
        # Use export_chat_invite_link to get a persistent primary invite link.
        invite_link = await context.bot.export_chat_invite_link(chat_id=chat_id)
        # Map the invite link to the inviter's display name.
        link_to_inviter[invite_link] = display_name
        await update.message.reply_text(f"Here is your invite link: {invite_link}")
    except Exception as e:
        logging.error(f"Error exporting invite link: {e}")
        await update.message.reply_text(f"Failed to export invite link: {e}")

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
