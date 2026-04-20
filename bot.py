import logging
import os
from datetime import datetime
import pytz
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from groq import Groq
import base64
import openpyxl
import io

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Timezone Indonesia
WIB = pytz.timezone('Asia/Jakarta')

# Normalisasi nama produk — supaya Chiki, chiki, CHIKI dianggap sama
def norm_nama(nama):
    return str(nama).strip().title()

# Setup Groq
groq_client = Groq(api_key=os.environ.get('GROQ_API_KEY'))

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

# States
(KULAKAN_NAMA, KULAKAN_TEMPAT, KULAKAN_HARGA, KULAKAN_JUMLAH,
 KANTIN_NAMA, KANTIN_JUMLAH,
 JUAL_NAMA, JUAL_JUMLAH,
 PRODUK_PILIH, PRODUK_NAMA, PRODUK_SATUAN, PRODUK_HARGA_JUAL,
 KULAKAN_PILIH, KANTIN_PILIH, JUAL_PILIH,
 UBAH_HARGA_NAMA, UBAH_HARGA_BARU,
 SISA_PILIH, SISA_INPUT) = range(19)

# ================================
# MENU UTAMA
# ================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ['📦 Catat Kulakan', '🏪 Stok ke Kantin'],
        ['💰 Catat Penjualan', '📊 Lihat Laporan'],
        ['📋 Lihat Stok', '➕ Tambah Produk'],
        ['💲 Ubah Harga Jual', '🧮 Sisa Stok Kantin'],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        '🐸 *Selamat datang di Bot Kasir Kantin!*\n\nPilih menu di bawah:',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# ================================
# PILIH CARA INPUT
# ================================
def keyboard_cara_input():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Manual", callback_data='manual'),
            InlineKeyboardButton("📸 Foto Nota", callback_data='foto'),
            InlineKeyboardButton("📊 Excel", callback_data='excel'),
        ],
        [
            InlineKeyboardButton("❌ Batal", callback_data='batal'),
        ]
    ])

# ================================
# BATAL
# ================================
async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        ['📦 Catat Kulakan', '🏪 Stok ke Kantin'],
        ['💰 Catat Penjualan', '📊 Lihat Laporan'],
        ['📋 Lihat Stok', '➕ Tambah Produk'],
    ]
    await update.message.reply_text(
        '❌ *Dibatalkan.*\n\nKembali ke menu utama:',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

# ================================
# KULAKAN
# ================================
async def kulakan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['menu'] = 'kulakan'
    await update.message.reply_text(
        '📦 *Catat Kulakan*\n\nPilih cara input:',
        reply_markup=keyboard_cara_input(),
        parse_mode='Markdown'
    )
    return KULAKAN_PILIH

async def kulakan_pilih(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pilihan = query.data

    if pilihan == 'batal':
        await query.edit_message_text('❌ Dibatalkan. Kembali ke menu utama.')
        return ConversationHandler.END
    elif pilihan == 'manual':
        await query.edit_message_text('✏️ Input Manual\n\nNama snack yang dibeli?\n\n_Ketik /batal untuk membatalkan_', parse_mode='Markdown')
        return KULAKAN_NAMA
    elif pilihan == 'foto':
        await query.edit_message_text('📸 Kirim foto nota kulakan kamu sekarang!\n\n_Ketik /batal untuk membatalkan_', parse_mode='Markdown')
        context.user_data['waiting_foto'] = 'kulakan'
        return ConversationHandler.END
    elif pilihan == 'excel':
        await query.edit_message_text(
            '📊 *Upload Excel Kulakan*\n\n'
            'Format kolom Excel:\n'
            '`Nama_Snack | Tempat_Beli | Harga_Beli | Jumlah`\n\n'
            'Kirim file Excel sekarang!\n\n_Ketik /batal untuk membatalkan_',
            parse_mode='Markdown'
        )
        context.user_data['waiting_excel'] = 'kulakan'
        return ConversationHandler.END

async def kulakan_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['kulakan_nama'] = norm_nama(update.message.text.strip())
    await update.message.reply_text('Beli di mana? (contoh: Alfamart, Toko Pak Budi)')
    return KULAKAN_TEMPAT

async def kulakan_tempat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['kulakan_tempat'] = update.message.text.strip()
    await update.message.reply_text('Harga beli per pcs? (angka saja, contoh: 2000)')
    return KULAKAN_HARGA

async def kulakan_harga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    if teks.startswith('/'):
        return KULAKAN_HARGA
    try:
        context.user_data['kulakan_harga'] = int(teks)
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

        # Simpan dulu ke sheet Kulakan
        sheet = get_sheet()
        ws = sheet.worksheet('Kulakan')
        ws.append_row([tanggal, nama, tempat, harga, jumlah, total])

        await update.message.reply_text(
            f'✅ *Kulakan tercatat!*\n\n'
            f'🛍 Snack: {nama}\n'
            f'🏪 Tempat: {tempat}\n'
            f'💵 Harga beli: Rp{harga:,}\n'
            f'📦 Jumlah: {jumlah}\n'
            f'💰 Total: Rp{total:,}',
            parse_mode='Markdown'
        )

        # Cek apakah produk sudah ada
        daftar = get_daftar_produk()
        if norm_nama(nama) not in daftar:
            context.user_data['produk_baru_manual'] = nama
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ya, Tambahkan", callback_data='manual_produk_ya'),
                    InlineKeyboardButton("❌ Lewati", callback_data='manual_produk_skip'),
                ]
            ])
            await update.message.reply_text(
                f'🆕 *Produk baru ditemukan!*\n\n'
                f'*"{nama}"* belum ada di daftar produk.\n\n'
                f'Tambahkan ke daftar produk?',
                parse_mode='Markdown',
                reply_markup=keyboard
            )

    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
    return ConversationHandler.END

# ================================
# STOK KE KANTIN
# ================================
async def kantin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['menu'] = 'kantin'
    await update.message.reply_text(
        '🏪 *Stok ke Kantin*\n\nPilih cara input:',
        reply_markup=keyboard_cara_input(),
        parse_mode='Markdown'
    )
    return KANTIN_PILIH

