# extensions/core.py

import os
import sys
import asyncio
import subprocess
import re
import threading
import json
from typing import Optional
import discord
from discord.ext import commands, tasks
from config import ADMIN_ID, CHANNEL_ID
from utils.data_manager import load_all, save_all
import aiohttp
from utils.data_manager import load_json
from utils import load_banned_words, load_triggers, get_cid_to_monitor
from utils import save_banned_words, save_triggers, save_cid_monitor
from datetime import timedelta
from discord.utils import utcnow

banned_words = {}
banned_word_triggers = {}
decay_control = {'active': True}


class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.save_data_periodically.start()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Logged in as {self.bot.user}")
        self.load_data()

        if not hasattr(self.bot, 'session'):
            self.bot.session = aiohttp.ClientSession()


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Forward non-command DMs only
        if isinstance(message.channel, discord.DMChannel) and not message.content.startswith("!"):
            channel = self.bot.get_channel(CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    description=f"From: {message.author.mention}\n\n{message.content}",
                    timestamp=utcnow(),
                    color=discord.Color.green()
                )
                embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)

                if message.attachments:
                    files = [await attachment.to_file() for attachment in message.attachments]
                    await channel.send(embed=embed, files=files)
                else:
                    await channel.send(embed=embed)

    @commands.command(name="dm")
    async def dm_command(self, ctx, user_or_name: Optional[str] = None, *, content: Optional[str] = None):
        """Send a DM to a user. Usage: !dm @user <message>"""

        if user_or_name is None or content is None:
            return await ctx.send("Usage: !dm @User <message>")

        try:
            converter = commands.UserConverter()
            user = await converter.convert(ctx, user_or_name)
        except commands.UserNotFound:
            return await ctx.send(f"User '{user_or_name}' not found.")

        if not content.strip():
            return await ctx.send("Please include a message to send.")

        try:
            embed = discord.Embed(
                description=f"From: {ctx.author.mention}\n\n{content}",
                timestamp=utcnow(),
                color=discord.Color.green()
            )
            embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)

            await user.send(embed=embed)
            await ctx.send(f"Message sent to {user.name}.")
        except Exception as e:
            await ctx.send(f"Failed to send message: {e}")

    @tasks.loop(minutes=60)
    async def save_data_periodically(self):
        self.save_data()

    def save_data(self):
        save_all()
        print("Data saved successfully.")

    def load_data(self):
        global banned_words, banned_word_triggers

        try:
            state = load_all()
            banned_words.update(state.get('banned_words', {}))
            banned_word_triggers.update(state.get('banned_word_triggers', {}))
            print("Data loaded successfully.")
        except Exception as e:
            print(f"Error loading data: {e}")

    @commands.command()
    async def update(self, ctx):
        """Pull latest code from GitHub (admin only)"""
        if ctx.author.id != ADMIN_ID:
            await ctx.send("Unauthorized.")
            return
        # Run git pull in a thread to avoid blocking
        git_res = await asyncio.to_thread(subprocess.run, ["git", "pull"], capture_output=True, text=True)
        git_out = (git_res.stdout or "") + ("\n" + git_res.stderr if git_res.stderr else "")
        await ctx.send(f"Git pull result:\n```{git_out[:1900]}```")

        # Attempt to install requirements (if any)
        req_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements.txt")
        if os.path.exists(req_path):
            await ctx.send("Installing requirements from requirements.txt...")
            pip_res = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pip", "install", "-r", req_path], capture_output=True, text=True)
            pip_out = (pip_res.stdout or "") + ("\n" + pip_res.stderr if pip_res.stderr else "")

            # Only report pip output if install failed or packages were actually installed.
            if pip_res.returncode != 0:
                await ctx.send(f"Pip install FAILED:\n```{pip_out[:1800]}```")
            else:
                # Try to detect installed packages from pip output.
                installed = []
                m = re.search(r"Successfully installed (.+)", pip_out)
                if m:
                    tokens = m.group(1).strip().split()
                    installed.extend(tokens)
                else:
                    m2 = re.search(r"Installing collected packages: (.+)", pip_out)
                    if m2:
                        tokens = [p.strip().strip(',') for p in m2.group(1).split(',') if p.strip()]
                        installed.extend(tokens)

                if installed:
                    # Clean tokens to show package names (strip versions if present)
                    cleaned = []
                    for tok in installed:
                        tok = tok.strip().strip(',')
                        mname = re.match(r"^([A-Za-z0-9_.+-]+)", tok)
                        cleaned.append(mname.group(1) if mname else tok)
                    await ctx.send(f"Pip installed: {', '.join(cleaned)}")
        else:
            await ctx.send("No requirements.txt found; skipping pip install.")

    @commands.command()
    async def restartlinux(self, ctx):
        """Update and restart the bot on Linux (admin only)."""
        if ctx.author.id != ADMIN_ID:
            await ctx.send("Unauthorized.")
            return
        # Run git pull
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "pull"],
            capture_output=True,
            text=True,
        )

        pull_output = (result.stdout or "").strip()
        if result.stderr:
            pull_output += "\n" + result.stderr.strip()

        await ctx.send(f"Git pull result:\n```{pull_output[:1800]}```")

        if "Already up to date" not in pull_output:
            # Show recent commits
            log_result = subprocess.run(
                ["git", "log", "--oneline", "-3"],
                capture_output=True,
                text=True,
            )
            log_output = log_result.stdout.strip()
            if log_output:
                await ctx.send(f"Recent commits:\n```{log_output}```")

            # Show changed files summary
            stat_result = subprocess.run(
                ["git", "diff", "--stat", "HEAD~3..HEAD"],
                capture_output=True,
                text=True,
            )
            stat_output = stat_result.stdout.strip()
            if stat_output:
                await ctx.send(f"Changes summary:\n```{stat_output}```")

        self.save_data()

        # Install requirements
        req_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "requirements.txt",
        )

        if os.path.exists(req_path):
            await ctx.send("Installing requirements before restart...")
            pip_res = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pip", "install", "-r", req_path],
                capture_output=True,
                text=True,
            )

            pip_out = (pip_res.stdout or "") + ("\n" + pip_res.stderr if pip_res.stderr else "")

            if pip_res.returncode != 0:
                await ctx.send(f"Pip install FAILED:\n```{pip_out[:1800]}```")
            else:
                installed = []
                m = re.search(r"Successfully installed (.+)", pip_out)
                if m:
                    installed.extend(m.group(1).strip().split())
                else:
                    m2 = re.search(r"Installing collected packages: (.+)", pip_out)
                    if m2:
                        installed.extend([p.strip().strip(',') for p in m2.group(1).split(',')])

                if installed:
                    await ctx.send(f"Pip installed: {', '.join(installed)}")

        # Trigger systemd restart
        await ctx.send("Restarting bot via systemd...")
        os._exit(1)  # systemd sees this as a failure → restarts bot

    @commands.command()
    async def shutdown(self, ctx):
        """Shut down the bot (admin only)"""
        if ctx.author.id != ADMIN_ID:
            await ctx.send("You are not authorized to shut me down.")
            return

        self.save_data()
        await ctx.send("Shutting down...")
        await self.bot.close()

    @commands.command()
    async def loadext(self, ctx, ext_name: str):
        """Load an extension at runtime (admin only)"""
        if ctx.author.id != ADMIN_ID:
            await ctx.send("You are not authorized to load extensions.")
            return

        try:
            await self.bot.load_extension(ext_name)
            await ctx.send(f"Loaded extension: {ext_name}")
        except Exception as e:
            await ctx.send(f"Failed to load extension {ext_name}: {e}")

    @commands.command()
    async def unloadext(self, ctx, ext_name: str):
        """Unload an extension at runtime (admin only)"""
        if ctx.author.id != ADMIN_ID:
            await ctx.send("You are not authorized to unload extensions.")
            return

        try:
            await self.bot.unload_extension(ext_name)
            await ctx.send(f"Unloaded extension: {ext_name}")
        except Exception as e:
            await ctx.send(f"Failed to unload extension {ext_name}: {e}")

    @commands.command()
    async def restart(self, ctx):
        """Update and restart the bot (admin only)"""
        if ctx.author.id != ADMIN_ID:
            await ctx.send("Unauthorized.")
            return
        # Run git pull
        result = await asyncio.to_thread(subprocess.run, ["git", "pull"], capture_output=True, text=True)
        pull_output = (result.stdout or "").strip()
        if result.stderr:
            pull_output += "\n" + result.stderr.strip()
        await ctx.send(f"Git pull result:\n```{pull_output[:1800]}```")
        
        if "Already up to date" not in pull_output:
            # Show what changed
            log_result = subprocess.run(["git", "log", "--oneline", "-3"], capture_output=True, text=True)
            log_output = log_result.stdout.strip()
            if log_output:
                await ctx.send(f"Recent commits:\n```{log_output}```")
            
            stat_result = subprocess.run(["git", "diff", "--stat", "HEAD~3..HEAD"], capture_output=True, text=True)
            stat_output = stat_result.stdout.strip()
            if stat_output:
                await ctx.send(f"Changes summary:\n```{stat_output}```")

        self.save_data()
        # Install requirements before restart
        req_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements.txt")
        if os.path.exists(req_path):
            await ctx.send("Installing requirements from requirements.txt before restart...")
            pip_res = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pip", "install", "-r", req_path], capture_output=True, text=True)
            pip_out = (pip_res.stdout or "") + ("\n" + pip_res.stderr if pip_res.stderr else "")

            # Only report pip output if install failed or packages were actually installed.
            if pip_res.returncode != 0:
                await ctx.send(f"Pip install FAILED:\n```{pip_out[:1800]}```")
            else:
                installed = []
                m = re.search(r"Successfully installed (.+)", pip_out)
                if m:
                    tokens = m.group(1).strip().split()
                    installed.extend(tokens)
                else:
                    m2 = re.search(r"Installing collected packages: (.+)", pip_out)
                    if m2:
                        tokens = [p.strip().strip(',') for p in m2.group(1).split(',') if p.strip()]
                        installed.extend(tokens)

                if installed:
                    cleaned = []
                    for tok in installed:
                        tok = tok.strip().strip(',')
                        mname = re.match(r"^([A-Za-z0-9_.+-]+)", tok)
                        cleaned.append(mname.group(1) if mname else tok)
                    await ctx.send(f"Pip installed: {', '.join(cleaned)}")

        await ctx.send("Updating and restarting...")
        await self.bot.close()


async def setup(bot):
    await bot.add_cog(Core(bot))
