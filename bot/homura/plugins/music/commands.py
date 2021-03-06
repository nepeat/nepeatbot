# coding=utf-8
import asyncio
import logging
import math
import random
import re
import time
import traceback
from datetime import timedelta
from io import BytesIO

import discord
import pytimeparse

from homura.lib.structure import CommandError, Message
from homura.lib.util import sanitize
from homura.plugins.command import command
from homura.plugins.music.base import MusicBase
from homura.plugins.music.objects import StreamPlaylistEntry, URLPlaylistEntry

MIN_SKIPS = 4
SKIP_RATIO = 0.5

log = logging.getLogger(__name__)


class MusicCommands(MusicBase):
    @command(
        patterns=[
            r"music (queue file)",
            r"music (queue|np|now playing)$",
            r"music$",
        ],
        permission_name="music.info",
        global_command=True,
        description="Music status",
        usage="music"
    )
    async def music(self, message, args):
        player = await self.get_player(message.guild, message.author)

        embed = self.create_voice_embed()

        if player.current_entry:
            embed.add_field(
                name="Now {action}".format(
                    action="streaming" if isinstance(player.current_entry, StreamPlaylistEntry) else "playing"
                ),
                value=f"[{player.current_entry.title}]({player.current_entry.url})"
            )

            if player.current_entry.meta.get("author", ""):
                embed.add_field(
                    name="Added by",
                    value=player.current_entry.meta["author"].mention
                )

            if isinstance(player.current_entry, StreamPlaylistEntry):
                prog_name = "Streaming"
                prog_str = "{progress}".format(
                    progress=str(timedelta(seconds=player.progress)).lstrip('0').lstrip(':')
                )
            else:
                prog_name = "Progress"
                prog_str = '{progress}{extra}'.format(
                    progress=str(timedelta(seconds=player.progress)).lstrip('0').lstrip(':'),
                    extra="/" + str(timedelta(seconds=player.current_entry.duration)).lstrip('0').lstrip(':')
                ) 

        embed.add_field(
            name="Queue",
            value=player.playlist.format_discord(),
            inline=False
        )

        message_to_send = Message(embed)

        if args and args[0].strip().lower() == "queue file":
            message_to_send.set_file(
                data=[x.encode("utf8") for x in player.playlist.format_discord(None, formatted=False)],
                filename=f"{int(time.time())}-music-queue-{message.guild.id}.txt"
            )

        return message_to_send

    @command(
        "music (play|prepend|stream) (.+)",
        permission_name="music.queue",
        global_command=True,
        description="Queues a URL for playback.",
        usage="music [play|prepend|queue]"
    )
    async def play(self, message, args):
        player = await self.get_player(message.guild, message.author)
        url = args[1].strip()

        if url.startswith("prepend:"):
            url = url.lstrip("prepend:")
            prepend = True
            stream = args[0].lower() == "stream"
        else:
            prepend = args[0].lower() == "prepend"
            stream = args[0].lower() == "stream"

        url_regex = re.compile(r'((http(s)*:[/][/]|www.)([a-z]|[A-Z]|[0-9]|[/.]|[~])*)')
        matched_url = url_regex.match(url)
        if matched_url is None:
            url = url.replace('/', '%2F')

        info = await self.downloader.extract_info(player.playlist.loop, url, download=False, process=False)

        if not info:
            return Message(embed=self.create_voice_embed(
                colour=discord.Colour.red(),
                description="This URL could not be played."
            ))

        if info.get("url", "").startswith("ytsearch"):
            info = await self.downloader.extract_info(
                player.playlist.loop,
                url,
                download=False,
                process=True,
                on_error=lambda e: asyncio.ensure_future(
                    message.channel.send("```\n%s\n```" % e), loop=self.bot.loop)
            )

            if not info or not info.get("entries", []):
                raise CommandError(f"No videos were found.")

            song_url = info["entries"][0]["webpage_url"]

            return await self.play._func(self, message, ["prepend" if prepend else "play", song_url])

        if "entries" in info:
            num_songs = sum(1 for _ in info["entries"])

            if info['extractor'].lower() in ['youtube:playlist', 'soundcloud:set', 'bandcamp:album']:
                return await self.play_playlist_async(player, message.channel, message.author, url, info["extractor"])

            t0 = time.time()

            # My test was 1.2 seconds per song, but we maybe should fudge it a bit, unless we can
            # monitor it and edit the message with the estimated time, but that's some ADVANCED SHIT
            # I don't think we can hook into it anyways, so this will have to do.
            # It would probably be a thread to check a few playlists and get the speed from that
            # Different playlists might download at different speeds though
            wait_per_song = 1.2

            procmesg = await message.channel.send(
                embed=self.create_voice_embed(
                    title="Processing",
                    description='Gathering playlist information for {} songs{}'.format(
                        num_songs,
                        ', ETA: {} seconds'.format(
                            self._fixg(
                                num_songs * wait_per_song
                            )
                        ) if num_songs >= 10 else '.'
                    )
                )
            )

            entry_list, position = await player.playlist.import_from(url, channel=message.channel, author=message.author)

            tnow = time.time()
            ttime = tnow - t0
            listlen = len(entry_list)

            log.info("Processed {} songs in {} seconds at {:.2f}s/song, {:+.2g}/song from expected ({}s)".format(
                listlen,
                self._fixg(ttime),
                ttime / listlen,
                ttime / listlen - wait_per_song,
                self._fixg(wait_per_song * num_songs))
            )

            await self.bot.delete_message(procmesg)

            embed_description = f"**{listlen}** songs have been queued!"
        else:
            entry, position = await player.playlist.add_entry(url, channel=message.channel, author=message.author, prepend=prepend, stream=stream)
            embed_description = f"**{entry.title}** has been {'prepended' if prepend else 'queued'}!"

        embed = self.create_voice_embed(
            description=embed_description
        ).add_field(
            name="Queue position",
            value="Up next!" if (position == 1 and player.is_stopped) else position
        )

        if not (position == 1 and player.is_stopped):
            embed.add_field(
                name="Time remaining",
                value=await player.playlist.estimate_time_until(position, player)
            )

        return Message(embed)

    @command(
        patterns=[
            "music shuffle$",
            "music shuffle (.+)"
        ],
        permission_name="music.shuffle",
        description="Shuffles the music queue.",
        usage="music shuffle"
    )
    async def shuffle(self, message, args):
        player = await self.get_player(message.guild, message.author)

        if player.is_stopped:
            raise CommandError("Can't shuffle! The player is not playing!")

        if args:
            player.playlist.shuffle(args[0])
        else:
            player.playlist.shuffle()

        return Message(embed=self.create_voice_embed("Playlist shuffled!"))

    @command(
        patterns=[
            "music seek$",
            "music seek (.+)"
        ],
        permission_name="music.seek",
        description="Seeks the current song.",
        usage="music seek 4:20",
        global_command=True
    )
    async def seek(self, message, args):
        player = await self.get_player(message.guild, message.author)

        if player.is_stopped:
            raise CommandError("Can't seek! The player is not playing!")

        try:
            seek = args[0]
        except IndexError:
            raise CommandError('A time is required to seek.')

        if not (
            message.author == player.current_entry.meta.get("author", None)
            or message.author.guild_permissions.administrator
        ):
            raise CommandError("You cannot seek the video unless you have added the video or are a server admin.")

        try:
            original_seek = seek

            seek = pytimeparse.parse(seek)

            if not seek:
                seek = int(original_seek)

            if seek < 0:
                raise ValueError()
        except (TypeError, ValueError):
            raise CommandError('The time you have given is invalid.')

        try:
            player.seek(seek)
        except (ValueError, TypeError) as e:
            raise CommandError(str(e))

        return Message(embed=self.create_voice_embed(
            title="Seek",
            description='Seeked to %s!' % (
                str(timedelta(seconds=seek)).lstrip('0').lstrip(':')
            )
        ))

    @command(
        patterns=[
            "music (vote)skip",
            "music skip$",
        ],
        permission_name="music.skip",
        global_command=True,
        description="Skips the current playing song.",
        usage="music skip"
    )
    async def skip(self, message, args):
        player = await self.get_player(message.guild, message.author)
        force_vote = args and args[0].lower() == "vote"

        if player.is_stopped:
            raise CommandError("You cannot skip when there are no songs playing!")

        if not player.current_entry:
            if player.playlist.peek():
                raise CommandError("The next song (%s) is downloading, please wait." % player.playlist.peek().title)

        if (
            message.author == player.current_entry.meta.get("author", None)
            or message.author.guild_permissions.administrator
        ) and not force_vote:
            skipped_title = player.current_entry.title
            player.skip()
            return Message(embed=self.create_voice_embed(
                title="Skip",
                description=f"**{skipped_title}** been skipped. (instantly)"
            ))

        num_voice = sum(1 for m in player.voice_client.channel.members if not (
            m.voice.deaf or
            m.voice.self_deaf or
            m.id == self.bot.user.id
        ))

        num_skips, added = player.skip_state.toggle_skip(message.author.id)

        # XXX: hack
        skip_ratio_required = 0.5

        skips_remaining = min(
            MIN_SKIPS,
            math.ceil(skip_ratio_required / (1 / num_voice)) # Number of skips from config ratio
        ) - num_skips

        if skips_remaining <= 0:
            player.skip()
            return Message(embed=self.create_voice_embed(
                title="Skip",
                description=f"Your skip for **{player.current_entry.title}** has been successful.\n"
            ).set_footer(
                text=f"The next song is coming up!" if player.playlist.peek() else "No more songs left in queue!"
            ))
        else:
            return Message(embed=self.create_voice_embed(
                title="Skip",
                description=f"Your skip for **{player.current_entry.title}** has been {'added' if added else 'removed'}."
            ).set_footer(
                text=f"{skips_remaining} more {'skip' if skips_remaining == 1 else 'skips'} are required to skip."
            ), reply=True)

    @command(
        "music summon$",
        permission_name="music.summon",
        description="Summons the bot to a channel",
        usage="music summon"
    )
    async def summon(self, author):
        if not author.voice:
            raise CommandError("You must be in a channel to summon the bot!")

        voice_client = await self.get_voice_client(author.guild, author)

        if voice_client.channel != author.voice.channel:
            perms = author.voice.channel.permissions_for(author.voice.channel.guild.me)

            if not perms.connect:
                raise CommandError(f"I do not have permissions to connect to \"{sanitize(author.voice.channel.name)}\"!")
            elif not perms.speak:
                raise CommandError(f"I do not have permissions to speak in \"{sanitize(author.voice.channel.name)}\"!")

            await voice_client.move_to(author.voice.channel)

        return Message(embed=self.create_voice_embed("Bot summoned!"))

    @command(
        "music clear$",
        permission_name="music.clear",
        description="Clears the music queue",
        usage="music clear"
    )
    async def clear(self, message):
        player = await self.get_player(message.guild, message.author)
        player.playlist.clear()
        return Message(embed=self.create_voice_embed(
            title="Queue cleared",
            description="\N{PUT LITTER IN ITS PLACE SYMBOL}"
        ))

    @command(
        patterns=[
            "music volume$",
            "music volume (.+)"
        ],
        permission_name="music.volume",
        description="Sets the bot volume",
        usage="music volume"
    )
    async def volume(self, message, args):
        player = await self.get_player(message.guild, message.author)

        if not args:
            return Message(embed=self.create_voice_embed(
                title="Volume",
                description="The current bot volume is %s%%" % (player.volume * 100)
            ))

        relative = False
        if args[0][0] in '+-':
            relative = True

        try:
            new_volume = int(args[0])
        except ValueError:
            raise CommandError('{} is not a valid number'.format(args[0]))

        if relative:
            vol_change = new_volume
            new_volume += (player.volume * 100)

        old_volume = int(player.volume * 100)

        if 0.0 < new_volume <= 200:
            player.volume = new_volume / 100.0

            return Message(embed=self.create_voice_embed(
                title="Volume",
                description='Volume has been updated from %d%% to %d%%' % (old_volume, new_volume)
            ))
        elif new_volume >= 200:
            if not message.author.guild_permissions.administrator:
                raise CommandError("You must be an administrator to set the volume beyond 200%")

            embed = self.create_voice_embed(
                title="ARE YOU FUCKING SURE?" if new_volume >= 1000 else "Are you sure?",
                description="Are you sure you would like to set the volume to {volume}%?\n"
                            "Setting the volume beyond this level gives no benefit to the volume or quality at all.\n"
                            "You have 15 seconds to confirm this.{danger}".format(
                                volume=new_volume,
                                danger="\n**RIP HEADPHONE USERS OH GOD**" if new_volume > 500 else ""
                            )
            )

            if new_volume >= 1000:
                embed.set_thumbnail(url="https://i.imgur.com/lWUsTOR.jpg")

            temp_confirm = await message.channel.send(embed=embed)
            await temp_confirm.add_reaction("\N{THUMBS UP SIGN}")

            try:
                confirmed = await self.bot.wait_for(
                    "reaction_add",
                    timeout=15,
                    check=lambda reaction, author: (
                        reaction.message.id == temp_confirm.id and
                        author.id == message.author.id and
                        reaction.emoji == "\N{THUMBS UP SIGN}"
                    )
                )
            except asyncio.TimeoutError:
                return Message(embed=self.create_voice_embed(
                    description="15 seconds has passed without a response. {timing}".format(
                        timing="Thank fucking god." if new_volume > 500 else "Timing out."
                    )
                ))
            finally:
                await self.bot.delete_message(temp_confirm)

            player.volume = new_volume / 100.0
            return Message(embed=self.create_voice_embed(
                title="Volume",
                description='Volume has been updated from %d%% to %d%%' % (old_volume, new_volume)
            ))
        else:
            if relative:
                raise CommandError(
                    'Unreasonable volume change provided: {}{:+} -> {}%.  Provide a change between {} and {:+}.'.format(
                        old_volume,
                        vol_change,
                        old_volume + vol_change, 1 - old_volume, 100 - old_volume
                    ))
            else:
                raise CommandError(
                    'Unreasonable volume provided: {}%. Provide a value between 1 and 100.'.format(new_volume)
                )

    @command(
        "music (disconnect|leave|kill)$",
        permission_name="music.leave",
        description="Makes the bot disconnect",
        usage="music leave"
    )
    async def leave(self, message):
        if not message.guild.voice_client:
            return Message(embed=self.create_voice_embed("The bot is not in the server!"))

        player = await self.get_player(message.guild, message.author)
        await self.cleanup_player(player)

        return Message(embed=self.create_voice_embed("Bot has left the server!"))

    @command(
        patterns=[
            "music surprise$",
            "music surprise (prepend)"
        ],
        permission_name="music.queue.surprise",
        description="Plays a random song from all the songs",
        usage="music surprise"
    )
    async def surprise(self, message, args):
        if args:
            prepend = args[0].lower() == "prepend"
        else:
            prepend = False

        song_url = random.choice(list(self.bot.stats.query('select sample("value", 15), url from music_play').get_points()))["url"]
        return await self.play._func(self, message, ["prepend" if prepend else "play", song_url])

    async def play_playlist_async(self, player, channel, author, playlist_url, extractor_type):
        info = await self.downloader.extract_info(player.playlist.loop, playlist_url, download=False, process=False)

        if not info:
            raise CommandError("That playlist cannot be played.")

        num_songs = sum(1 for _ in info['entries'])
        t0 = time.time()

        busymsg = await channel.send(embed=self.create_voice_embed(
            title="Processing",
            description="Processing %s songs..." % num_songs
        ))

        entries_added = 0
        if extractor_type.lower() in ['youtube:playlist', 'soundcloud:set', 'bandcamp:album']:
            try:
                entries_added = await player.playlist.async_process_playlist(
                    playlist_url,
                    extractor_type.lower(),
                    channel=channel,
                    author=author
                )
                # TODO: Add hook to be called after each song
                # TODO: Add permissions

            except Exception:
                traceback.print_exc()
                raise CommandError('Error handling playlist %s queuing.' % playlist_url)

        songs_processed = len(entries_added)

        await self.bot.delete_message(busymsg)

        songs_added = len(entries_added)
        tnow = time.time()
        ttime = tnow - t0
        wait_per_song = 1.2
        # TODO: actually calculate wait per song in the process function and return that too

        # This is technically inaccurate since bad songs are ignored but still take up time
        log.info("Processed {}/{} songs in {} seconds at {:.2f}s/song, {:+.2g}/song from expected ({}s)".format(
            songs_processed,
            num_songs,
            self._fixg(ttime),
            ttime / num_songs,
            ttime / num_songs - wait_per_song,
            self._fixg(wait_per_song * num_songs))
        )

        return Message(embed=self.create_voice_embed(
            "Enqueued {} songs to be played in {} seconds".format(
                songs_added,
                self._fixg(ttime, 1)
            )
        ))
