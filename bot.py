import logging
import os
from datetime import datetime
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import google.generativeai as genai

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Timezone Indonesia
WIB = pytz.timezone('Asia/Jakarta')

# Setup Gemini
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# Koneksi Google Sheets
def get_sheet():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds_json = os.environ.get('GOOGLE_CREDS')
    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open('Data Kantin')
    return sheet

# State untuk conversation
(KULAKAN_NAMA, KULAKAN_TEMPAT, KULAKAN_HARGA, KULAKAN_JUMLAH,
 KANTIN_NAMA, KANTIN_JUMLAH,
 JUAL_NAMA, JUAL_JUMLAH, JUAL_HARGA,
 PRODUK_NAMA, PRODUK_SATUAN) = range(11)

# ================================
# MENU UTAMA
# ================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ['📦 Catat Kulakan', '🏪 Stok ke Kantin'],
        ['💰 Catat Penjualan', '📊 Lihat Laporan'],
        ['📋 Lihat Stok', '➕ Tambah Produk'],
        ['📸 Foto Nota']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        '🐸 *Selamat datang di Bot Kasir Kantin!*\n\nPilih menu di bawah:',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# ================================
# FOTO NOTA — BACA PAKAI GEMINI
# ================================
async def foto_nota_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '📸 *Kirim Foto Nota*\n\n'
        'Silakan kirim foto nota belanja kamu.\n'
        'Bot akan otomatis membaca dan menyimpan datanya!\n\n'
        '_Pastikan foto jelas dan tidak blur ya_ 😊',
        parse_mode='Markdown'
    )
    context.user_data['waiting_nota'] = True

async def proses_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_nota'):
        return

    await update.message.reply_text('⏳ Sedang membaca nota, tunggu sebentar...')

    try:
        # Download foto dari Telegram
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()

        # Kirim ke Gemini untuk dibaca
        import base64
        image_base64 = base64.b64encode(file_bytes).decode('utf-8')

        prompt = """
        Kamu adalah asisten kasir. Baca nota belanja ini dan ekstrak semua item.
        
        Kembalikan dalam format JSON seperti ini:
        {
            "tempat_beli": "nama toko",
            "tanggal": "tanggal pada nota atau kosong",
            "items": [
                {
                    "nama": "nama produk",
                    "jumlah": angka,
                    "harga_satuan": angka,
                    "total": angka
                }
            ],
            "total_semua": angka
        }
        
        Jika tidak bisa baca dengan jelas, isi dengan data yang bisa terbaca saja.
        Kembalikan JSON saja tanpa penjelasan lain.
        """

        response = gemini_model.generate_content([
            prompt,
            {
                "mime_type": "image/jpeg",
                "data": image_base64
            }
        ])
        hasil_text = response.text.strip()

        # Bersihkan response
        if '```json' in hasil_text:
            hasil_text = hasil_text.split('```json')[1].split('```')[0].strip()
        elif '```' in hasil_text:
            hasil_text = hasil_text.split('```')[1].split('```')[0].strip()

        hasil = json.loads(hasil_text)

        # Simpan ke Google Sheets
        sheet = get_sheet()
        ws = sheet.worksheet('Kulakan')
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')
        tempat = hasil.get('tempat_beli', 'Tidak diketahui')

        pesan = f'✅ *Nota berhasil dibaca!*\n\n'
        pesan += f'🏪 Tempat: {tempat}\n\n'
        pesan += f'📦 *Item yang tersimpan:*\n'

        for item in hasil.get('items', []):
            nama = item.get('nama', '-')
            jumlah = item.get('jumlah', 0)
            harga = item.get('harga_satuan', 0)
            total = item.get('total', harga * jumlah)

            ws.append_row([tanggal, nama, tempat, harga, jumlah, total])
            pesan += f'• {nama} x{jumlah} @ Rp{harga:,} = Rp{total:,}\n'

        total_semua = hasil.get('total_semua', 0)
        pesan += f'\n💰 *Total: Rp{total_semua:,}*'
        pesan += f'\n\n_Semua item sudah tersimpan ke sheet Kulakan_ ✅'

        await update.message.reply_text(pesan, parse_mode='Markdown')

    except json.JSONDecodeError:
        await update.message.reply_text(
            '⚠️ Bot bisa baca notanya tapi format kurang jelas.\n'
            'Coba foto lebih dekat dan pastikan tulisan terlihat jelas ya!'
        )
    except Exception as e:
        logger.error(f'Error proses foto: {e}')
        await update.message.reply_text(
            '❌ Gagal membaca nota. Pastikan:\n'
            '• Foto cukup terang\n'
            '• Tulisan tidak blur\n'
            '• Coba foto ulang lebih dekat'
        )

    context.user_data['waiting_nota'] = False

# ================================
# TAMBAH PRODUK BARU
# ================================
async def tambah_produk_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Nama snack baru? (contoh: Chitato, Taro, dll)')
    return PRODUK_NAMA

async def produk_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['produk_nama'] = update.message.text.strip()
    await update.message.reply_text('Satuannya apa? (contoh: pcs, bungkus, pak)')
    return PRODUK_SATUAN

