import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord import app_commands
from supabase import create_client

AUTOROL = "Miembro"
XP_MIN = 15
XP_MAX = 25
COOLDOWN = 60

NIVELES_ROL = [
    (5, "Miembro"),
    (10, "🕷️・Spider"),
    (15, "🕸️・Spider-Man"),
    (20, "✨・Spectacular"),
    (30, "💫・Amazing"),
    (40, "🟠・Ultimate"),
    (50, "🔴・Legendary"),
]


def cargar_env(ruta=".env"):
    if not os.path.exists(ruta):
        return
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip())


def xp_para_nivel(nivel):
    return 5 * (nivel ** 2) + 50 * nivel + 100


def nivel_desde_xp(xp):
    nivel = 0
    while xp >= xp_para_nivel(nivel):
        xp -= xp_para_nivel(nivel)
        nivel += 1
    return nivel


cargar_env()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

cooldowns = {}


def obtener_xp(gid, uid):
    res = (supabase.table("niveles").select("xp")
           .eq("guild_id", str(gid)).eq("user_id", str(uid)).execute())
    return res.data[0]["xp"] if res.data else 0


def sumar_xp(gid, uid, cantidad):
    actual = obtener_xp(gid, uid)
    nuevo = actual + cantidad
    supabase.table("niveles").upsert(
        {"guild_id": str(gid), "user_id": str(uid), "xp": nuevo},
        on_conflict="guild_id,user_id",
    ).execute()
    return nuevo


def reiniciar_xp(gid, uid):
    supabase.table("niveles").upsert(
        {"guild_id": str(gid), "user_id": str(uid), "xp": 0},
        on_conflict="guild_id,user_id",
    ).execute()


def ranking(gid, limite=10):
    res = (supabase.table("niveles").select("user_id,xp")
           .eq("guild_id", str(gid)).order("xp", desc=True).limit(limite).execute())
    return res.data


async def aplicar_roles_nivel(member, nivel):
    for lvl, nombre in NIVELES_ROL:
        rol = discord.utils.get(member.guild.roles, name=nombre)
        if rol is None:
            continue
        try:
            if nivel >= lvl:
                if rol not in member.roles:
                    await member.add_roles(rol, reason=f"Nivel {lvl}")
            elif rol in member.roles:
                await member.remove_roles(rol, reason="Recompensa superior")
        except discord.Forbidden:
            print("Sin permisos para gestionar roles de nivel")


@client.event
async def on_ready():
    print(f"Conectado como {client.user} ({len(client.guilds)} servidores)")
    for guild in client.guilds:
        if discord.utils.get(guild.roles, name=AUTOROL) is None:
            await guild.create_role(name=AUTOROL, colour=discord.Colour.greyple())
            print(f"Rol '{AUTOROL}' creado en {guild.name}")
    try:
        await tree.sync()
        print("Comandos sincronizados")
    except Exception as e:
        print("No se pudieron sincronizar comandos:", e)


@client.event
async def on_member_join(member):
    rol = discord.utils.get(member.guild.roles, name=AUTOROL)
    if rol is None:
        return
    try:
        await member.add_roles(rol, reason="Autorol de bienvenida")
    except discord.Forbidden:
        print("Sin permisos para el autorol")


@client.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    # Detección flexible del canal de confesiones (por texto en el nombre)
    nombre_canal = message.channel.name.lower() if message.channel.name else ""
    if "confesion" in nombre_canal:
        try:
            await message.delete()
            embed = discord.Embed(
                title="💌 Nueva Confesión Anónima",
                description=message.content,
                colour=discord.Colour.purple()
            )
            embed.set_footer(text="Enviado de forma anónima en el servidor.")
            await message.channel.send(embed=embed)
        except Exception as e:
            print("Error procesando confesión anónima:", e)
        return

    ahora = time.time()
    clave = (message.guild.id, message.author.id)
    if ahora - cooldowns.get(clave, 0) < COOLDOWN:
        return
    cooldowns[clave] = ahora

    antes = nivel_desde_xp(obtener_xp(message.guild.id, message.author.id))
    nuevo_xp = sumar_xp(message.guild.id, message.author.id, random.randint(XP_MIN, XP_MAX))
    despues = nivel_desde_xp(nuevo_xp)

    if despues > antes:
        await message.channel.send(f"🎉 {message.author.mention} subió al **nivel {despues}**!")
        await aplicar_roles_nivel(message.author, despues)


@tree.command(name="nivel", description="Muestra tu nivel o el de otro usuario")
async def nivel(interaction: discord.Interaction, usuario: discord.Member = None):
    usuario = usuario or interaction.user
    xp = obtener_xp(interaction.guild.id, usuario.id)
    lv = nivel_desde_xp(xp)
    falta = xp_para_nivel(lv) - (xp % xp_para_nivel(lv) if xp else 0)
    embed = discord.Embed(title=f"Nivel de {usuario.display_name}", colour=discord.Colour.blurple())
    embed.add_field(name="Nivel", value=str(lv))
    embed.add_field(name="XP total", value=str(xp))
    embed.add_field(name="Falta para subir", value=str(falta) + " XP")
    embed.set_thumbnail(url=usuario.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@tree.command(name="top", description="Ranking de los más activos")
async def top(interaction: discord.Interaction):
    datos = ranking(interaction.guild.id)
    if not datos:
        await interaction.response.send_message("Todavía no hay datos de actividad.")
        return
    lineas = []
    for i, fila in enumerate(datos, 1):
        miembro = interaction.guild.get_member(int(fila["user_id"]))
        nombre = miembro.display_name if miembro else f"Usuario {fila['user_id']}"
        lineas.append(f"**{i}.** {nombre} — Nv.{nivel_desde_xp(fila['xp'])} ({fila['xp']} XP)")
    embed = discord.Embed(title="🏆 Top 10 más activos", description="\n".join(lineas),
                          colour=discord.Colour.gold())
    await interaction.response.send_message(embed=embed)


@tree.command(name="solo_comandos", description="Bloquea el canal actual en modo solo comandos")
@app_commands.default_permissions(administrator=True)
async def solo_comandos(interaction: discord.Interaction):
    canal = interaction.channel
    everyone = interaction.guild.default_role
    await canal.set_permissions(everyone, send_messages=False, reason="Modo solo comandos por bot")
    await interaction.response.send_message(f"🔒 Canal {canal.mention} configurado en modo **solo comandos**.", ephemeral=True)


@tree.command(name="resetxp", description="Reinicia el XP de un usuario (staff)")
@app_commands.default_permissions(administrator=True)
async def resetxp(interaction: discord.Interaction, usuario: discord.Member):
    reiniciar_xp(interaction.guild.id, usuario.id)
    await interaction.response.send_message(f"XP de {usuario.mention} reiniciado.", ephemeral=True)


def keepalive():
    puerto = int(os.environ.get("PORT", 8080))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot activo")

        def log_message(self, *args):
            pass

    HTTPServer(("0.0.0.0", puerto), Handler).serve_forever()


threading.Thread(target=keepalive, daemon=True).start()

token = os.environ.get("DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_TOKEN")
if not token:
    raise SystemExit("Falta DISCORD_BOT_TOKEN (en .env o variable de entorno)")
client.run(token)
