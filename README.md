# Telegram forwarding bot

The bot accepts voice, audio, and text messages only in private chat. It sends the original voice or audio together with its transcription, and sends text messages, to the Telegram group specified by `TARGET_CHAT_ID`.

## Deploy to Railway

1. Upload the contents of this folder to a new GitHub repository. Do not create or upload a `.env` file.
2. In Railway, create a new project from that GitHub repository.
3. In the Railway project variables, create the following variables:

   ```text
   BOT_TOKEN=<token from BotFather>
   GROQ_API_KEY=<Groq API key>
   TARGET_CHAT_ID=<ID of the destination Telegram group>
   ```

4. Deploy the project. Railway uses Python 3.11 and starts the bot with `python bot.py`.

## Target group setup

Add the bot to the target group and allow it to send messages. To find the group ID, add the bot to the group and send `/chatid`; use the returned value as `TARGET_CHAT_ID`.

## Local start

Set the same three environment variables, run `install_requirements.bat`, then run `start_bot.bat`.

Keep `BOT_TOKEN` and `GROQ_API_KEY` out of GitHub. If a bot token has been shown in a log or chat, revoke it in BotFather and use the new token in Railway.
