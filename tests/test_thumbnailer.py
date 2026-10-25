import io
import base64
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from core.thumbnailer import _comic_preview, _fb2_cover, _mobi_cover, _office_preview, _pdf_preview


def jpeg_bytes(color):
    image = Image.new('RGB', (40, 60), color)
    output = io.BytesIO()
    image.save(output, format='JPEG')
    return output.getvalue()


def mobi_fixture():
    first_image = 1
    exth_entry = (201).to_bytes(4, 'big') + (12).to_bytes(4, 'big') + (1).to_bytes(4, 'big')
    exth = b'EXTH' + (12 + len(exth_entry)).to_bytes(4, 'big') + (1).to_bytes(4, 'big') + exth_entry
    mobi = bytearray(0xE4)
    mobi[:4] = b'MOBI'
    mobi[4:8] = (0xE4).to_bytes(4, 'big')
    mobi[0x6C:0x70] = first_image.to_bytes(4, 'big')
    mobi[0x80:0x84] = (0x40).to_bytes(4, 'big')
    header_record = bytes(16) + mobi + exth
    image_records = [jpeg_bytes('blue'), jpeg_bytes('red')]
    record_count = 1 + len(image_records)
    record_table_end = 78 + 8 * record_count
    offsets = [record_table_end]
    for record in [header_record, *image_records][:-1]:
        offsets.append(offsets[-1] + len(record))
    pdb = bytearray(record_table_end)
    pdb[76:78] = record_count.to_bytes(2, 'big')
    for index, offset in enumerate(offsets):
        pdb[78 + 8 * index:82 + 8 * index] = offset.to_bytes(4, 'big')
    return bytes(pdb) + header_record + b''.join(image_records)


def simple_pdf():
    stream = b'BT /F1 24 Tf 10 50 Td (PDF preview) Tj ET'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
    ]
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f'{index} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = len(data)
    data.extend(f'xref\n0 {len(offsets)}\n'.encode() + b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return bytes(data)


class ThumbnailerFormatTests(unittest.TestCase):
    def test_extracts_kindle_cover_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / 'sample.azw3'
            book.write_bytes(mobi_fixture())
            preview = _mobi_cover(book)
            self.assertIsNotNone(preview)
            self.assertGreater(preview.getpixel((300, 400))[0], 180)

    def test_reads_office_embedded_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = Path(tmp) / 'sample.docx'
            with zipfile.ZipFile(document, 'w') as archive:
                archive.writestr('docProps/thumbnail.jpeg', jpeg_bytes('green'))
            preview = _office_preview(document)
            self.assertIsNotNone(preview)
            self.assertGreater(preview.getpixel((300, 400))[1], 100)

    def test_reads_first_cbz_page_as_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            comic = Path(tmp) / 'sample.cbz'
            with zipfile.ZipFile(comic, 'w') as archive:
                archive.writestr('001.jpg', jpeg_bytes('blue'))
                archive.writestr('cover.jpg', jpeg_bytes('red'))
            preview = _comic_preview(comic)
            self.assertIsNotNone(preview)
            self.assertGreater(preview.getpixel((300, 400))[0], 180)

    def test_extracts_fictionbook_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / 'sample.fb2'
            encoded = base64.b64encode(jpeg_bytes('purple')).decode()
            book.write_text(
                '<FictionBook xmlns:xlink="http://www.w3.org/1999/xlink"><description><title-info>'
                '<coverpage><image xlink:href="#cover"/></coverpage></title-info></description>'
                f'<binary id="cover" content-type="image/jpeg">{encoded}</binary></FictionBook>',
                encoding='utf-8',
            )
            preview = _fb2_cover(book)
            self.assertIsNotNone(preview)
            self.assertGreater(preview.getpixel((300, 400))[0], 100)

    def test_renders_first_pdf_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = Path(tmp) / 'sample.pdf'
            document.write_bytes(simple_pdf())
            preview = _pdf_preview(document)
            self.assertIsNotNone(preview)
            self.assertEqual(preview.size, (600, 800))


if __name__ == '__main__':
    unittest.main()
