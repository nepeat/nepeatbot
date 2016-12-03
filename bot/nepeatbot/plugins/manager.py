import logging
from nepeatbot.plugins import ALL_PLUGINS

log = logging.getLogger(__name__)

class PluginManager:

    def __init__(self, bot):
        self.bot = bot
        self.bot.plugins = []

    def load(self, plugin):
        log.info('Loading {}.'.format(plugin.__name__))
        plugin_instance = plugin(self.bot)
        self.bot.plugins.append(plugin_instance)
        log.info('{} loaded.'.format(plugin.__name__))

    def load_all(self):
        for plugin in ALL_PLUGINS:
            self.load(plugin)

    async def get_all(self, server):
        enabled_plugins = self.bot.redis.smembers('plugins:{}'.format(server.id))
        plugins = []

        for plugin in self.bot.plugins:
            if plugin.is_global:
                plugins.append(plugin)

            if plugin.__class__.__name__.lower() in enabled_plugins:
                plugins.append(plugin)

        return plugins

    def get(self, name):
        name = name.lower()
        for plugin in self.bot.plugins:
            if plugin.__class__.__name__.lower() == name:
                return plugin

        return None
