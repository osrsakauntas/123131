import logging
import os
import sqlite3

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("minecraft_applications")


class ApplicationModal(discord.ui.Modal, title="Anketa į Eterija serverį"):
    minecraft_nick = discord.ui.TextInput(
        label="Minecraft slapyvardis",
        placeholder="Įrašykite savo žaidimo slapyvardį",
        custom_id="minecraft_nick",
        max_length=32,
    )
    age = discord.ui.TextInput(
        label="Jūsų amžius",
        placeholder="Įrašykite savo amžių",
        custom_id="age",
        max_length=3,
    )
    playtime = discord.ui.TextInput(
        label="Kiek laiko žaidžiate Minecraft?",
        placeholder="Trumpai papasakokite apie savo patirtį",
        custom_id="playtime",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    server_experience = discord.ui.TextInput(
        label="Patirtis panašiuose serveriuose",
        placeholder="Ar esate žaidę panašiuose serveriuose?",
        custom_id="server_experience",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    motivation = discord.ui.TextInput(
        label="Kodėl norite prisijungti prie serverio?",
        placeholder="Papasakokite, kodėl norėtumėte žaisti pas mus",
        custom_id="motivation",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, bot: "ApplicationBot") -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Anketą galima pildyti tik serveryje.", ephemeral=True
            )
            return

        channel = self.bot.get_channel(self.bot.application_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.bot.application_channel_id)
            except discord.HTTPException:
                logger.exception("Nepavyko rasti anketų kanalo")
                await interaction.response.send_message(
                    "Nepavyko pasiekti anketų kanalo. Praneškite administracijai.",
                    ephemeral=True,
                )
                return

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "Anketų kanalo konfigūracija neteisinga. Praneškite administracijai.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        application_id = await self.bot.create_pending_application(
            interaction.user.id, interaction.guild.id
        )
        if application_id is None:
            await interaction.followup.send(
                "Jūsų anketa jau pateikta ir laukia administracijos sprendimo.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Nauja Minecraft serverio anketa",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Pareiškėjas",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False,
        )
        embed.add_field(name="Minecraft slapyvardis", value=self.minecraft_nick.value, inline=True)
        embed.add_field(name="Amžius", value=self.age.value, inline=True)
        embed.add_field(name="Žaidimo patirtis", value=self.playtime.value, inline=False)
        embed.add_field(
            name="Patirtis panašiuose serveriuose",
            value=self.server_experience.value,
            inline=False,
        )
        embed.add_field(name="Prisijungimo motyvacija", value=self.motivation.value, inline=False)
        embed.set_footer(text=f"Anketos numeris: {application_id}")

        try:
            message = await channel.send(
                embed=embed,
                view=ReviewView(self.bot, application_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            await self.bot.set_application_status(application_id, "delivery_failed")
            logger.exception("Nepavyko išsiųsti anketos į administracijos kanalą")
            await interaction.followup.send(
                "Anketos išsiųsti nepavyko. Pabandykite vėliau arba susisiekite su administracija.",
                ephemeral=True,
            )
            return

        await self.bot.set_application_message(application_id, message.id)
        await interaction.followup.send(
            "Anketa pateikta administracijai. Sprendimo laukite šiame Discord serveryje.",
            ephemeral=True,
        )


class ApplicationButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Pildyti anketą",
            style=discord.ButtonStyle.primary,
            custom_id="application:open",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(self.view, ApplicationPanelView):
            return
        if interaction.guild is None:
            await interaction.response.send_message(
                "Anketą galima pildyti tik serveryje.", ephemeral=True
            )
            return
        if await self.view.bot.get_application_for_user(interaction.user.id):
            await interaction.response.send_message(
                "Jūsų anketa jau pateikta ir laukia administracijos sprendimo.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(ApplicationModal(self.view.bot))


class ApplicationPanelView(discord.ui.View):
    def __init__(self, bot: "ApplicationBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(ApplicationButton())


class DecisionButton(discord.ui.Button):
    def __init__(self, application_id: int, approve: bool) -> None:
        self.approve = approve
        action = "approve" if approve else "reject"
        super().__init__(
            label="Patvirtinti" if approve else "Atmesti",
            style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
            custom_id=f"application:{application_id}:{action}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if isinstance(self.view, ReviewView):
            await self.view.handle_decision(interaction, self.approve)


class ReviewView(discord.ui.View):
    def __init__(self, bot: "ApplicationBot", application_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.application_id = application_id
        self.add_item(DecisionButton(application_id, approve=True))
        self.add_item(DecisionButton(application_id, approve=False))

    async def handle_decision(
        self, interaction: discord.Interaction, approve: bool
    ) -> None:
        if interaction.guild is None or not self.bot.can_review(interaction.user):
            await interaction.response.send_message(
                "Šiuos mygtukus gali naudoti tik administracija.", ephemeral=True
            )
            return

        application = await self.bot.get_application(self.application_id)
        if (
            application is None
            or application[1] != interaction.guild.id
            or application[2] != "pending"
        ):
            await interaction.response.send_message(
                "Ši anketa jau peržiūrėta arba nebegalioja.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        if not await self.bot.claim_application(self.application_id):
            await interaction.followup.send(
                "Šią anketą jau peržiūri kitas administratorius.", ephemeral=True
            )
            return

        if approve:
            role = interaction.guild.get_role(self.bot.player_role_id)
            if role is None:
                await self.bot.set_application_status(self.application_id, "pending")
                await interaction.followup.send(
                    "Žaidėjo rolė nerasta. Patikrinkite boto konfigūraciją.", ephemeral=True
                )
                return

            member = interaction.guild.get_member(application[0])
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(application[0])
                except discord.NotFound:
                    await self.bot.set_application_status(self.application_id, "pending")
                    await interaction.followup.send(
                        "Žaidėjas nebėra šiame Discord serveryje; anketa palikta laukianti.",
                        ephemeral=True,
                    )
                    return
                except discord.HTTPException:
                    await self.bot.set_application_status(self.application_id, "pending")
                    await interaction.followup.send(
                        "Nepavyko rasti žaidėjo. Pabandykite dar kartą.", ephemeral=True
                    )
                    return

            try:
                await member.add_roles(
                    role, reason=f"Minecraft serverio anketa #{self.application_id} patvirtinta"
                )
            except discord.HTTPException:
                await self.bot.set_application_status(self.application_id, "pending")
                logger.exception("Nepavyko priskirti žaidėjo rolės")
                await interaction.followup.send(
                    "Rolės priskirti nepavyko. Patikrinkite boto teises ir rolės hierarchiją.",
                    ephemeral=True,
                )
                return

            await self.bot.set_application_status(self.application_id, "approved")
            await self.finish_message(interaction, "PATVIRTINTA", discord.Color.green())
            await interaction.followup.send(
                "Anketa patvirtinta, žaidėjo rolė priskirta.", ephemeral=True
            )
            return

        await self.bot.set_application_status(self.application_id, "rejected")
        await self.finish_message(interaction, "ATMESTA", discord.Color.red())
        await interaction.followup.send(
            "Anketa atmesta. Žaidėjas gali pateikti naują anketą paspaudęs „Pildyti anketą“ mygtuką.",
            ephemeral=True,
        )

    async def finish_message(
        self,
        interaction: discord.Interaction,
        decision: str,
        color: discord.Color,
    ) -> None:
        self.disable_all_items()
        if interaction.message is None or not interaction.message.embeds:
            return
        embed = interaction.message.embeds[0]
        embed.title = f"Minecraft serverio anketa — {decision}"
        embed.color = color
        embed.add_field(
            name="Sprendė",
            value=interaction.user.mention,
            inline=False,
        )
        try:
            await interaction.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            logger.exception("Nepavyko atnaujinti peržiūrėtos anketos žinutės")


class ApplicationBot(commands.Bot):
    def __init__(
        self,
        application_channel_id: int,
        player_role_id: int,
        admin_role_id: int | None,
    ) -> None:
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.application_channel_id = application_channel_id
        self.player_role_id = player_role_id
        self.admin_role_id = admin_role_id
        self.db: aiosqlite.Connection | None = None

    async def on_ready(self) -> None:
        logger.info("Prisijungta kaip %s", self.user)
        print("KODARI_READY", flush=True)

    async def setup_hook(self) -> None:
        self.db = await aiosqlite.connect("applications.sqlite3")
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_application_per_user
            ON applications(user_id) WHERE status IN ('pending', 'processing');
            """
        )
        await self.db.execute(
            "UPDATE applications SET status = 'delivery_failed' "
            "WHERE status = 'pending' AND message_id IS NULL"
        )
        await self.db.execute(
            "UPDATE applications SET status = 'pending' WHERE status = 'processing'"
        )
        await self.db.commit()

        async with self.db.execute(
            "SELECT id, message_id FROM applications WHERE status = 'pending' AND message_id IS NOT NULL"
        ) as cursor:
            pending = await cursor.fetchall()
        for application_id, message_id in pending:
            self.add_view(ReviewView(self, application_id), message_id=message_id)

        self.add_view(ApplicationPanelView(self))
        self.tree.add_command(make_panel_command(self))
        await self.tree.sync()

    def can_review(self, user: discord.abc.User) -> bool:
        if not isinstance(user, discord.Member):
            return False
        if user.guild_permissions.manage_guild:
            return True
        return self.admin_role_id is not None and any(
            role.id == self.admin_role_id for role in user.roles
        )

    async def create_pending_application(self, user_id: int, guild_id: int) -> int | None:
        assert self.db is not None
        try:
            cursor = await self.db.execute(
                "INSERT INTO applications (user_id, guild_id, status) VALUES (?, ?, 'pending')",
                (user_id, guild_id),
            )
            await self.db.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            await self.db.rollback()
            return None

    async def set_application_message(self, application_id: int, message_id: int) -> None:
        assert self.db is not None
        await self.db.execute(
            "UPDATE applications SET message_id = ? WHERE id = ?",
            (message_id, application_id),
        )
        await self.db.commit()

    async def set_application_status(self, application_id: int, status: str) -> None:
        assert self.db is not None
        await self.db.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (status, application_id),
        )
        await self.db.commit()

    async def get_application(self, application_id: int) -> tuple[int, int, str] | None:
        assert self.db is not None
        async with self.db.execute(
            "SELECT user_id, guild_id, status FROM applications WHERE id = ?",
            (application_id,),
        ) as cursor:
            return await cursor.fetchone()

    async def claim_application(self, application_id: int) -> bool:
        assert self.db is not None
        cursor = await self.db.execute(
            "UPDATE applications SET status = 'processing' WHERE id = ? AND status = 'pending'",
            (application_id,),
        )
        await self.db.commit()
        return cursor.rowcount == 1


def make_panel_command(bot: ApplicationBot) -> app_commands.Command:
    @app_commands.command(
        name="anketos-skydelis", description="Paskelbti anketos pildymo mygtuką šiame kanale"
    )
    @app_commands.guild_only()
    async def anketos_skydelis(interaction: discord.Interaction) -> None:
        if interaction.guild is None or not bot.can_review(interaction.user):
            await interaction.response.send_message(
                "Šią komandą gali naudoti tik administracija serveryje.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "Anketos skydelio šiame kanale paskelbti negalima.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="Anketa į Minecraft serverį",
            description="Norite prisijungti prie serverio? Paspauskite mygtuką ir užpildykite anketą.",
            color=discord.Color.blurple(),
        )
        try:
            await interaction.channel.send(embed=embed, view=ApplicationPanelView(bot))
        except discord.Forbidden:
            await interaction.response.send_message(
                "Botas neturi teisių šiame kanale. Suteikite jam „View Channel“, "
                "„Send Messages“ ir „Embed Links“ teises, tada bandykite dar kartą.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Nepavyko paskelbti anketos skydelio")
            await interaction.response.send_message(
                "Nepavyko paskelbti anketos skydelio. Pabandykite dar kartą.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Anketos pildymo mygtukas paskelbtas šiame kanale.", ephemeral=True
        )

    return anketos_skydelis


async def get_application_for_user(self: ApplicationBot, user_id: int) -> bool:
    assert self.db is not None
    async with self.db.execute(
        "SELECT 1 FROM applications WHERE user_id = ? AND status IN ('pending', 'processing') LIMIT 1",
        (user_id,),
    ) as cursor:
        return await cursor.fetchone() is not None


ApplicationBot.get_application_for_user = get_application_for_user


def read_id(name: str, required: bool = True) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        if required:
            raise ValueError(f"Nenurodytas {name} kintamasis .env faile")
        return None
    try:
        identifier = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} turi būti Discord ID skaičius") from exc
    if identifier <= 0:
        if required:
            raise ValueError(f"{name} turi būti pakeistas tikru Discord ID")
        return None
    return identifier


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "your_discord_bot_token_here":
        logger.error("Nurodykite DISCORD_TOKEN .env faile")
        return
    try:
        application_channel_id = read_id("APPLICATION_CHANNEL_ID")
        player_role_id = read_id("PLAYER_ROLE_ID")
        admin_role_id = read_id("ADMIN_ROLE_ID", required=False)
    except ValueError as exc:
        logger.error("Boto konfigūracijos klaida: %s", exc)
        return

    bot = ApplicationBot(application_channel_id, player_role_id, admin_role_id)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()