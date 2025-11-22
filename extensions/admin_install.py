import os
import sys
import aiohttp
import asyncio
from urllib.parse import urlparse
from discord.ext import commands

ROOT = os.path.dirname(os.path.dirname(__file__))
EXT_DIR = os.path.join(ROOT, "extensions")

# Optional allowlist for hosts. Set to None or empty set to allow any host (less safe).
ALLOWED_HOSTS = {"raw.githubusercontent.com"}


class AdminInstall(commands.Cog):
    """Admin-only tools for installing single-file extensions remotely.

    Command: !installext <url>
    - Only users with Administrator permission can run this command.
    - Downloads a .py file and places it into `extensions/`.
    - Backs up existing file to .bak before replacing and attempts rollback if load fails.
    """

    def __init__(self, bot):
        self.bot = bot

    async def cog_unload(self):
        return None

    @commands.has_permissions(administrator=True)
    @commands.command(name="installext")
    async def installext(self, ctx, url: str):
        """Install or update a single extension .py file from a URL.

        Usage:
          !installext https://raw.githubusercontent.com/user/repo/main/extensions/myext.py

        Notes:
          - Caller must have the Discord Administrator permission.
          - By default only raw.githubusercontent.com is allowed; change ALLOWED_HOSTS if needed.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return await ctx.send("Only http(s) URLs are allowed.")

        hostname = parsed.hostname or ""
        if ALLOWED_HOSTS and hostname not in ALLOWED_HOSTS:
            return await ctx.send(f"Host not allowed: {hostname}. Add it to ALLOWED_HOSTS to allow.")

        filename = os.path.basename(parsed.path.split("?")[0])
        if not filename.endswith(".py"):
            return await ctx.send("URL must point to a .py file")

        dest_path = os.path.join(EXT_DIR, filename)
        module_name = f"extensions.{filename[:-3]}"

        await ctx.trigger_typing()

        # Download
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return await ctx.send(f"Failed to download: HTTP {resp.status}")
                    content = await resp.text()
        except Exception as e:
            return await ctx.send(f"Download error: {e}")

        # Ensure extensions dir exists
        os.makedirs(EXT_DIR, exist_ok=True)

        # Backup existing
        backup_path = None
        if os.path.exists(dest_path):
            backup_path = dest_path + ".bak"
            try:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                os.replace(dest_path, backup_path)
            except Exception as e:
                return await ctx.send(f"Failed to backup existing file: {e}")

        # Write new file
        try:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            # restore backup
            if backup_path and os.path.exists(backup_path):
                try:
                    os.replace(backup_path, dest_path)
                except Exception:
                    pass
            return await ctx.send(f"Failed to write file: {e}")

        # Attempt to unload/load
        try:
            if module_name in self.bot.extensions:
                try:
                    await self.bot.unload_extension(module_name)
                except Exception:
                    # continue; will attempt to load new
                    pass

            # If the module is already in sys.modules, remove it so load_extension imports fresh
            if module_name in sys.modules:
                try:
                    del sys.modules[module_name]
                except Exception:
                    pass

            await self.bot.load_extension(module_name)
        except Exception as e:
            # rollback
            try:
                if backup_path and os.path.exists(backup_path):
                    os.replace(backup_path, dest_path)
                    # try to reload original
                    try:
                        if module_name in self.bot.extensions:
                            await self.bot.unload_extension(module_name)
                        await self.bot.load_extension(module_name)
                    except Exception:
                        pass
            except Exception:
                pass

            return await ctx.send(f"Failed to load extension: {e}")

        # Success - remove backup
        if backup_path and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass

        await ctx.send(f"Extension `{module_name}` installed and loaded successfully.")


async def setup(bot):
    await bot.add_cog(AdminInstall(bot))
