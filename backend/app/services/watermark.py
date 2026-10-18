import os
import io
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF для работы с PDF

def add_watermark_to_image(image_path: str, assessor_id: str) -> io.BytesIO:
    """Накладывает полупрозрачный текст с ID асессора на изображение."""
    img = Image.open(image_path).convert("RGBA")
    
    # Создаем прозрачный слой для текста водяного знака
    txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_layer)
    
    # Текст водяного знака
    text = f"CONFIDENTIAL | Assessor: {assessor_id}"
    
    # Вычисляем размер шрифта в зависимости от размеров изображения
    font_size = max(20, int(img.width / 25))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except IOError:
        font = ImageFont.load_default()

    # Рисуем повторяющийся текст по диагонали или сеткой
    text_bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
    
    # Делаем полупрозрачный паттерн водяного знака
    for y in range(0, img.height, th * 4):
        for x in range(0, img.width, tw + 100):
            draw.text((x, y), text, fill=(150, 150, 150, 70), font=font) # Серый полупрозрачный цвет

    # Объединяем картинку со слоем водяного знака
    watermarked = Image.alpha_composite(img, txt_layer)
    
    # Конвертируем обратно в RGB / JPEG для отдачи клиенту
    output = io.BytesIO()
    watermarked.convert("RGB").save(output, format="JPEG", quality=85)
    output.seek(0)
    return output


def add_watermark_to_pdf(pdf_path: str, assessor_id: str) -> io.BytesIO:
    """Конвертирует страницы PDF в изображения, накладывает водяной знак и возвращает новый PDF."""
    doc = fitz.open(pdf_path)
    output_pdf = fitz.open()

    for page_num in range(len(doc)):
        page = doc[page_num]
        # Рендерим страницу PDF в картинку (высокое качество)
        pix = page.get_pixmap(dpi=150)
        img_data = pix.tobytes("jpeg")
        
        # Накладываем водяной знак через Pillow
        img = Image.open(io.BytesIO(img_data)).convert("RGBA")
        txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt_layer)
        
        text = f"CONFIDENTIAL | Assessor: {assessor_id}"
        font_size = max(25, int(img.width / 30))
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()

        text_bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]

        for y in range(0, img.height, th * 5):
            for x in range(0, img.width, tw + 150):
                draw.text((x, y), text, fill=(150, 150, 150, 80), font=font)

        watermarked = Image.alpha_composite(img, txt_layer)
        
        # Сохраняем страницу обратно в формат PDF
        img_byte_arr = io.BytesIO()
        watermarked.convert("RGB").save(img_byte_arr, format="JPEG", quality=85)
        img_byte_arr = img_byte_arr.getvalue()

        # Создаем новую страницу в выходном PDF
        new_page = output_pdf.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=img_byte_arr)

    pdf_bytes = output_pdf.write()
    output = io.BytesIO(pdf_bytes)
    output.seek(0)
    return output