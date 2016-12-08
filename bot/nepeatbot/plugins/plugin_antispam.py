import re
import discord
import logging

from nepeatbot.plugins.common import PluginBase, Message, command

log = logging.getLogger(__name__)

class AntispamPlugin(PluginBase):
    requires_admin = True

    @command("antispam status")
    async def antispam_status(self, message):
        result = "Blacklist {blacklist} entries.\nWarnlist {warnlist} entries.".format(
            blacklist=await self.redis.scard("antispam:{}:blacklist".format(message.server.id)),
            warnlist=await self.redis.scard("antispam:{}:warnlist".format(message.server.id)),
        )
        return Message(result)

    @command("antispam setlog")
    async def set_log(self, message):
        await self.redis.hset("antispam:{}:config".format(message.server.id), "log_channel", message.channel.id)
        return Message("Log channel set!")

    @command("antispam exclude")
    async def exclude_channel(self, message):
        excluded = await self.redis.sismember("antispam:{}:excluded".format(message.server.id), message.channel.id)
        await self._alter_list(message.server, message.channel.id, list_name="excluded", add=not excluded, validate_regex=False)
        return Message("Channel is {action} from antispam!".format(
            action="added" if excluded else "excluded"
        ))

    @command(patterns=[
        "antispam (add|remove) (blacklist, warnlist) (.+)",
        "antispam (blacklist, warnlist) (add|remove) (.+)"
    ])
    async def alter_list(self, message, args):
        action = True if args[1] == "add" else False
        return await self._alter_list(message.server, args[1], list_name=args[0], add=action)

    async def _alter_list(self, server, value, list_name="warns", add=True, validate_regex=True):
        action = self.redis.sadd if add else self.redis.srem

        if validate_regex and not self.validate_regex(value):
            return Message("invalid [make this user friendly l8r]")

        await action("antispam:{}:{}".format(server.id, list_name), [value])
        return Message("List updated!")

    @command(patterns=[
        "antispam list (blacklist, warnlist, warnings, warns)",
        "antispam (blacklist, warnlist, warnings, warns) list"
    ])
    async def list_list(self, message, args):
        return await self._list_list(message.server, args[0])

    async def _list_list(self, server, list_name):
        list_key = "antispam:{}:{}".format(server.id, list_name)

        contents = await self.redis.smembers(list_key)
        contents = await contents.asset()

        result = "**__{}__**\n".format(
            list_key.capitalize()
        )
        result += "\n".join(contents if contents else {"No entries exist in the {}!".format(list_name)})

        return Message(result)

    @command("antispam list")
    async def list_help(self, channel):
        return Message("!antispam list [blacklist|warnlist]")

    async def on_message(self, message):
        log_channel_id = await self.redis.hget("antispam:{}:config".format(message.server.id), "log_channel")
        if not log_channel_id:
            return

        log_channel = self.bot.get_channel(log_channel_id)
        if not log_channel:
            return

        if await self.redis.sismember("antispam:{}:excluded".format(message.server.id), message.channel.id):
            return

        if await self.check_list(message, "warns"):
            await self.bot.send_message(log_channel, "\N{WARNING SIGN} **{name}** <#{chat}> {message}".format(
                name=self.bot.sanitize(message.author.display_name),
                chat=message.channel.id,
                message=(message.clean_content[:500] + '...') if len(message.clean_content) > 500 else message.clean_content
            ))
        elif await self.check_list(message, "blacklist"):
            if not message.author.server_permissions.administrator:
                await self.bot.delete_message(message)
            await self.bot.send_message(log_channel, "\N{NO ENTRY SIGN} **{name}** <#{chat}> {message}".format(
                name=self.bot.sanitize(message.author.display_name),
                chat=message.channel.id,
                message=(message.clean_content[:500] + '...') if len(message.clean_content) > 500 else message.clean_content
            ))

    async def check_list(self, message, list_name):
        items = await self.redis.smembers("antispam:{}:{}".format(message.server.id, list_name))
        items = await items.asset()

        for item in items:
            if re.search(item, message.clean_content, (re.I | re.M)):
                return True

        return False

    def validate_regex(self, regex):
        try:
            re.compile(regex)
            return True
        except re.error:
            return False