async def kantin_pilih(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pilihan = query.data

    if pilihan == 'batal':
        await query.edit_message_text('❌ Dibatalkan. Kembali ke menu utama.')
        return ConversationHandler.END
    elif pilihan == 'manual':
        await query.edit_message_text('✏️ Input Manual\n\nNama snack yang dibawa ke kantin?\n\n_Ketik /batal untuk membatalkan_', parse_mode='Markdown')
        return KANTIN_NAMA
    elif pilihan == 'foto':
        await query.edit_message_text('📸 Kirim foto daftar stok kantin kamu sekarang!\n\n_Ketik /batal untuk membatalkan_', parse_mode='Markdown')
        context.user_data['waiting_foto'] = 'kantin'
        return ConversationHandler.END
    elif pilihan == 'excel':
        await query.edit_message_text(
            '📊 *Upload Excel Kantin*\n\n'
            'Format kolom Excel:\n'
            '`Nama_Snack | Jumlah`\n\n'
            'Kirim file Excel sekarang!\n\n_Ketik /batal untuk membatalkan_',
            parse_mode='Markdown'
        )
        context.user_data['waiting_excel'] = 'kantin'
        return ConversationHandler.END

async def kantin_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['kantin_nama'] = norm_nama(update.message.text.strip())
    await update.message.reply_text('Berapa jumlah yang dibawa ke kantin?')
    return KANTIN_JUMLAH

async def kantin_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    if teks.startswith('/'):
        return KANTIN_JUMLAH
    try:
        jumlah = int(teks)
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
    context.user_data['menu'] = 'jual'
    await update.message.reply_text(
        '💰 *Catat Penjualan*\n\nPilih cara input:',
        reply_markup=keyboard_cara_input(),
        parse_mode='Markdown'
    )
    return JUAL_PILIH

async def jual_pilih(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pilihan = query.data

    if pilihan == 'batal':
        await query.edit_message_text('❌ Dibatalkan. Kembali ke menu utama.')
        return ConversationHandler.END
    elif pilihan == 'manual':
        await query.edit_message_text('✏️ Input Manual\n\nNama snack yang terjual?\n\n_Ketik /batal untuk membatalkan_', parse_mode='Markdown')
        return JUAL_NAMA
    elif pilihan == 'foto':
        await query.edit_message_text('📸 Kirim foto daftar penjualan kamu sekarang!\n\n_Ketik /batal untuk membatalkan_', parse_mode='Markdown')
        context.user_data['waiting_foto'] = 'jual'
        return ConversationHandler.END
    elif pilihan == 'excel':
        await query.edit_message_text(
            '📊 *Upload Excel Penjualan*\n\n'
            'Format kolom Excel:\n'
            '`Nama_Snack | Jumlah_Terjual | Harga_Jual`\n\n'
            'Kirim file Excel sekarang!\n\n_Ketik /batal untuk membatalkan_',
            parse_mode='Markdown'
        )
        context.user_data['waiting_excel'] = 'jual'
        return ConversationHandler.END

async def jual_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['jual_nama'] = norm_nama(update.message.text.strip())
    await update.message.reply_text('Berapa yang terjual?')
    return JUAL_JUMLAH

async def jual_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    if teks.startswith('/'):
        return JUAL_JUMLAH
    try:
        jumlah = int(teks)
        nama = context.user_data['jual_nama']
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')

        # Ambil harga jual dari sheet Product
        sheet = get_sheet()
        ws_produk = sheet.worksheet('Product')
        data_produk = ws_produk.get_all_records()
        harga = 0
        for p in data_produk:
            if norm_nama(p['Nama_Snack']) == nama:
                harga = int(p.get('Harga_Jual', 0))
                break

        if harga == 0:
            await update.message.reply_text(
                f'⚠️ Harga jual *{nama}* belum diset!\n\n'
                f'Silakan set dulu via menu *💲 Ubah Harga Jual*',
                parse_mode='Markdown'
            )
            return ConversationHandler.END

        total = harga * jumlah
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
# PROSES FOTO (semua menu)
# ================================
async def proses_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = context.user_data.get('waiting_foto')
    if not menu:
        return

    await update.message.reply_text('⏳ Sedang membaca foto, tunggu sebentar...')

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_base64 = base64.b64encode(file_bytes).decode('utf-8')

        if menu == 'kulakan':
            prompt = """Baca nota belanja ini. Ekstrak semua item dalam format JSON:
{
    "tempat_beli": "nama toko atau tidak diketahui",
    "items": [{"nama": "nama produk", "jumlah": angka, "harga_satuan": angka, "total": angka}],
    "total_semua": angka
}
Kembalikan JSON saja tanpa penjelasan."""

        elif menu == 'kantin':
            prompt = """Baca daftar stok ini. Ekstrak semua item dalam format JSON:
{
    "items": [{"nama": "nama produk", "jumlah": angka}]
}
Kembalikan JSON saja tanpa penjelasan."""

        elif menu == 'jual':
            prompt = """Baca daftar penjualan ini. Ekstrak semua item dalam format JSON:
{
    "items": [{"nama": "nama produk", "jumlah": angka, "harga_jual": angka, "total": angka}]
}
Kembalikan JSON saja tanpa penjelasan."""

        elif menu == 'produk':
            prompt = """Baca daftar produk/snack ini. Ekstrak semua item dalam format JSON:
{
    "items": [{"nama": "nama produk", "satuan": "pcs/bungkus/dll", "harga_jual": angka}]
}
Jika satuan tidak ada, isi dengan "pcs".
Jika harga tidak ada, isi dengan 0.
Kembalikan JSON saja tanpa penjelasan."""

        elif menu == 'sisa':
            prompt = """Baca daftar sisa stok ini. Ekstrak semua item dalam format JSON:
{
    "items": [{"nama": "nama produk", "sisa": angka}]
}
Kembalikan JSON saja tanpa penjelasan."""

        response = groq_client.chat.completions.create(
            model='meta-llama/llama-4-scout-17b-16e-instruct',
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'text',
                            'text': prompt
                        },
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/jpeg;base64,{image_base64}'
                            }
                        }
                    ]
                }
            ],
            max_tokens=1024,
        )

        hasil_text = response.choices[0].message.content.strip()
        if '```json' in hasil_text:
            hasil_text = hasil_text.split('```json')[1].split('```')[0].strip()
        elif '```' in hasil_text:
            hasil_text = hasil_text.split('```')[1].split('```')[0].strip()

        hasil = json.loads(hasil_text)

        # Simpan hasil sementara untuk konfirmasi
        context.user_data['hasil_foto'] = hasil
        context.user_data['menu_foto'] = menu

        # Tampilkan hasil dulu, belum disimpan
        pesan = '📋 *Hasil Baca Foto:*\n\n'

        if menu == 'kulakan':
            tempat = hasil.get('tempat_beli', 'Tidak diketahui')
            pesan += f'🏪 Tempat: {tempat}\n\n📦 Item:\n'
            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                jumlah = item.get('jumlah', 0)
                harga = item.get('harga_satuan', 0)
                total = item.get('total', harga * jumlah)
                pesan += f'• {nama} x{jumlah} @ Rp{harga:,} = Rp{total:,}\n'
            pesan += f'\n💰 Total: Rp{hasil.get("total_semua", 0):,}'

        elif menu == 'kantin':
            pesan += '📦 Item masuk kantin:\n'
            for item in hasil.get('items', []):
                pesan += f'• {item.get("nama")} x{item.get("jumlah")}\n'

        elif menu == 'jual':
            pesan += '💰 Item terjual:\n'
            total_semua = 0
            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                jumlah = item.get('jumlah', 0)
                harga = item.get('harga_jual', 0)
                total = item.get('total', harga * jumlah)
                total_semua += total
                pesan += f'• {nama} x{jumlah} = Rp{total:,}\n'
            pesan += f'\n💰 Total: Rp{total_semua:,}'

        elif menu == 'produk':
            pesan += '🍿 Daftar produk:\n'
            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                satuan = item.get('satuan', 'pcs')
                harga = item.get('harga_jual', 0)
                pesan += f'• {nama} ({satuan}) — Rp{harga:,}\n'

        elif menu == 'sisa':
            # Ambil stok kantin SAAT INI (sudah dikurangi penjualan sebelumnya)
            sheet = get_sheet()
            stok_sekarang = get_stok_kantin_sekarang()

            pesan += '🧮 *Rekap Sisa Stok Kantin:*\n\n'
            terjual_list = []
            total_pendapatan = 0

            # Ambil harga dari Product
            ws_produk = sheet.worksheet('Product')
            data_produk = ws_produk.get_all_records()
            harga_dict = {}
            for p in data_produk:
                harga_dict[norm_nama(p['Nama_Snack'])] = int(p.get('Harga_Jual', 0))

            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                sisa_fisik = int(item.get('sisa', 0))
                stok_kini = stok_sekarang.get(nama, 0)
                terjual = max(0, stok_kini - sisa_fisik)
                harga = harga_dict.get(nama, 0)
                total = terjual * harga
                total_pendapatan += total
                terjual_list.append({
                    'nama': nama, 'stok_kini': stok_kini,
                    'sisa': sisa_fisik, 'terjual': terjual,
                    'harga': harga, 'total': total
                })
                pesan += (
                    f'🍿 *{nama}*\n'
                    f'   Stok kantin: {stok_kini} pcs\n'
                    f'   Sisa fisik : {sisa_fisik} pcs\n'
                    f'   Terjual    : {terjual} pcs\n'
                    f'   Total      : Rp{total:,}\n\n'
                )

            pesan += f'💰 *Total Pendapatan: Rp{total_pendapatan:,}*'
            # Simpan data terjual sementara
            context.user_data['sisa_terjual'] = terjual_list

        pesan += '\n\n_Data sudah benar?_'

        # Tombol konfirmasi
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, Simpan!", callback_data='konfirmasi_simpan'),
                InlineKeyboardButton("❌ Batal", callback_data='konfirmasi_batal'),
            ]
        ])

        await update.message.reply_text(pesan, parse_mode='Markdown', reply_markup=keyboard)

    except Exception as e:
        logger.error(f'Error proses foto: {e}')
        await update.message.reply_text('❌ Gagal membaca foto. Coba lagi dengan foto yang lebih jelas!')
        context.user_data['waiting_foto'] = None

