import os
import re
import logging
from io import BytesIO
from PIL import Image, ImageEnhance, ImageOps
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
import requests
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
SPOTIPY_CLIENT_ID = '23c490f6a1244ff490455965ea7e2c67'
SPOTIPY_CLIENT_SECRET = 'eb652a87c0f944948ba930a1f46c7314'
TELEGRAM_TOKEN = '7600550214:AAGeP6kvbSF4pLt5gaXrWvVgOnwON1Or7SY'

# Инициализация Spotify
auth_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
sp = spotipy.Spotify(auth_manager=auth_manager)

# Временная директория
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

def sanitize_filename(filename):
    """Очистка имени файла от недопустимых символов"""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "✨🌈 <b>Привет!</b> Отправь мне ссылку на трек, альбом или плейлист из <b>Spotify</b>, "
        "и я пришлю тебе MP3-файл <i>с обложкой и метаданными.</i>\n\n"
        "<b>Проект лейбла Sovietwave Records: @swr24</b>",
        parse_mode="HTML"
    )  

async def handle_spotify_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик Spotify-ссылок"""
    url = update.message.text.strip()
    chat_id = update.message.chat_id

    if 'open.spotify.com/track/' in url:
        await process_spotify_track(url, chat_id, context)
    elif 'open.spotify.com/album/' in url:
        await process_spotify_album(url, chat_id, context)
    elif 'open.spotify.com/playlist/' in url:
        await process_spotify_playlist(url, chat_id, context)
    else:
        await update.message.reply_text("Неподдерживаемый формат ссылки. Пожалуйста, отправьте ссылку на трек, альбом или плейлист Spotify.")

async def process_spotify_track(track_url, chat_id, context):
    """Обработка отдельного трека"""
    track_info = sp.track(track_url)
    artists = ", ".join([artist['name'] for artist in track_info['artists']])
    track_name = track_info['name']
    query = f"{artists} - {track_name}"

    await context.bot.send_message(chat_id, f"🔍 Ищу: {query}")

    mp3_path = await download_from_youtube(query)
    cover_url = get_highest_resolution_cover(track_info['album']['images'])
    metadata = {
        'title': track_name,
        'artist': artists,
        'album': track_info['album']['name']
    }

    embed_cover_to_mp3(mp3_path, cover_url, metadata)

    with open(mp3_path, 'rb') as audio_file:
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=InputFile(audio_file),
            title=track_name,
            performer=artists
        )
    os.remove(mp3_path)

async def download_from_youtube(query):
    """Скачивание аудио с YouTube"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(TEMP_DIR, f'{sanitize_filename(query)}.%(ext)s'),
        'quiet': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f'ytsearch:{query}'])
    return os.path.join(TEMP_DIR, f"{sanitize_filename(query)}.mp3")

def get_highest_resolution_cover(images):
    """Получение обложки максимального качества"""
    return max(images, key=lambda x: x['width'])['url']

def enhance_and_resize_image(image_data, target_size=(3000, 3000), dpi=300):
    """Улучшение и масштабирование изображения"""
    with Image.open(BytesIO(image_data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ['RGB', 'L']:
            img = img.convert('RGB')

        original_ratio = img.width / img.height
        target_ratio = target_size[0] / target_size[1]

        if original_ratio != target_ratio:
            if original_ratio > target_ratio:
                new_height = img.height
                new_width = int(img.height * target_ratio)
                left = (img.width - new_width) // 2
                img = img.crop((left, 0, left + new_width, new_height))
            else:
                new_width = img.width
                new_height = int(img.width / target_ratio)
                top = (img.height - new_height) // 2
                img = img.crop((0, top, new_width, top + new_height))

        if img.width < target_size[0] or img.height < target_size[1]:
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.15)
            img = img.resize(target_size, Image.LANCZOS)
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.05)
        else:
            img.thumbnail(target_size, Image.LANCZOS)

        img.info['dpi'] = (dpi, dpi)

        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=100, subsampling=0, optimize=True, progressive=True)
        return buffer.getvalue()

def embed_cover_to_mp3(mp3_path, cover_url, track_metadata):
    """Добавление обложки и метаданных в MP3"""
    response = requests.get(cover_url)
    cover_data = response.content
    enhanced_cover = enhance_and_resize_image(cover_data)

    audio = MP3(mp3_path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()

    audio["TIT2"] = TIT2(encoding=3, text=track_metadata['title'])
    audio["TPE1"] = TPE1(encoding=3, text=track_metadata['artist'])
    audio["TALB"] = TALB(encoding=3, text=track_metadata['album'])

    audio.tags.add(
        APIC(
            encoding=3,
            mime='image/jpeg',
            type=3,
            desc='Cover',
            data=enhanced_cover
        )
    )
    audio.save(v2_version=3)

async def process_spotify_album(album_url, chat_id, context):
    """Обработка альбома"""
    album = sp.album(album_url)
    await context.bot.send_message(chat_id, f"🔍 Начинаю обработку альбома: {album['name']}")

    cover_url = get_highest_resolution_cover(album['images'])
    tracks = sp.album_tracks(album_url)['items']

    for track in tracks:
        await process_track_from_album(track, album['name'], cover_url, chat_id, context)

async def process_track_from_album(track, album_name, cover_url, chat_id, context):
    """Обработка трека из альбома"""
    artists = ", ".join([artist['name'] for artist in track['artists']])
    track_name = track['name']
    query = f"{artists} - {track_name}"

    mp3_path = await download_from_youtube(query)
    metadata = {
        'title': track_name,
        'artist': artists,
        'album': album_name
    }

    embed_cover_to_mp3(mp3_path, cover_url, metadata)

    with open(mp3_path, 'rb') as audio_file:
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=InputFile(audio_file),
            title=track_name,
            performer=artists
        )
    os.remove(mp3_path)

async def process_spotify_playlist(playlist_url, chat_id, context):
    """Обработка плейлиста"""
    playlist = sp.playlist(playlist_url)
    await context.bot.send_message(chat_id, f"🔍 Начинаю обработку плейлиста: {playlist['name']}")

    cover_url = get_highest_resolution_cover(playlist['images']) if playlist['images'] else None
    results = sp.playlist_tracks(playlist_url)
    tracks = results['items']

    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])

    for item in tracks:
        track = item['track']
        if track:
            await process_track_from_playlist(track, playlist['name'], cover_url, chat_id, context)

async def process_track_from_playlist(track, playlist_name, playlist_cover_url, chat_id, context):
    """Обработка трека из плейлиста"""
    artists = ", ".join([artist['name'] for artist in track['artists']])
    track_name = track['name']
    query = f"{artists} - {track_name}"

    mp3_path = await download_from_youtube(query)
    cover_url = playlist_cover_url or get_highest_resolution_cover(track['album']['images'])
    metadata = {
        'title': track_name,
        'artist': artists,
        'album': track['album']['name']
    }

    embed_cover_to_mp3(mp3_path, cover_url, metadata)

    with open(mp3_path, 'rb') as audio_file:
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=InputFile(audio_file),
            title=track_name,
            performer=artists
        )
    os.remove(mp3_path)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")
    if update.message:
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте ещё раз.")

def main():
    """Запуск бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spotify_link))
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == "__main__":
    main()