async def produk_satuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nama = context.user_data['produk_nama']
    satuan = update.message.text.strip()
    try:
        sheet = get_sheet()
        ws = sheet.worksheet('Produk')
        data = ws.get_all_values()
        id_baru = len(data)
        ws.append_row([id_baru, nama, satuan])
        await update.message.reply_text(f'✅ Produk *{nama}* berhasil ditambahkan!', parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
    return ConversationHandler.END

# ================================
# CATAT KULAKAN
# ================================
async def kulakan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('📦 *Catat Kulakan Baru*\n\nNama snack yang dibeli?', parse_mode='Markdown')
    return KULAKAN_NAMA

async def kulakan_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['kulakan_nama'] = update.message.text.strip()
    await update.message.reply_text('Beli di mana? (contoh: Alfamart, Toko Pak Budi)')
    return KULAKAN_TEMPAT

async def kulakan_tempat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['kulakan_tempat'] = update.message.text.strip()
    await update.message.reply_text('Harga beli per pcs/bungkus? (angka saja, contoh: 2000)')
    return KULAKAN_HARGA

async def kulakan_harga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['kulakan_harga'] = int(update.message.text.strip())
        await update.message.reply_text('Beli berapa banyak?')
        return KULAKAN_JUMLAH
    except:
        await update.message.reply_text('❌ Masukkan angka saja ya!')
        return KULAKAN_HARGA

async def kulakan_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        jumlah = int(update.message.text.strip())
        nama = context.user_data['kulakan_nama']
        tempat = context.user_data['kulakan_tempat']
        harga = context.user_data['kulakan_harga']
        total = harga * jumlah
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')

        sheet = get_sheet()
        ws = sheet.worksheet('Kulakan')
        ws.append_row([tanggal, nama, tempat, harga, jumlah, total])

        await update.message.reply_text(
            f'✅ *Kulakan tercatat!*\n\n'
            f'🛍 Snack: {nama}\n'
            f'🏪 Tempat: {tempat}\n'
            f'💵 Harga beli: Rp{harga:,}\n'
            f'📦 Jumlah: {jumlah}\n'
            f'💰 Total bayar: Rp{total:,}',
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
    return ConversationHandler.END

# ================================
# STOK KE KANTIN
# ================================
async def kantin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('🏪 *Stok Masuk Kantin*\n\nNama snack yang dibawa ke kantin?', parse_mode='Markdown')
    return KANTIN_NAMA

async def kantin_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['kantin_nama'] = update.message.text.strip()
    await update.message.reply_text('Berapa jumlah yang dibawa ke kantin?')
    return KANTIN_JUMLAH

async def kantin_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        jumlah = int(update.message.text.strip())
        nama = context.user_data['kantin_nama']
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')

        sheet = get_sheet()
        ws = sheet.worksheet('Kantin')
        ws.append_row([tanggal, nama, jumlah])

        await update.message.reply_text(
            f'✅ *Stok kantin tercatat!*\n\n'
            f'🍿 Snack: {nama}\n'
            f'📦 Jumlah: {jumlah}',
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
    return ConversationHandler.END

# ================================
# CATAT PENJUALAN
# ================================
async def jual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('💰 *Catat Penjualan*\n\nNama snack yang terjual?', parse_mode='Markdown')
    return JUAL_NAMA

async def jual_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['jual_nama'] = update.message.text.strip()
    await update.message.reply_text('Berapa yang terjual?')
    return JUAL_JUMLAH

async def jual_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['jual_jumlah'] = int(update.message.text.strip())
        await update.message.reply_text('Harga jual per pcs? (angka saja)')
        return JUAL_HARGA
    except:
        await update.message.reply_text('❌ Masukkan angka saja ya!')
        return JUAL_JUMLAH

async def jual_harga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        harga = int(update.message.text.strip())
        nama = context.user_data['jual_nama']
        jumlah = context.user_data['jual_jumlah']
        total = harga * jumlah
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')

        sheet = get_sheet()
        ws = sheet.worksheet('Penjualan')
        ws.append_row([tanggal, nama, jumlah, harga, total])

        await update.message.reply_text(
            f'✅ *Penjualan tercatat!*\n\n'
            f'🍿 Snack: {nama}\n'
            f'📦 Terjual: {jumlah}\n'
            f'💵 Harga jual: Rp{harga:,}\n'
            f'💰 Total: Rp{total:,}',
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
    return ConversationHandler.END

# ================================
# LIHAT STOK
# ================================
async def lihat_stok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        kulakan = sheet.worksheet('Kulakan').get_all_records()
        penjualan = sheet.worksheet('Penjualan').get_all_records()

        stok = {}
        for row in kulakan:
            nama = row['Nama_Snack']
            stok[nama] = stok.get(nama, 0) + int(row['Jumlah'])

        for row in penjualan:
            nama = row['Nama_Snack']
            stok[nama] = stok.get(nama, 0) - int(row['Jumlah_Terjual'])

        if not stok:
            await update.message.reply_text('Belum ada data stok.')
            return

        pesan = '📋 *Stok Saat Ini:*\n\n'
        for nama, jumlah in stok.items():
            emoji = '✅' if jumlah > 5 else '⚠️'
            pesan += f'{emoji} {nama}: *{jumlah}* pcs\n'

        await update.message.reply_text(pesan, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')

# ================================
# LAPORAN
# ================================
async def laporan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ['📅 Hari Ini', '📆 Bulan Ini'],
        ['📊 Semua Data', '🔙 Kembali']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text('Pilih laporan:', reply_markup=reply_markup)

async def laporan_hari_ini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hari_ini = datetime.now(WIB).strftime('%Y-%m-%d')
        sheet = get_sheet()
        penjualan = sheet.worksheet('Penjualan').get_all_records()

        total = 0
        pesan = f'📅 *Laporan Hari Ini ({hari_ini})*\n\n'
        ada_data = False

        for row in penjualan:
            if str(row['Tanggal']).startswith(hari_ini):
                ada_data = True
                pesan += f"🍿 {row['Nama_Snack']} x{row['Jumlah_Terjual']} = Rp{int(row['Total']):,}\n"
                total += int(row['Total'])

        if not ada_data:
            pesan += 'Belum ada penjualan hari ini.'
        else:
            pesan += f'\n💰 *Total: Rp{total:,}*'

        await update.message.reply_text(pesan, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')

async def laporan_bulan_ini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bulan_ini = datetime.now(WIB).strftime('%Y-%m')
        sheet = get_sheet()
        penjualan = sheet.worksheet('Penjualan').get_all_records()

        total = 0
        rekap = {}

        for row in penjualan:
            if str(row['Tanggal']).startswith(bulan_ini):
                nama = row['Nama_Snack']
                rekap[nama] = rekap.get(nama, 0) + int(row['Total'])
                total += int(row['Total'])

        pesan = f'📆 *Laporan Bulan Ini*\n\n'
        if not rekap:
            pesan += 'Belum ada data bulan ini.'
        else:
            for nama, tot in rekap.items():
                pesan += f'🍿 {nama}: Rp{tot:,}\n'
            pesan += f'\n💰 *Total: Rp{total:,}*'

        await update.message.reply_text(pesan, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')

async def laporan_semua(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        penjualan = sheet.worksheet('Penjualan').get_all_records()
        kulakan = sheet.worksheet('Kulakan').get_all_records()

        total_jual = sum(int(r['Total']) for r in penjualan)
        total_beli = sum(int(r['Total_Bayar']) for r in kulakan)
        keuntungan = total_jual - total_beli

        pesan = (
            f'📊 *Laporan Keseluruhan*\n\n'
            f'💰 Total Penjualan: Rp{total_jual:,}\n'
            f'🛒 Total Kulakan: Rp{total_beli:,}\n'
            f'📈 Keuntungan: Rp{keuntungan:,}'
        )
        await update.message.reply_text(pesan, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')

# ================================
# MAIN
# ================================
def main():
    token = os.environ.get('BOT_TOKEN')
    app = Application.builder().token(token).build()

    kulakan_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('📦 Catat Kulakan'), kulakan_start)],
        states={
            KULAKAN_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_nama)],
            KULAKAN_TEMPAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_tempat)],
            KULAKAN_HARGA: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_harga)],
            KULAKAN_JUMLAH: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_jumlah)],
        },
        fallbacks=[CommandHandler('start', start)]
    )

    kantin_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('🏪 Stok ke Kantin'), kantin_start)],
        states={
            KANTIN_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, kantin_nama)],
            KANTIN_JUMLAH: [MessageHandler(filters.TEXT & ~filters.COMMAND, kantin_jumlah)],
        },
        fallbacks=[CommandHandler('start', start)]
    )

    jual_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('💰 Catat Penjualan'), jual_start)],
        states={
            JUAL_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_nama)],
            JUAL_JUMLAH: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_jumlah)],
            JUAL_HARGA: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_harga)],
        },
        fallbacks=[CommandHandler('start', start)]
    )

    produk_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('➕ Tambah Produk'), tambah_produk_start)],
        states={
            PRODUK_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, produk_nama)],
            PRODUK_SATUAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, produk_satuan)],
        },
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(kulakan_handler)
    app.add_handler(kantin_handler)
    app.add_handler(jual_handler)
    app.add_handler(produk_handler)
    app.add_handler(MessageHandler(filters.Regex('📸 Foto Nota'), foto_nota_start))
    app.add_handler(MessageHandler(filters.PHOTO, proses_foto))
    app.add_handler(MessageHandler(filters.Regex('📋 Lihat Stok'), lihat_stok))
    app.add_handler(MessageHandler(filters.Regex('📊 Lihat Laporan'), laporan))
    app.add_handler(MessageHandler(filters.Regex('📅 Hari Ini'), laporan_hari_ini))
    app.add_handler(MessageHandler(filters.Regex('📆 Bulan Ini'), laporan_bulan_ini))
    app.add_handler(MessageHandler(filters.Regex('📊 Semua Data'), laporan_semua))
    app.add_handler(MessageHandler(filters.Regex('🔙 Kembali'), start))

    print('Bot berjalan...')
    app.run_polling()

if __name__ == '__main__':
    main()