# ================================
# CEK & TAMBAH PRODUK OTOMATIS
# ================================
def get_stok_kantin_sekarang():
    """Hitung stok kantin saat ini = total masuk - total terjual"""
    try:
        sheet = get_sheet()
        kantin_records = sheet.worksheet('Kantin').get_all_records()
        penjualan_records = sheet.worksheet('Penjualan').get_all_records()

        stok = {}
        for row in kantin_records:
            nama = norm_nama(row['Nama_Snack'])
            stok[nama] = stok.get(nama, 0) + int(row['Jumlah_Masuk'])
        for row in penjualan_records:
            nama = norm_nama(row['Nama_Snack'])
            stok[nama] = stok.get(nama, 0) - int(row['Jumlah_Terjual'])

        return stok
    except Exception as e:
        logger.error(f'Error get stok kantin: {e}')
        return {}
        
def get_daftar_produk():
    """Ambil semua nama produk dari sheet Produk"""
    try:
        sheet = get_sheet()
        ws = sheet.worksheet('Product')
        data = ws.get_all_records()
        return [norm_nama(row['Nama_Snack']) for row in data]
    except:
        return []

def tambah_produk_otomatis(nama, satuan='pcs', harga_jual=0):
    """Tambah produk baru ke sheet Product"""
    try:
        sheet = get_sheet()
        ws = sheet.worksheet('Product')
        data = ws.get_all_values()
        id_baru = len(data)
        ws.append_row([id_baru, nama, satuan, harga_jual])
        return True
    except:
        return False

def cek_produk_baru(items, field_nama='nama'):
    """Cek item mana saja yang belum ada di sheet Produk"""
    daftar = get_daftar_produk()
    produk_baru = []
    for item in items:
        nama = norm_nama(item.get(field_nama, ''))
        if nama and nama not in daftar:
            produk_baru.append(item.get(field_nama))
    return produk_baru

