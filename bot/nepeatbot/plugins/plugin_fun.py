from nepeatbot.plugins.common import PluginBase, command

class FunPlugin(PluginBase):
    @command("fart")
    async def fart(self, channel):
        print("FARTED")
        await self.bot.send_message(channel, "\N{DASH SYMBOL}")