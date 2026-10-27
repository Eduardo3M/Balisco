"""Generate local previews for library files and containers."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path, PureWindowsPath
import base64
import posixpath
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont, ImageOps


THUMBNAIL_SIZE = (600, 800)
VIDEO_EXTENSIONS = {'.3gp', '.avi', '.m4v', '.mkv', '.mov', '.mp4', '.mpeg', '.mpg', '.ogv', '.ts', '.webm', '.wmv'}
KINDLE_EXTENSIONS = {'.azw', '.azw3', '.mobi', '.prc'}
EPUB_EXTENSIONS = {'.epub', '.kepub'}
OFFICE_EXTENSIONS = {'.docx', '.pptx', '.xlsx', '.odt', '.odp', '.ods'}
COMIC_IMAGE_EXTENSIONS = {'.avif', '.bmp', '.gif', '.jpeg', '.jpg', '.png', '.tif', '.tiff', '.webp'}


def thumbnail_name(profile: str, relative_path: str) -> str:
    normalized = PureWindowsPath(relative_path).as_posix().casefold()
    return sha256(f'{profile}\0{normalized}'.encode('utf-8')).hexdigest() + '.jpg'


def _font(size: int, bold: bool = False):
    candidates = ([r'C:\Windows\Fonts\segoeuib.ttf', r'C:\Windows\Fonts\arialbd.ttf'] if bold else
                  [r'C:\Windows\Fonts\segoeui.ttf', r'C:\Windows\Fonts\arial.ttf'])
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.width * image.height > 100_000_000:
        image.thumbnail((2400, 3200), Image.Resampling.LANCZOS)
    if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
        rgba = image.convert('RGBA')
        background = Image.new('RGBA', rgba.size, (22, 25, 32, 255))
        background.alpha_composite(rgba)
        image = background.convert('RGB')
    else:
        image = image.convert('RGB')
    return ImageOps.fit(image, THUMBNAIL_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))


def _image_from_bytes(data: bytes):
    with Image.open(BytesIO(data)) as image:
        return _fit(image.copy())


def _epub_cover(path: Path):
    with zipfile.ZipFile(path) as book:
        container = ET.fromstring(book.read('META-INF/container.xml'))
        rootfile = next((node.attrib.get('full-path') for node in container.iter()
                         if node.tag.endswith('rootfile') and node.attrib.get('full-path')), None)
        if not rootfile:
            return None
        package = ET.fromstring(book.read(rootfile))
        metadata = next((node for node in package if node.tag.endswith('metadata')), None)
        manifest = next((node for node in package if node.tag.endswith('manifest')), None)
        if manifest is None:
            return None
        cover_id = None
        if metadata is not None:
            for node in metadata.iter():
                if node.tag.endswith('meta') and node.attrib.get('name', '').casefold() == 'cover':
                    cover_id = node.attrib.get('content')
                    break
        items = list(manifest)
        image_item = next((node for node in items if 'cover-image' in node.attrib.get('properties', '').split()), None)
        if image_item is None and cover_id:
            image_item = next((node for node in items if node.attrib.get('id') == cover_id), None)
        if image_item is None:
            image_item = next((node for node in items if node.attrib.get('media-type', '').startswith('image/')), None)
        href = image_item.attrib.get('href') if image_item is not None else None
        if not href:
            return None
        internal = posixpath.normpath(posixpath.join(posixpath.dirname(rootfile), href))
        if internal.startswith('../') or internal.startswith('/'):
            return None
        return _image_from_bytes(book.read(internal))


def _fb2_cover(path: Path):
    """Extract the cover image referenced by a FictionBook document."""
    try:
        root = ET.parse(path).getroot()
        cover_id = None
        for node in root.iter():
            if not node.tag.endswith('coverpage'):
                continue
            for child in node:
                if child.tag.endswith('image'):
                    cover_id = next((value for key, value in child.attrib.items()
                                     if key == 'href' or key.endswith('}href')), '').lstrip('#')
                    if cover_id:
                        break
            if cover_id:
                break
        if not cover_id:
            return None
        for node in root.iter():
            if node.tag.endswith('binary') and node.attrib.get('id') == cover_id and node.text:
                encoded = ''.join(node.text.split())
                if len(encoded) <= 48 * 1024 * 1024:
                    return _image_from_bytes(base64.b64decode(encoded))
    except Exception:
        return None
    return None


def _pdf_preview(path: Path):
    try:
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(str(path))
        if len(document) < 1:
            document.close()
            return None
        page = document[0]
        bitmap = page.render(scale=1.5)
        try:
            return _fit(bitmap.to_pil())
        finally:
            bitmap.close()
            page.close()
            document.close()
    except Exception:
        return None


def _mobi_cover(path: Path):
    """Read the embedded cover record from DRM-free MOBI/AZW books."""
    try:
        data = path.read_bytes()
        if len(data) < 86:
            return None
        record_count = int.from_bytes(data[76:78], 'big')
        if record_count < 2 or record_count > 100_000:
            return None
        offsets = [int.from_bytes(data[78 + index * 8:82 + index * 8], 'big')
                   for index in range(record_count)]
        if any(offset >= len(data) for offset in offsets) or offsets != sorted(offsets):
            return None
        records = [data[offsets[index]:offsets[index + 1] if index + 1 < record_count else len(data)]
                   for index in range(record_count)]
        header = records[0]
        mobi_start = header.find(b'MOBI', 16, min(len(header), 64))
        if mobi_start < 0 or len(header) < mobi_start + 0x84:
            return None
        mobi_length = int.from_bytes(header[mobi_start + 4:mobi_start + 8], 'big')
        first_image = int.from_bytes(header[mobi_start + 0x6C:mobi_start + 0x70], 'big')
        exth_flags = int.from_bytes(header[mobi_start + 0x80:mobi_start + 0x84], 'big')
        cover_offset = None
        if exth_flags & 0x40:
            exth_start = mobi_start + mobi_length
            if header[exth_start:exth_start + 4] == b'EXTH' and len(header) >= exth_start + 12:
                exth_length = int.from_bytes(header[exth_start + 4:exth_start + 8], 'big')
                count = int.from_bytes(header[exth_start + 8:exth_start + 12], 'big')
                cursor = exth_start + 12
                end = min(exth_start + exth_length, len(header))
                for _ in range(count):
                    if cursor + 8 > end:
                        break
                    kind = int.from_bytes(header[cursor:cursor + 4], 'big')
                    size = int.from_bytes(header[cursor + 4:cursor + 8], 'big')
                    if size < 8 or cursor + size > end:
                        break
                    if kind in (201, 202) and size >= 12:
                        cover_offset = int.from_bytes(header[cursor + 8:cursor + 12], 'big')
                        if kind == 201:
                            break
                    cursor += size
        candidate_indexes = []
        if cover_offset is not None:
            candidate_indexes.append(first_image + cover_offset)
        if first_image < record_count:
            candidate_indexes.extend(range(first_image, min(record_count, first_image + 8)))
        for index in dict.fromkeys(candidate_indexes):
            if 0 <= index < record_count:
                try:
                    return _image_from_bytes(records[index])
                except Exception:
                    continue
    except (OSError, ValueError, IndexError, OverflowError):
        return None
    return None


def _office_preview(path: Path):
    """Use a preview image embedded by Office/OpenDocument editors, if present."""
    candidates = ('docProps/thumbnail.jpeg', 'docProps/thumbnail.png',
                  'Thumbnails/thumbnail.png', 'Thumbnails/thumbnail.jpeg')
    try:
        with zipfile.ZipFile(path) as document:
            for name in candidates:
                try:
                    info = document.getinfo(name)
                except KeyError:
                    continue
                if info.file_size > 32 * 1024 * 1024:
                    continue
                try:
                    return _image_from_bytes(document.read(name))
                except Exception:
                    continue
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _comic_preview(path: Path):
    try:
        with zipfile.ZipFile(path) as archive:
            images = [entry for entry in archive.infolist()
                      if not entry.is_dir() and Path(entry.filename).suffix.casefold() in COMIC_IMAGE_EXTENSIONS]
            images.sort(key=lambda entry: (0 if Path(entry.filename).stem.casefold() in {'cover', 'front', '00'} else 1,
                                           entry.filename.casefold()))
            for entry in images[:8]:
                if entry.file_size > 32 * 1024 * 1024:
                    continue
                try:
                    return _image_from_bytes(archive.read(entry))
                except Exception:
                    continue
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _video_preview(path: Path):
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return None
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', '00:00:01', '-i', str(path),
               '-frames:v', '1', '-vf', 'scale=600:800:force_original_aspect_ratio=increase,crop=600:800',
               '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1']
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        result = subprocess.run(command, capture_output=True, timeout=25, check=False, creationflags=flags)
        return _image_from_bytes(result.stdout) if result.returncode == 0 and result.stdout else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _audio_art(path: Path):
    try:
        from mutagen import File as AudioFile  # Optional: extract embedded album art if available.
        audio = AudioFile(path)
        tags = getattr(audio, 'tags', None)
        if not tags:
            return None
        for value in tags.values():
            candidates = value if isinstance(value, (list, tuple)) else (value,)
            for candidate in candidates:
                data = getattr(candidate, 'data', None)
                if isinstance(data, bytes) and data:
                    preview = _image_from_bytes(data)
                    if preview is not None:
                        return preview
    except Exception:
        pass
    return None


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int):
    words = text.split()
    lines = []
    line = ''
    for word in words:
        candidate = f'{line} {word}'.strip()
        if line and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _generated_preview(path: Path):
    digest = sha256(path.name.casefold().encode('utf-8')).digest()
    hue = digest[0] / 255
    base = (int(24 + 28 * hue), int(29 + 24 * digest[1] / 255), int(42 + 30 * digest[2] / 255))
    image = Image.new('RGB', THUMBNAIL_SIZE)
    pixels = image.load()
    for y in range(image.height):
        mix = y / image.height
        color = tuple(int(channel * (1 - mix) + end * mix) for channel, end in zip(base, (8, 10, 15)))
        for x in range(image.width):
            pixels[x, y] = color
    draw = ImageDraw.Draw(image, 'RGBA')
    draw.polygon([(0, 440), (600, 120), (600, 270), (0, 590)], fill=(255, 255, 255, 8), outline=(255, 255, 255, 20))
    ext = path.suffix.lstrip('.').upper()[:12] or 'ARCHIVO'
    draw.rounded_rectangle((48, 64, 190, 104), radius=10, fill=(8, 10, 15, 150), outline=(255, 255, 255, 45), width=2)
    draw.text((66, 72), ext, font=_font(20, True), fill=(220, 225, 237, 225))
    title = path.stem.replace('_', ' ').replace('-', ' ').strip() or path.name
    font = _font(39, True)
    lines = _wrap(draw, title, font, 500)
    if len(lines) > 7:
        font = _font(31, True)
        lines = _wrap(draw, title, font, 500)
    lines = lines[:7]
    height = sum(draw.textbbox((0, 0), line, font=font)[3] + 12 for line in lines)
    y = max(190, 360 - height // 2)
    for line in lines:
        draw.text((50, y), line, font=font, fill=(236, 238, 244, 245))
        y += draw.textbbox((0, 0), line, font=font)[3] + 12
    return image


def create_thumbnail(source: str | Path, destination: str | Path):
    """Create a real content preview when supported, and a generated file cover otherwise."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    preview = None
    suffix = source.suffix.casefold()
    if suffix in VIDEO_EXTENSIONS:
        preview = _video_preview(source)
    elif suffix in KINDLE_EXTENSIONS:
        preview = _mobi_cover(source)
    elif suffix in EPUB_EXTENSIONS:
        try:
            preview = _epub_cover(source)
        except Exception:
            preview = None
    elif suffix == '.fb2':
        preview = _fb2_cover(source)
    elif suffix == '.pdf':
        preview = _pdf_preview(source)
    elif suffix in OFFICE_EXTENSIONS:
        preview = _office_preview(source)
    elif suffix == '.cbz':
        preview = _comic_preview(source)
    elif suffix in {'.mp3', '.m4a', '.m4b', '.flac', '.ogg', '.opus', '.wav', '.wma', '.aac'}:
        preview = _audio_art(source)
    if preview is None:
        try:
            with Image.open(source) as image:
                preview = _fit(image.copy())
        except Exception:
            preview = _generated_preview(source)
    temporary = destination.with_name(destination.stem + '.tmp.jpg')
    try:
        preview.save(temporary, 'JPEG', quality=84, optimize=True, progressive=True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