async def konfirmasi_produk_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    nama = context.user_data.get('produk_baru_manual')

    if query.data == 'manual_produk_ya':
        berhasil = tambah_produk_otomatis(nama)
        if berhasil:
            await query.edit_message_text(
                f'✅ *{nama}* berhasil ditambahkan ke daftar produk!',
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(f'❌ Gagal tambah produk.')
    else:
        await query.edit_message_text(f'⏭ *{nama}* tidak ditambahkan ke daftar produk.', parse_mode='Markdown')

    context.user_data['produk_baru_manual'] = None


async def konfirmasi_produk_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    produk_list = context.user_data.get('produk_baru_excel_list', [])
    index = context.user_data.get('produk_baru_excel_index', 0)
    nama = produk_list[index]

    if query.data == 'excel_produk_ya':
        tambah_produk_otomatis(nama)
        await query.answer(f'✅ {nama} ditambahkan!')
    else:
        await query.answer(f'⏭ {nama} dilewati.')

    # Cek apakah masih ada produk baru
    index += 1
    context.user_data['produk_baru_excel_index'] = index

    if index < len(produk_list):
        nama_berikut = produk_list[index]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, Tambahkan", callback_data='excel_produk_ya'),
                InlineKeyboardButton("❌ Lewati", callback_data='excel_produk_skip'),
            ]
        ])
        await query.edit_message_text(
            f'🆕 *Produk baru ditemukan!*\n\n'
            f'*"{nama_berikut}"* belum ada di daftar produk.\n\n'
            f'Tambahkan ke daftar produk?',
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    else:
        await query.edit_message_text(
            '✅ Semua produk baru sudah diproses!',
            parse_mode='Markdown'
        )
        context.user_data['produk_baru_excel_list'] = None
        context.user_data['produk_baru_excel_index'] = 0


async def konfirmasi_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'konfirmasi_batal':
        await query.edit_message_text('❌ Data dibatalkan, tidak ada yang tersimpan.')
        context.user_data['waiting_foto'] = None
        return

    if query.data == 'konfirmasi_simpan':
        hasil = context.user_data.get('hasil_foto')
        menu = context.user_data.get('menu_foto')

        # Cek produk baru hanya untuk kulakan dan penjualan
        if menu in ['kulakan', 'jual', 'kantin']:
            items = hasil.get('items', [])
            produk_baru = cek_produk_baru(items)

            if produk_baru:
                # Ada produk baru — simpan dulu di user_data, tanya konfirmasi
                context.user_data['produk_baru_list'] = produk_baru
                context.user_data['produk_baru_index'] = 0
                context.user_data['siap_simpan'] = True

                nama = produk_baru[0]
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Ya, Tambahkan", callback_data='produk_ya'),
                        InlineKeyboardButton("❌ Lewati", callback_data='produk_skip'),
                    ]
                ])
                await query.edit_message_text(
                    f'🆕 *Produk baru ditemukan!*\n\n'
                    f'*"{nama}"* belum ada di daftar produk.\n\n'
                    f'Tambahkan ke daftar produk?',
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                return

        # Tidak ada produk baru — langsung simpan
        await simpan_data_foto(query, context)

    if query.data in ['produk_ya', 'produk_skip']:
        produk_list = context.user_data.get('produk_baru_list', [])
        index = context.user_data.get('produk_baru_index', 0)
        nama = produk_list[index]

        if query.data == 'produk_ya':
            tambah_produk_otomatis(nama)
            await query.answer(f'✅ {nama} ditambahkan ke produk!')
        else:
            await query.answer(f'⏭ {nama} dilewati.')

        # Cek apakah masih ada produk baru lainnya
        index += 1
        context.user_data['produk_baru_index'] = index

        if index < len(produk_list):
            nama_berikut = produk_list[index]
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ya, Tambahkan", callback_data='produk_ya'),
                    InlineKeyboardButton("❌ Lewati", callback_data='produk_skip'),
                ]
            ])
            await query.edit_message_text(
                f'🆕 *Produk baru ditemukan!*\n\n'
                f'*"{nama_berikut}"* belum ada di daftar produk.\n\n'
                f'Tambahkan ke daftar produk?',
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return

        # Semua produk baru sudah diproses — simpan data
        await simpan_data_foto(query, context)


async def simpan_data_foto(query, context):
    """Simpan data foto ke Google Sheets setelah konfirmasi"""
    try:
        hasil = context.user_data.get('hasil_foto')
        menu = context.user_data.get('menu_foto')
        sheet = get_sheet()
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')
        count = 0

        if menu == 'kulakan':
            ws = sheet.worksheet('Kulakan')
            tempat = hasil.get('tempat_beli', 'Tidak diketahui')
            data_batch = []
            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                jumlah = item.get('jumlah', 0)
                harga = item.get('harga_satuan', 0)
                total = item.get('total', harga * jumlah)
                data_batch.append([tanggal, nama, tempat, harga, jumlah, total])
                count += 1
            if data_batch:
                ws.append_rows(data_batch)

        elif menu == 'kantin':
            ws = sheet.worksheet('Kantin')
            data_batch = []
            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                jumlah = item.get('jumlah', 0)
                data_batch.append([tanggal, nama, jumlah])
                count += 1
            if data_batch:
                ws.append_rows(data_batch)

        elif menu == 'jual':
            ws = sheet.worksheet('Penjualan')
            data_batch = []
            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                jumlah = item.get('jumlah', 0)
                harga = item.get('harga_jual', 0)
                total = item.get('total', harga * jumlah)
                data_batch.append([tanggal, nama, jumlah, harga, total])
                count += 1
            if data_batch:
                ws.append_rows(data_batch)

        elif menu == 'produk':
            ws = sheet.worksheet('Product')
            # Pakai get_all_values supaya aman walau sheet kosong
            semua_data = ws.get_all_values()
            # Ambil nama produk yang sudah ada (skip baris header)
            daftar_ada = [norm_nama(row[1]) for row in semua_data[1:] if len(row) > 1 and row[1]]
            data_batch = []
            skipped = 0
            for item in hasil.get('items', []):
                nama = norm_nama(item.get('nama', '-'))
                satuan = item.get('satuan', 'pcs')
                harga_jual = int(item.get('harga_jual', 0))
                if nama in daftar_ada:
                    skipped += 1
                    continue
                id_baru = len(semua_data) + len(data_batch)
                data_batch.append([id_baru, nama, satuan, harga_jual])
                count += 1
            if data_batch:
                ws.append_rows(data_batch)
            # Tampilkan pesan sesuai hasil
            if count == 0 and skipped > 0:
                await query.edit_message_text(
                    f'ℹ️ Semua produk sudah ada di daftar, tidak ada yang ditambahkan.',
                    parse_mode='Markdown'
                )
            elif skipped > 0:
                await query.edit_message_text(
                    f'✅ *Produk berhasil disimpan!*\n\n'
                    f'➕ {count} produk baru ditambahkan.\n'
                    f'⏭ {skipped} produk dilewati (sudah ada). 🎉',
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f'✅ *{count} produk berhasil ditambahkan!* 🎉',
                    parse_mode='Markdown'
                )
            # Cleanup dan return lebih awal
            context.user_data['waiting_foto'] = None
            context.user_data['hasil_foto'] = None
            context.user_data['menu_foto'] = None
            context.user_data['produk_baru_list'] = None
            context.user_data['produk_baru_index'] = 0
            context.user_data['siap_simpan'] = False
            return

        elif menu == 'sisa':
            # Simpan hasil hitung terjual ke sheet Penjualan
            terjual_list = context.user_data.get('sisa_terjual', [])
            ws = sheet.worksheet('Penjualan')
            data_batch = []
            for item in terjual_list:
                if item['terjual'] > 0:
                    data_batch.append([
                        tanggal,
                        item['nama'],
                        item['terjual'],
                        item['harga'],
                        item['total']
                    ])
                    count += 1
            if data_batch:
                ws.append_rows(data_batch)
            context.user_data['sisa_terjual'] = None
            await query.edit_message_text(
                f'✅ *Penjualan berhasil dicatat!*\n\n'
                f'{count} produk tersimpan ke sheet Penjualan. 🎉',
                parse_mode='Markdown'
            )
            context.user_data['waiting_foto'] = None
            context.user_data['hasil_foto'] = None
            context.user_data['menu_foto'] = None
            context.user_data['produk_baru_list'] = None
            context.user_data['produk_baru_index'] = 0
            context.user_data['siap_simpan'] = False
            return

        await query.edit_message_text(
            f'✅ *Berhasil disimpan!*\n\n'
            f'{count} item tersimpan ke Google Sheets. 🎉',
            parse_mode='Markdown'
        )

    except Exception as e:
        await query.edit_message_text(f'❌ Gagal simpan: {e}')

    context.user_data['waiting_foto'] = None
    context.user_data['hasil_foto'] = None
    context.user_data['menu_foto'] = None
    context.user_data['produk_baru_list'] = None
    context.user_data['produk_baru_index'] = 0
    context.user_data['siap_simpan'] = False

# ================================
# PROSES EXCEL (semua menu)
# ================================
async def proses_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = context.user_data.get('waiting_excel')
    if not menu:
        return

    await update.message.reply_text('⏳ Sedang membaca file Excel...')

    try:
        file = await context.bot.get_file(update.document.file_id)
        file_bytes = await file.download_as_bytearray()

        wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
        ws_excel = wb.active
        rows = list(ws_excel.iter_rows(min_row=2, values_only=True))

        sheet = get_sheet()
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')
        pesan = '✅ *Excel berhasil dibaca!*\n\n'
        count = 0

        if menu == 'kulakan':
            ws = sheet.worksheet('Kulakan')
            pesan += '📦 Item kulakan:\n'
            data_batch = []
            for row in rows:
                if not row[0]:
                    continue
                nama = norm_nama(str(row[0]))
                tempat = str(row[1]) if row[1] else 'Tidak diketahui'
                harga = int(row[2]) if row[2] else 0
                jumlah = int(row[3]) if row[3] else 0
                total = harga * jumlah
                data_batch.append([tanggal, nama, tempat, harga, jumlah, total])
                pesan += f'• {nama} x{jumlah} @ Rp{harga:,} = Rp{total:,}\n'
                count += 1
            if data_batch:
                ws.append_rows(data_batch)

        elif menu == 'kantin':
            ws = sheet.worksheet('Kantin')
            pesan += '🏪 Item masuk kantin:\n'
            data_batch = []
            for row in rows:
                if not row[0]:
                    continue
                nama = norm_nama(str(row[0]))
                jumlah = int(row[1]) if row[1] else 0
                data_batch.append([tanggal, nama, jumlah])
                pesan += f'• {nama} x{jumlah}\n'
                count += 1
            if data_batch:
                ws.append_rows(data_batch)

        elif menu == 'jual':
            ws = sheet.worksheet('Penjualan')
            pesan += '💰 Item terjual:\n'
            total_semua = 0
            data_batch = []
            for row in rows:
                if not row[0]:
                    continue
                nama = norm_nama(str(row[0]))
                jumlah = int(row[1]) if row[1] else 0
                harga = int(row[2]) if row[2] else 0
                total = harga * jumlah
                total_semua += total
                data_batch.append([tanggal, nama, jumlah, harga, total])
                pesan += f'• {nama} x{jumlah} = Rp{total:,}\n'
                count += 1
            if data_batch:
                ws.append_rows(data_batch)
            pesan += f'\n💰 Total: Rp{total_semua:,}'
             
        # Cek produk baru dari excel
        daftar = get_daftar_produk()
        produk_baru_excel = []
        for row in rows:
            if not row[0]:
                continue
            nama = norm_nama(str(row[0]))
            if nama and nama not in daftar:
                produk_baru_excel.append(str(row[0]))

        if produk_baru_excel:
            context.user_data['produk_baru_excel_list'] = produk_baru_excel
            context.user_data['produk_baru_excel_index'] = 0

            nama_pertama = produk_baru_excel[0]
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ya, Tambahkan", callback_data='excel_produk_ya'),
                    InlineKeyboardButton("❌ Lewati", callback_data='excel_produk_skip'),
                ]
            ])
            await update.message.reply_text(
                f'🆕 *Produk baru ditemukan!*\n\n'
                f'*"{nama_pertama}"* belum ada di daftar produk.\n\n'
                f'Tambahkan ke daftar produk?',
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        pesan += f'\n\n✅ {count} item berhasil disimpan!'
        await update.message.reply_text(pesan, parse_mode='Markdown')

    except Exception as e:
        logger.error(f'Error proses excel: {e}')
        await update.message.reply_text('❌ Gagal baca Excel. Pastikan format kolom sudah benar ya!')

    context.user_data['waiting_excel'] = None

# ================================
# TAMBAH PRODUK
# ================================
async def tambah_produk_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Manual", callback_data='produk_input_manual'),
            InlineKeyboardButton("📸 Foto", callback_data='produk_input_foto'),
        ],
        [InlineKeyboardButton("❌ Batal", callback_data='produk_input_batal')]
    ])
    await update.message.reply_text(
        '➕ *Tambah Produk Baru*\n\nPilih cara input:',
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    return PRODUK_PILIH

async def produk_pilih(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pilihan = query.data

    if pilihan == 'produk_input_batal':
        await query.edit_message_text('❌ Dibatalkan.')
        return ConversationHandler.END
    elif pilihan == 'produk_input_manual':
        await query.edit_message_text(
            '✏️ *Input Manual*\n\nNama snack baru?\n\n_Ketik /batal untuk membatalkan_',
            parse_mode='Markdown'
        )
        return PRODUK_NAMA
    elif pilihan == 'produk_input_foto':
        await query.edit_message_text(
            '📸 *Input Foto*\n\n'
            'Kirim foto daftar produk kamu!\n\n'
            'Format yang bisa dibaca:\n'
            '• Daftar nama + harga\n'
            '• Struk/nota dengan nama produk\n'
            '• Tulisan tangan daftar snack\n\n'
            '_Ketik /batal untuk membatalkan_',
            parse_mode='Markdown'
        )
        context.user_data['waiting_foto'] = 'produk'
        return ConversationHandler.END

async def produk_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['produk_nama'] = norm_nama(update.message.text.strip())
    await update.message.reply_text('Satuannya apa? (contoh: pcs, bungkus)')
    return PRODUK_SATUAN

async def produk_satuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['produk_satuan'] = update.message.text.strip()
    await update.message.reply_text('Harga jual per pcs? (angka saja, contoh: 5000)')
    return PRODUK_HARGA_JUAL

async def produk_harga_jual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    if teks.startswith('/'):
        return PRODUK_HARGA_JUAL
    try:
        harga_jual = int(teks)
        nama = context.user_data['produk_nama']
        satuan = context.user_data['produk_satuan']
        try:
            sheet = get_sheet()
            ws = sheet.worksheet('Product')
            data = ws.get_all_values()
            ws.append_row([len(data), nama, satuan, harga_jual])
            await update.message.reply_text(
                f'✅ *Produk berhasil ditambahkan!*\n\n'
                f'🍿 Nama: {nama}\n'
                f'📦 Satuan: {satuan}\n'
                f'💵 Harga jual: Rp{harga_jual:,}',
                parse_mode='Markdown'
            )
        except Exception as e:
            await update.message.reply_text(f'❌ Gagal: {e}')
    except:
        await update.message.reply_text('❌ Masukkan angka saja ya!')
        return PRODUK_HARGA_JUAL
    return ConversationHandler.END

# ================================
# UBAH HARGA JUAL
# ================================
async def ubah_harga_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        ws = sheet.worksheet('Product')
        data = ws.get_all_records()

        if not data:
            await update.message.reply_text('⚠️ Belum ada produk. Tambah produk dulu via ➕ Tambah Produk.')
            return ConversationHandler.END

        pesan = '💲 *Ubah Harga Jual*\n\nDaftar produk saat ini:\n\n'
        for i, row in enumerate(data, 1):
            harga = row.get('Harga_Jual', 0)
            pesan += f'{i}. {row["Nama_Snack"]} — Rp{int(harga):,}\n'

        pesan += '\nKetik nama produk yang ingin diubah harganya:\n\n_Ketik /batal untuk membatalkan_'
        await update.message.reply_text(pesan, parse_mode='Markdown')
        return UBAH_HARGA_NAMA
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
        return ConversationHandler.END

async def ubah_harga_nama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nama = norm_nama(update.message.text.strip())
    try:
        sheet = get_sheet()
        ws = sheet.worksheet('Product')
        data = ws.get_all_records()
        ditemukan = any(norm_nama(row['Nama_Snack']) == nama for row in data)

        if not ditemukan:
            await update.message.reply_text(
                f'❌ Produk *{nama}* tidak ditemukan.\nCoba ketik nama yang sesuai daftar.',
                parse_mode='Markdown'
            )
            return UBAH_HARGA_NAMA

        context.user_data['ubah_harga_nama'] = nama
        await update.message.reply_text(
            f'Masukkan harga jual baru untuk *{nama}*:\n(angka saja, contoh: 5000)',
            parse_mode='Markdown'
        )
        return UBAH_HARGA_BARU
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
        return ConversationHandler.END

async def ubah_harga_baru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    if teks.startswith('/'):
        return UBAH_HARGA_BARU
    try:
        harga_baru = int(teks)
        nama = context.user_data['ubah_harga_nama']

        sheet = get_sheet()
        ws = sheet.worksheet('Product')
        data = ws.get_all_records()

        # Cari baris produk dan update harganya
        for i, row in enumerate(data, 2):  # mulai dari baris 2 (skip header)
            if norm_nama(row['Nama_Snack']) == nama:
                # Kolom Harga_Jual = kolom D = kolom 4
                ws.update_cell(i, 4, harga_baru)
                await update.message.reply_text(
                    f'✅ *Harga berhasil diubah!*\n\n'
                    f'🍿 Produk: {nama}\n'
                    f'💵 Harga baru: Rp{harga_baru:,}',
                    parse_mode='Markdown'
                )
                return ConversationHandler.END

        await update.message.reply_text('❌ Produk tidak ditemukan.')
    except:
        await update.message.reply_text('❌ Masukkan angka saja ya!')
        return UBAH_HARGA_BARU
    return ConversationHandler.END

# ================================
# LIHAT STOK
# ================================
async def lihat_stok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        kulakan = sheet.worksheet('Kulakan').get_all_records()
        kantin_masuk = sheet.worksheet('Kantin').get_all_records()
        penjualan = sheet.worksheet('Penjualan').get_all_records()

        # Hitung stok APAR = total kulakan - total pindah ke kantin
        stok_apar = {}
        for row in kulakan:
            nama = norm_nama(row['Nama_Snack'])
            stok_apar[nama] = stok_apar.get(nama, 0) + int(row['Jumlah'])
        for row in kantin_masuk:
            nama = norm_nama(row['Nama_Snack'])
            stok_apar[nama] = stok_apar.get(nama, 0) - int(row['Jumlah_Masuk'])

        # Hitung stok KANTIN = total masuk kantin - total terjual
        stok_kantin = {}
        for row in kantin_masuk:
            nama = norm_nama(row['Nama_Snack'])
            stok_kantin[nama] = stok_kantin.get(nama, 0) + int(row['Jumlah_Masuk'])
        for row in penjualan:
            nama = norm_nama(row['Nama_Snack'])
            stok_kantin[nama] = stok_kantin.get(nama, 0) - int(row['Jumlah_Terjual'])

        # Gabungkan semua nama produk
        semua_produk = set(list(stok_apar.keys()) + list(stok_kantin.keys()))

        if not semua_produk:
            await update.message.reply_text('Belum ada data stok.')
            return

        pesan = '📋 *Stok Saat Ini:*\n\n'
        for nama in sorted(semua_produk):
            apar = stok_apar.get(nama, 0)
            kantin = stok_kantin.get(nama, 0)
            total = apar + kantin

            # Emoji peringatan kalau stok menipis
            if total <= 0:
                emoji = '🔴'
            elif total <= 5:
                emoji = '⚠️'
            else:
                emoji = '✅'

            pesan += f'{emoji} *{nama}*\n'
            pesan += f'   🏠 Apar  : {apar} pcs\n'
            pesan += f'   🏪 Kantin: {kantin} pcs\n\n'

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
    await update.message.reply_text(
        'Pilih laporan:',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

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
        pesan = '📆 *Laporan Bulan Ini*\n\n'
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
# SISA STOK KANTIN
# ================================
async def sisa_stok_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Manual", callback_data='sisa_manual'),
            InlineKeyboardButton("📸 Foto", callback_data='sisa_foto'),
        ],
        [InlineKeyboardButton("❌ Batal", callback_data='sisa_batal')]
    ])
    await update.message.reply_text(
        '🧮 *Sisa Stok Kantin*\n\n'
        'Input sisa stok yang ada di kantin sekarang.\n'
        'Bot akan otomatis hitung yang terjual!\n\n'
        'Pilih cara input:',
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    return SISA_PILIH

async def sisa_pilih(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pilihan = query.data

    if pilihan == 'sisa_batal':
        await query.edit_message_text('❌ Dibatalkan.')
        return ConversationHandler.END

    elif pilihan == 'sisa_foto':
        await query.edit_message_text(
            '📸 Kirim foto sisa stok kantin kamu!\n\n'
            'Bisa berupa:\n'
            '• Foto snack yang tersisa\n'
            '• Tulisan tangan daftar sisa\n\n'
            '_Ketik /batal untuk membatalkan_',
            parse_mode='Markdown'
        )
        context.user_data['waiting_foto'] = 'sisa'
        return ConversationHandler.END

    elif pilihan == 'sisa_manual':
        try:
            # Ambil stok kantin SAAT INI (sudah dikurangi penjualan sebelumnya)
            stok_sekarang = get_stok_kantin_sekarang()
            # Filter hanya yang stoknya > 0
            stok_ada = {k: v for k, v in stok_sekarang.items() if v > 0}

            if not stok_ada:
                await query.edit_message_text(
                    '⚠️ Tidak ada stok di kantin saat ini!\n\n'
                    'Input stok dulu via menu 🏪 Stok ke Kantin.'
                )
                return ConversationHandler.END

            context.user_data['sisa_stok_masuk'] = stok_ada
            context.user_data['sisa_produk_list'] = list(stok_ada.keys())
            context.user_data['sisa_produk_index'] = 0
            context.user_data['sisa_hasil'] = []

            nama_pertama = context.user_data['sisa_produk_list'][0]
            stok_kini = stok_ada[nama_pertama]
            await query.edit_message_text(
                f'✏️ *Input Sisa Stok Manual*\n\n'
                f'🍿 *{nama_pertama}*\n'
                f'Stok kantin saat ini: {stok_kini} pcs\n\n'
                f'Sekarang sisa berapa?\n\n'
                f'_Ketik /batal untuk membatalkan_',
                parse_mode='Markdown'
            )
            return SISA_INPUT

        except Exception as e:
            await query.edit_message_text(f'❌ Gagal: {e}')
            return ConversationHandler.END

async def sisa_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    if teks.startswith('/'):
        return SISA_INPUT
    try:
        sisa_fisik = int(teks)
        produk_list = context.user_data['sisa_produk_list']
        stok_sekarang = context.user_data['sisa_stok_masuk']
        index = context.user_data['sisa_produk_index']
        nama = produk_list[index]
        stok_kini = stok_sekarang[nama]
        terjual = max(0, stok_kini - sisa_fisik)

        context.user_data['sisa_hasil'].append({
            'nama': nama, 'stok_kini': stok_kini,
            'sisa': sisa_fisik, 'terjual': terjual
        })

        index += 1
        context.user_data['sisa_produk_index'] = index

        # Masih ada produk berikutnya?
        if index < len(produk_list):
            nama_berikut = produk_list[index]
            stok_berikut = stok_sekarang[nama_berikut]
            await update.message.reply_text(
                f'✅ *{nama}* — terjual {terjual} pcs\n\n'
                f'🍿 *{nama_berikut}*\n'
                f'Stok kantin saat ini: {stok_berikut} pcs\n\n'
                f'Sekarang sisa berapa?',
                parse_mode='Markdown'
            )
            return SISA_INPUT

        # Semua produk sudah diinput — tampilkan rekap
        hasil = context.user_data['sisa_hasil']
        sheet = get_sheet()
        ws_produk = sheet.worksheet('Product')
        data_produk = ws_produk.get_all_records()
        harga_dict = {norm_nama(p['Nama_Snack']): int(p.get('Harga_Jual', 0)) for p in data_produk}

        pesan = '🧮 *Rekap Sisa Stok Kantin:*\n\n'
        total_pendapatan = 0
        terjual_list = []

        for item in hasil:
            nama_item = item['nama']
            harga = harga_dict.get(nama_item, 0)
            total = item['terjual'] * harga
            total_pendapatan += total
            terjual_list.append({
                'nama': nama_item,
                'stok_kini': item['stok_kini'],
                'sisa': item['sisa'],
                'terjual': item['terjual'],
                'harga': harga,
                'total': total
            })
            pesan += (
                f'🍿 *{nama_item}*\n'
                f'   Stok kantin: {item["stok_kini"]} pcs\n'
                f'   Sisa fisik : {item["sisa"]} pcs\n'
                f'   Terjual    : {item["terjual"]} pcs\n'
                f'   Total      : Rp{total:,}\n\n'
            )

        pesan += f'💰 *Total Pendapatan: Rp{total_pendapatan:,}*\n\n_Data sudah benar?_'
        context.user_data['sisa_terjual'] = terjual_list

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, Simpan!", callback_data='sisa_simpan'),
                InlineKeyboardButton("❌ Batal", callback_data='sisa_batal_simpan'),
            ]
        ])
        await update.message.reply_text(pesan, parse_mode='Markdown', reply_markup=keyboard)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text('❌ Masukkan angka saja ya!')
        return SISA_INPUT
    except Exception as e:
        await update.message.reply_text(f'❌ Gagal: {e}')
        return ConversationHandler.END

