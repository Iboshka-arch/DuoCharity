from bot.translations import bt

mention = '<a href="tg://user?id=1">Test</a>'
print(bt('welcome_message', 'ru', mention=mention))
print('---')
print(bt('welcome_message', 'uz', mention=mention))
