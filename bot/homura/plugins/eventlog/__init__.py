# coding=utf-8
import logging

import discord

from homura.lib.structure import CommandError, Message
from homura.lib.util import sanitize
from homura.plugins.base import PluginBase
from homura.plugins.command import command

log = logging.getLogger(__name__)


class EventLogPlugin(PluginBase):
    requires_admin = True
    EVENTS = ["join", "leave", "guild_rename", "member_rename", "message_edit", "message_delete"]

    @command(
        "eventlog",
        permission_name="eventlog.status",
        description="Shows what events are being logged.",
        usage="eventlog"
    )
    async def eventlog(self, message):
        enabled = await self.redis.smembers_asset("channellog:{}:enabled".format(message.guild.id))

        return Message("**__Enabled__**\n{enabled}\n**__Disabled__**\n{disabled}".format(
            enabled="\n".join(enabled),
            disabled="\n".join([x for x in EventLogPlugin.EVENTS if x not in enabled])
        ))

    @command(
        "eventlog (enable|disable) (.+)",
        permission_name="eventlog.toggle",
        description="Toggles what events to log.",
        usage="eventlog [enable|disable]"
    )
    async def toggle_event(self, message, args):
        event_type = args[1].strip().lower()
        enabled = await self.redis.smembers_asset("channellog:{}:enabled".format(message.guild.id))

        action = self.redis.sadd if args[0] == "enable" else self.redis.srem

        if event_type not in EventLogPlugin.EVENTS and event_type != "all":
            raise CommandError(f"'{event_type}' is not a valid event.")

        if event_type == "all":
            await action("channellog:{}:enabled".format(message.guild.id), EventLogPlugin.EVENTS)
        else:
            await action("channellog:{}:enabled".format(message.guild.id), [event_type])

        return Message("Done!")

    async def on_member_join(self, member):
        await self.log_member(member, True)

    async def on_member_remove(self, member):
        await self.log_member(member, False)

    async def on_guild_update(self, before, after):
        if before.name != after.name:
            embed = discord.Embed(
                colour=discord.Colour.gold(),
            ).set_author(
                name=f"Server has been renamed",
                icon_url="https://nepeat.github.io/assets/icons/edit.png",
            ).add_field(
                name="Before",
                value=sanitize(before.name),
            ).add_field(
                name="After",
                value=sanitize(after.name),
            )
            await self.log(embed, before, "guild_rename")

    async def on_member_update(self, before, after):
        old = before.nick if before.nick else before.name
        new = after.nick if after.nick else after.name

        if old == new:
            return

        embed = discord.Embed(
            colour=discord.Colour.blue(),
        ).set_author(
            name=f"User name change",
            icon_url="https://nepeat.github.io/assets/icons/edit.png",
        ).add_field(
            name="Before",
            value=sanitize(old),
        ).add_field(
            name="After",
            value=sanitize(new),
        )

        embed.set_footer(text=f"User {after.id}")

        await self.log(embed, before.guild, "member_rename")

    async def on_message_edit(self, before, after):
        if before.content == after.content:
            return

        embed = discord.Embed(
            colour=discord.Colour.blue(),
        ).set_author(
            name=f"Message has been edited",
            icon_url="https://nepeat.github.io/assets/icons/edit.png",
        ).add_field(
            name="Channel",
            value=before.channel.mention
        ).add_field(
            name="User",
            value=before.author.mention
        ).add_field(
            name="Before",
            value=(before.clean_content[:900] + '...') if len(before.clean_content) > 900 else before.clean_content,
            inline=False,
        ).add_field(
            name="After",
            value=(after.clean_content[:900] + '...') if len(after.clean_content) > 900 else after.clean_content,
            inline=False,
        )

        embed.set_footer(text=f"Message {after.id}")

        await self.log(embed, before.guild, "message_edit")

    async def on_message_delete(self, message):
        # Check: There must be a message text.
        if not message.clean_content:
            return

        embed = discord.Embed(
            colour=discord.Colour.red(),
        ).set_author(
            name=f"Deleted message",
            icon_url="https://nepeat.github.io/assets/icons/trash.png",
        ).add_field(
            name="Channel",
            value=f"<#{message.channel.id}>"
        ).add_field(
            name="User",
            value=message.author.mention
        ).add_field(
            name="Message",
            value=(message.clean_content[:900] + '...') if len(message.clean_content) > 900 else message.clean_content,
            inline=False,
        )

        await self.log(embed, message.guild, "message_delete")

    async def log(self, message, guild, event_type):
        log_channel = self.bot.get_channel(await self.redis.hget(f"{guild.id}:settings", "log_channel"))
        if not log_channel:
            return

        enabled = await self.redis.sismember("channellog:{}:enabled".format(guild.id), event_type)
        if enabled:
            if isinstance(message, discord.Embed):
                await log_channel.send(embed=message)
            else:
                await log_channel.send(message)

    async def log_member(self, member, joining):
        embed = discord.Embed(
            colour=discord.Colour.green() if joining else discord.Colour.red(),
        ).set_author(
            name=f"{member.display_name} has {'joined' if joining else 'left'}",
            icon_url=f"https://nepeat.github.io/assets/icons/{'check' if joining else 'x_circle'}.png",
        )

        embed.set_footer(text=f"User {member.id}")

        await self.log(embed, member.guild, "join" if joining else "leave")