async def konfirmasi_sisa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'sisa_batal_simpan':
        await query.edit_message_text('❌ Dibatalkan, tidak ada yang tersimpan.')
        context.user_data['sisa_terjual'] = None
        return

    try:
        terjual_list = context.user_data.get('sisa_terjual', [])
        sheet = get_sheet()
        tanggal = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')
        ws = sheet.worksheet('Penjualan')
        data_batch = []
        count = 0

        for item in terjual_list:
            if item['terjual'] > 0:
                data_batch.append([
                    tanggal,
                    item['nama'],
                    item['terjual'],
                    item['harga'],
                    item['total']
                ])
                count += 1

        if data_batch:
            ws.append_rows(data_batch)

        await query.edit_message_text(
            f'✅ *Penjualan berhasil dicatat!*\n\n'
            f'{count} produk tersimpan ke sheet Penjualan. 🎉',
            parse_mode='Markdown'
        )

    except Exception as e:
        await query.edit_message_text(f'❌ Gagal simpan: {e}')

    context.user_data['sisa_terjual'] = None
    context.user_data['sisa_hasil'] = None

# ================================
# MAIN
# ================================
def main():
    token = os.environ.get('BOT_TOKEN')
    app = Application.builder().token(token).build()

    kulakan_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('📦 Catat Kulakan'), kulakan_start)],
        states={
            KULAKAN_PILIH: [CallbackQueryHandler(kulakan_pilih)],
            KULAKAN_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_nama)],
            KULAKAN_TEMPAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_tempat)],
            KULAKAN_HARGA: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_harga)],
            KULAKAN_JUMLAH: [MessageHandler(filters.TEXT & ~filters.COMMAND, kulakan_jumlah)],
        },
        fallbacks=[CommandHandler('start', start), CommandHandler('batal', batal)]
    )

    kantin_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('🏪 Stok ke Kantin'), kantin_start)],
        states={
            KANTIN_PILIH: [CallbackQueryHandler(kantin_pilih)],
            KANTIN_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, kantin_nama)],
            KANTIN_JUMLAH: [MessageHandler(filters.TEXT & ~filters.COMMAND, kantin_jumlah)],
        },
        fallbacks=[CommandHandler('start', start), CommandHandler('batal', batal)]
    )

    jual_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('💰 Catat Penjualan'), jual_start)],
        states={
            JUAL_PILIH: [CallbackQueryHandler(jual_pilih)],
            JUAL_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_nama)],
            JUAL_JUMLAH: [MessageHandler(filters.TEXT & ~filters.COMMAND, jual_jumlah)],
        },
        fallbacks=[CommandHandler('start', start), CommandHandler('batal', batal)]
    )

    produk_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('➕ Tambah Produk'), tambah_produk_start)],
        states={
            PRODUK_PILIH: [CallbackQueryHandler(produk_pilih)],
            PRODUK_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, produk_nama)],
            PRODUK_SATUAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, produk_satuan)],
            PRODUK_HARGA_JUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, produk_harga_jual)],
        },
        fallbacks=[CommandHandler('start', start), CommandHandler('batal', batal)]
    )

    ubah_harga_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('💲 Ubah Harga Jual'), ubah_harga_start)],
        states={
            UBAH_HARGA_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ubah_harga_nama)],
            UBAH_HARGA_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, ubah_harga_baru)],
        },
        fallbacks=[CommandHandler('start', start), CommandHandler('batal', batal)]
    )

    sisa_stok_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('🧮 Sisa Stok Kantin'), sisa_stok_start)],
        states={
            SISA_PILIH: [CallbackQueryHandler(sisa_pilih)],
            SISA_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sisa_input)],
        },
        fallbacks=[CommandHandler('start', start), CommandHandler('batal', batal)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('batal', batal))
    app.add_handler(kulakan_handler)
    app.add_handler(kantin_handler)
    app.add_handler(jual_handler)
    app.add_handler(produk_handler)
    app.add_handler(ubah_harga_handler)
    app.add_handler(sisa_stok_handler)
    app.add_handler(MessageHandler(filters.PHOTO, proses_foto))
    app.add_handler(CallbackQueryHandler(konfirmasi_foto, pattern='^konfirmasi_|^produk_'))
    app.add_handler(CallbackQueryHandler(konfirmasi_produk_manual, pattern='^manual_produk_'))
    app.add_handler(CallbackQueryHandler(konfirmasi_produk_excel, pattern='^excel_produk_'))
    app.add_handler(CallbackQueryHandler(konfirmasi_sisa, pattern='^sisa_simpan|^sisa_batal_simpan'))
    app.add_handler(MessageHandler(filters.Document.ALL, proses_excel))
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
