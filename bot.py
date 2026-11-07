        finally:
            typing_task.cancel()

            try:
                await typing_task
            except asyncio.CancelledError:
                pass


# ==========================================
# 8. AIOHTTP WEB SERVER
# ==========================================

async def home(request):
    return web.json_response({
        "status": "online",
        "bot": BOT_NAME
    })


async def health(request):
    return web.json_response({
        "status": "healthy"
    })


async def start_webserver(application):
    app = web.Application()

    app.router.add_get("/", home)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    application.bot_data["web_runner"] = runner

    logger.info("Web server %s-portda ishga tushdi", PORT)


async def stop_webserver(application):
    runner = application.bot_data.get("web_runner")

    if runner:
        await runner.cleanup()

    await ai.close()


# ==========================================
# 9. MAIN
# ==========================================

def main():
    init_db()

    # Telegram API uchun timeoutlarni oshiramiz.
    # Asosiy request get_me/send_message kabi so'rovlar uchun,
    # alohida get_updates_request esa polling uchun ishlatiladi.
    telegram_request = HTTPXRequest(
        connection_pool_size=20,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    polling_request = HTTPXRequest(
        connection_pool_size=5,
        connect_timeout=30.0,
        read_timeout=40.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(telegram_request)
        .get_updates_request(polling_request)
        .get_updates_connection_pool_size(5)
        .concurrent_updates(True)
        .post_init(start_webserver)
        .post_shutdown(stop_webserver)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("clear", clear_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    logger.info("%s ishga tushmoqda...", BOT_NAME)

    application.run_polling(
        drop_pending_updates=True,
        poll_interval=1.0,
        timeout=20,
        bootstrap_retries=-1,
        read_timeout=40.0,
        write_timeout=30.0,
        connect_timeout=30.0,
        pool_timeout=30.0,
    )
