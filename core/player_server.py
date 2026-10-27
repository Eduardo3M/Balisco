"""Local loopback streaming and document rendering server for Balisco Player."""
from __future__ import annotations

from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, unquote, urlparse
import html
import mimetypes
import posixpath
import re
import secrets
import shutil
import threading
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageOps


MIME_OVERRIDES = {
    '.mp4': 'video/mp4',
    '.m4v': 'video/mp4',
    '.webm': 'video/webm',
    '.ogv': 'video/ogg',
    '.mov': 'video/quicktime',
    '.mkv': 'video/x-matroska',
    '.avi': 'video/x-msvideo',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    '.mpg': 'video/mpeg',
    '.mpeg': 'video/mpeg',
    '.3gp': 'video/3gpp',
    '.ts': 'video/mp2t',
    '.mp3': 'audio/mpeg',
    '.m4a': 'audio/mp4',
    '.m4b': 'audio/mp4',
    '.aac': 'audio/aac',
    '.flac': 'audio/flac',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.oga': 'audio/ogg',
    '.opus': 'audio/ogg',
    '.wma': 'audio/x-ms-wma',
    '.aiff': 'audio/aiff',
    '.aif': 'audio/aiff',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.bmp': 'image/bmp',
    '.avif': 'image/avif',
    '.ico': 'image/x-icon',
    '.pdf': 'application/pdf',
    '.epub': 'application/epub+zip',
}

BROWSER_NATIVE_IMAGES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.bmp', '.avif', '.ico'}
COMIC_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'}
VIDEO_EXTS = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v', '.wmv', '.flv', '.mpg', '.mpeg', '.3gp', '.3g2', '.ogv', '.ts', '.m2ts', '.mts', '.vob'}
AUDIO_EXTS = {'.mp3', '.m4a', '.m4b', '.aac', '.flac', '.wav', '.ogg', '.oga', '.opus', '.wma', '.aiff', '.aif', '.alac', '.ape', '.amr'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.svg', '.avif', '.ico', '.tif', '.tiff', '.heic', '.heif', '.jp2', '.j2k', '.apng'}
TEXT_EXTS = {
    '.txt', '.md', '.markdown', '.rst', '.log', '.csv', '.tsv', '.json', '.xml',
    '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.py', '.pyw', '.js', '.mjs',
    '.ts', '.tsx', '.jsx', '.html', '.htm', '.css', '.sql', '.sh', '.bat', '.ps1',
    '.c', '.cpp', '.h', '.hpp', '.cs', '.java', '.kt', '.rs', '.go', '.rb', '.php', '.lua',
}


def _guess_mime(path: str | Path) -> str:
    ext = Path(path).suffix.casefold()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or 'application/octet-stream'


def _natural_key(text: str):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', text)]


class PlayerServer:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self._lock = threading.RLock()
        self._tickets: dict[str, dict] = {}
        self._by_path: dict[str, str] = {}
        self._pdf_cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._pdf_docs: OrderedDict[str, tuple[int, threading.Lock, object]] = OrderedDict()
        self._server: ThreadingHTTPServer | None = None
        self._port: int = 0

    def ensure_started(self) -> int:
        with self._lock:
            if self._server is not None:
                return self._port
            parent = self

            class Handler(BaseHTTPRequestHandler):
                protocol_version = 'HTTP/1.1'

                def log_message(self, format, *args):
                    pass

                def _send_cors(self):
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type')

                def do_OPTIONS(self):
                    self.send_response(204)
                    self._send_cors()
                    self.send_header('Content-Length', '0')
                    self.end_headers()

                def do_HEAD(self):
                    self._handle(head_only=True)

                def do_GET(self):
                    self._handle(head_only=False)

                def _handle(self, head_only: bool):
                    try:
                        parsed = urlparse(self.path)
                        qs = parse_qs(parsed.query)
                        token = (qs.get('token') or [''])[0]
                        if not secrets.compare_digest(token, parent.token):
                            self._error(403, b'Forbidden')
                            return
                        parts = [p for p in parsed.path.split('/') if p]
                        if len(parts) < 2:
                            self._error(404, b'Not Found')
                            return
                        route, ticket = parts[0], parts[1]
                        entry = parent.get_ticket(ticket)
                        if not entry:
                            self._error(404, b'Ticket Not Found')
                            return
                        path: Path = entry['path']
                        if not path.is_file():
                            self._error(404, b'File Not Found')
                            return

                        if route == 'stream':
                            self._serve_file_range(path, _guess_mime(path), head_only)
                        elif route == 'pdf' and len(parts) >= 3:
                            page_idx = int(parts[2])
                            scale = float((qs.get('scale') or ['1.6'])[0])
                            data = parent.render_pdf_page(ticket, path, page_idx, scale)
                            self._serve_bytes(data, 'image/jpeg', head_only)
                        elif route == 'cbz' and len(parts) >= 3:
                            page_idx = int(parts[2])
                            data, mime = parent.read_cbz_page(entry, page_idx)
                            self._serve_bytes(data, mime, head_only)
                        elif route == 'image':
                            ext = path.suffix.casefold()
                            if ext in BROWSER_NATIVE_IMAGES:
                                self._serve_file_range(path, _guess_mime(path), head_only)
                            else:
                                data = parent.render_converted_image(path)
                                self._serve_bytes(data, 'image/jpeg', head_only)
                        elif route == 'epub_asset' and len(parts) >= 3:
                            rel_asset = unquote('/'.join(parts[2:]))
                            data, mime = parent.read_epub_asset(path, rel_asset)
                            self._serve_bytes(data, mime, head_only)
                        else:
                            self._error(404, b'Unknown Route')
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                    except Exception as exc:
                        try:
                            self._error(500, str(exc).encode('utf-8', errors='replace'))
                        except Exception:
                            pass

                def _error(self, code: int, body: bytes):
                    self.send_response(code)
                    self._send_cors()
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def _serve_bytes(self, data: bytes, mime: str, head_only: bool):
                    self.send_response(200)
                    self._send_cors()
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'private, max-age=3600')
                    self.end_headers()
                    if not head_only:
                        self.wfile.write(data)

                def _serve_file_range(self, path: Path, mime: str, head_only: bool):
                    size = path.stat().st_size
                    range_header = self.headers.get('Range')
                    start, end = 0, size - 1
                    status = 200
                    if range_header and range_header.startswith('bytes=') and size > 0:
                        spec = range_header[6:].split(',', 1)[0].strip()
                        if '-' in spec:
                            s_part, e_part = spec.split('-', 1)
                            try:
                                if s_part == '':
                                    suffix = int(e_part)
                                    start = max(0, size - suffix)
                                else:
                                    start = int(s_part)
                                    if e_part:
                                        end = min(size - 1, int(e_part))
                                if 0 <= start <= end < size:
                                    status = 206
                                else:
                                    self.send_response(416)
                                    self._send_cors()
                                    self.send_header('Content-Range', f'bytes */{size}')
                                    self.send_header('Content-Length', '0')
                                    self.end_headers()
                                    return
                            except ValueError:
                                start, end, status = 0, size - 1, 200

                    length = max(0, end - start + 1) if size > 0 else 0
                    self.send_response(status)
                    self._send_cors()
                    self.send_header('Content-Type', mime)
                    self.send_header('Accept-Ranges', 'bytes')
                    if status == 206:
                        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.send_header('Content-Length', str(length))
                    self.send_header('Cache-Control', 'private, max-age=600')
                    self.end_headers()
                    if head_only or length <= 0:
                        return
                    with path.open('rb') as handle:
                        handle.seek(start)
                        remaining = length
                        chunk_size = 262144
                        while remaining > 0:
                            chunk = handle.read(min(chunk_size, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.daemon_threads = True
            self._server = server
            self._port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True, name='BaliscoPlayerServer')
            thread.start()
            return self._port

    def register_file(self, path: Path, drive_id: str = '', container_id: str = '') -> tuple[str, dict]:
        resolved = path.resolve()
        stat = resolved.stat()
        key = f'{resolved}|{stat.st_mtime_ns}|{stat.st_size}'
        with self._lock:
            ticket = self._by_path.get(key)
            if ticket and ticket in self._tickets:
                return ticket, self._tickets[ticket]
            ticket = secrets.token_urlsafe(12)
            entry = {
                'ticket': ticket,
                'path': resolved,
                'drive_id': drive_id,
                'container_id': container_id,
                'mtime_ns': stat.st_mtime_ns,
                'size': stat.st_size,
            }
            self._tickets[ticket] = entry
            self._by_path[key] = ticket
            if len(self._tickets) > 120:
                oldest = next(iter(self._tickets))
                if oldest != ticket:
                    self._tickets.pop(oldest, None)
            return ticket, entry

    def get_ticket(self, ticket: str) -> dict | None:
        with self._lock:
            return self._tickets.get(ticket)

    def _get_pdf_doc(self, ticket: str, path: Path, mtime_ns: int):
        import pypdfium2 as pdfium
        with self._lock:
            cached = self._pdf_docs.get(ticket)
            if cached and cached[0] == mtime_ns:
                self._pdf_docs.move_to_end(ticket)
                return cached[1], cached[2]
            doc_lock = threading.Lock()
            doc = pdfium.PdfDocument(str(path))
            self._pdf_docs[ticket] = (mtime_ns, doc_lock, doc)
            while len(self._pdf_docs) > 6:
                _, (_, old_lock, old_doc) = self._pdf_docs.popitem(last=False)
                with old_lock:
                    try:
                        old_doc.close()
                    except Exception:
                        pass
            return doc_lock, doc

    def inspect_pdf(self, ticket: str, path: Path, mtime_ns: int) -> dict:
        doc_lock, doc = self._get_pdf_doc(ticket, path, mtime_ns)
        with doc_lock:
            count = len(doc)
            sizes = []
            limit = min(count, 2500)
            for idx in range(limit):
                try:
                    w, h = doc.get_page_size(idx)
                    sizes.append([round(float(w), 1), round(float(h), 1)])
                except Exception:
                    sizes.append([612.0, 792.0])
            toc = []
            try:
                for item in doc.get_toc():
                    if len(toc) >= 300:
                        break
                    if getattr(item, 'title', None) and getattr(item, 'page_index', None) is not None:
                        toc.append({
                            'title': str(item.title).strip(),
                            'page': max(0, int(item.page_index)),
                            'level': max(0, int(getattr(item, 'level', 0))),
                        })
            except Exception:
                pass
            return {'page_count': count, 'page_sizes': sizes, 'toc': toc}

    def render_pdf_page(self, ticket: str, path: Path, page_index: int, scale: float) -> bytes:
        scale = max(1.0, min(4.0, round(float(scale), 2)))
        mtime_ns = path.stat().st_mtime_ns
        cache_key = (ticket, mtime_ns, page_index, scale)
        with self._lock:
            if cache_key in self._pdf_cache:
                self._pdf_cache.move_to_end(cache_key)
                return self._pdf_cache[cache_key]
        doc_lock, doc = self._get_pdf_doc(ticket, path, mtime_ns)
        with doc_lock:
            if page_index < 0 or page_index >= len(doc):
                raise IndexError('Página fuera de rango')
            page = doc[page_index]
            bitmap = page.render(scale=scale)
            try:
                pil_img = bitmap.to_pil().convert('RGB')
            finally:
                bitmap.close()
                page.close()
        buf = BytesIO()
        pil_img.save(buf, 'JPEG', quality=94, subsampling=0, optimize=True)
        data = buf.getvalue()
        with self._lock:
            self._pdf_cache[cache_key] = data
            while len(self._pdf_cache) > 48:
                self._pdf_cache.popitem(last=False)
        return data

    def get_pdf_page_text(self, ticket: str, entry: dict, page_index: int) -> dict:
        path: Path = entry['path']
        mtime_ns = path.stat().st_mtime_ns
        doc_lock, doc = self._get_pdf_doc(ticket, path, mtime_ns)
        with doc_lock:
            if page_index < 0 or page_index >= len(doc):
                raise IndexError('Página fuera de rango')
            page = doc[page_index]
            try:
                pw, ph = doc.get_page_size(page_index)
                pw = max(1.0, float(pw))
                ph = max(1.0, float(ph))
                textpage = page.get_textpage()
                try:
                    spans = []
                    rect_count = min(600, int(textpage.count_rects()))
                    for i in range(rect_count):
                        left, bottom, right, top = textpage.get_rect(i)
                        txt = textpage.get_text_bounded(left, bottom, right, top).strip()
                        if not txt:
                            continue
                        x = max(0.0, min(100.0, (float(left) / pw) * 100.0))
                        y = max(0.0, min(100.0, ((ph - float(top)) / ph) * 100.0))
                        w = max(0.5, min(100.0 - x, ((float(right) - float(left)) / pw) * 100.0))
                        h = max(0.8, min(100.0 - y, ((float(top) - float(bottom)) / ph) * 100.0))
                        spans.append({
                            'x': round(x, 2),
                            'y': round(y, 2),
                            'w': round(w, 2),
                            'h': round(h, 2),
                            't': txt,
                        })
                    return {'page': page_index, 'spans': spans}
                finally:
                    textpage.close()
            finally:
                page.close()

    def search_pdf(self, ticket: str, entry: dict, query: str) -> dict:
        needle = str(query or '').strip()
        if not needle:
            return {'matches': []}
        path: Path = entry['path']
        mtime_ns = path.stat().st_mtime_ns
        doc_lock, doc = self._get_pdf_doc(ticket, path, mtime_ns)
        matches = []
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        with doc_lock:
            limit = min(len(doc), 1500)
            for idx in range(limit):
                page = doc[idx]
                try:
                    tp = page.get_textpage()
                    try:
                        text = tp.get_text_range() or ''
                    finally:
                        tp.close()
                finally:
                    page.close()
                found = list(pattern.finditer(text))
                if not found:
                    continue
                m = found[0]
                start = max(0, m.start() - 42)
                end = min(len(text), m.end() + 58)
                snippet = re.sub(r'\s+', ' ', text[start:end]).strip()
                matches.append({
                    'page': idx,
                    'count': len(found),
                    'snippet': snippet,
                })
                if len(matches) >= 120:
                    break
        return {'matches': matches}

    def search_epub(self, ticket: str, entry: dict, query: str) -> dict:
        needle = str(query or '').strip()
        if not needle:
            return {'matches': []}
        if 'epub_chapters' not in entry:
            self.inspect_epub(entry)
        chapters = entry.get('epub_chapters') or []
        path: Path = entry['path']
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        matches = []
        with zipfile.ZipFile(path, 'r') as zf:
            for ch in chapters[:400]:
                try:
                    raw = zf.read(ch['href']).decode('utf-8', errors='replace')
                    plain = re.sub(r'<[^>]+>', ' ', raw)
                    plain = html.unescape(re.sub(r'\s+', ' ', plain)).strip()
                    found = list(pattern.finditer(plain))
                    if not found:
                        continue
                    m = found[0]
                    start = max(0, m.start() - 40)
                    end = min(len(plain), m.end() + 60)
                    matches.append({
                        'chapter': ch['index'],
                        'title': ch['title'],
                        'count': len(found),
                        'snippet': plain[start:end].strip(),
                    })
                    if len(matches) >= 100:
                        break
                except Exception:
                    continue
        return {'matches': matches}

    def inspect_cbz(self, entry: dict) -> dict:
        path: Path = entry['path']
        with zipfile.ZipFile(path, 'r') as zf:
            names = [
                info.filename for info in zf.infolist()
                if not info.is_dir() and Path(info.filename).suffix.casefold() in COMIC_IMAGE_EXTS
            ]
        names.sort(key=_natural_key)
        entry['cbz_pages'] = names
        return {'page_count': len(names)}

    def read_cbz_page(self, entry: dict, page_index: int) -> tuple[bytes, str]:
        if 'cbz_pages' not in entry:
            self.inspect_cbz(entry)
        pages = entry.get('cbz_pages') or []
        if page_index < 0 or page_index >= len(pages):
            raise IndexError('Página de cómic fuera de rango')
        name = pages[page_index]
        with zipfile.ZipFile(entry['path'], 'r') as zf:
            data = zf.read(name)
        return data, _guess_mime(name)

    def render_converted_image(self, path: Path) -> bytes:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            if img.width * img.height > 36_000_000:
                img.thumbnail((3600, 3600), Image.Resampling.LANCZOS)
            rgb = img.convert('RGB')
            buf = BytesIO()
            rgb.save(buf, 'JPEG', quality=92)
            return buf.getvalue()

    def inspect_epub(self, entry: dict) -> dict:
        path: Path = entry['path']
        ext = path.suffix.casefold()
        if ext == '.fb2':
            return {'chapter_count': 1, 'chapters': [{'index': 0, 'title': path.stem}]}
        with zipfile.ZipFile(path, 'r') as zf:
            names = set(zf.namelist())
            container_xml = ET.fromstring(zf.read('META-INF/container.xml'))
            rootfile = container_xml.find('.//{*}rootfile')
            if rootfile is None or 'full-path' not in rootfile.attrib:
                raise ValueError('EPUB sin archivo OPF válido')
            opf_path = rootfile.attrib['full-path']
            opf_dir = PurePosixPath(opf_path).parent
            opf = ET.fromstring(zf.read(opf_path))

            manifest = {}
            for item in opf.findall('.//{*}manifest/{*}item'):
                ident = item.attrib.get('id')
                href = item.attrib.get('href')
                media = item.attrib.get('media-type', '')
                if ident and href:
                    resolved = posixpath.normpath(str(opf_dir / unquote(href)))
                    if resolved.startswith('./'):
                        resolved = resolved[2:]
                    manifest[ident] = {'href': resolved, 'media': media, 'props': item.attrib.get('properties', '')}

            # Read TOC labels if available
            toc_titles = {}
            for item in manifest.values():
                if 'nav' in item['props'] and item['href'] in names:
                    try:
                        nav_root = ET.fromstring(zf.read(item['href']))
                        nav_dir = PurePosixPath(item['href']).parent
                        for a in nav_root.findall('.//{*}a'):
                            href = a.attrib.get('href', '').split('#')[0]
                            text = ''.join(a.itertext()).strip()
                            if href and text:
                                norm = posixpath.normpath(str(nav_dir / unquote(href))).lstrip('./')
                                toc_titles.setdefault(norm, text)
                    except Exception:
                        pass
                elif item['media'] == 'application/x-dtbncx+xml' and item['href'] in names:
                    try:
                        ncx_root = ET.fromstring(zf.read(item['href']))
                        ncx_dir = PurePosixPath(item['href']).parent
                        for point in ncx_root.findall('.//{*}navPoint'):
                            label = ''.join(point.find('.//{*}text').itertext()).strip() if point.find('.//{*}text') is not None else ''
                            content = point.find('.//{*}content')
                            src = content.attrib.get('src', '').split('#')[0] if content is not None else ''
                            if src and label:
                                norm = posixpath.normpath(str(ncx_dir / unquote(src))).lstrip('./')
                                toc_titles.setdefault(norm, label)
                    except Exception:
                        pass

            chapters = []
            for itemref in opf.findall('.//{*}spine/{*}itemref'):
                idref = itemref.attrib.get('idref')
                info = manifest.get(idref)
                if not info or info['href'] not in names:
                    continue
                if 'html' not in info['media'] and not info['href'].lower().endswith(('.xhtml', '.html', '.htm', '.xml')):
                    continue
                idx = len(chapters)
                title = toc_titles.get(info['href']) or f'Capítulo {idx + 1}'
                chapters.append({'index': idx, 'href': info['href'], 'title': title})

            if not chapters:
                html_files = sorted(
                    [n for n in names if n.lower().endswith(('.xhtml', '.html', '.htm')) and not Path(n).name.startswith('.')],
                    key=_natural_key,
                )
                chapters = [{'index': i, 'href': h, 'title': f'Sección {i + 1}'} for i, h in enumerate(html_files)]

            entry['epub_chapters'] = chapters
            return {
                'chapter_count': len(chapters),
                'chapters': [{'index': ch['index'], 'title': ch['title']} for ch in chapters],
            }

    def read_epub_chapter(self, ticket: str, entry: dict, chapter_index: int) -> dict:
        path: Path = entry['path']
        port = self.ensure_started()
        if path.suffix.casefold() == '.fb2':
            raw = path.read_bytes()
            try:
                root = ET.fromstring(raw)
                paragraphs = []
                for elem in root.findall('.//{*}body//*'):
                    tag = elem.tag.split('}')[-1].lower()
                    text = (elem.text or '').strip()
                    if not text:
                        continue
                    if tag == 'title':
                        paragraphs.append(f'<h2>{html.escape(text)}</h2>')
                    elif tag == 'p':
                        paragraphs.append(f'<p>{html.escape(text)}</p>')
                return {'index': 0, 'title': path.stem, 'html': '\n'.join(paragraphs) or '<p>(Sin texto)</p>'}
            except Exception:
                return {'index': 0, 'title': path.stem, 'html': f'<pre>{html.escape(raw.decode("utf-8", errors="replace")[:200000])}</pre>'}

        if 'epub_chapters' not in entry:
            self.inspect_epub(entry)
        chapters = entry.get('epub_chapters') or []
        if chapter_index < 0 or chapter_index >= len(chapters):
            raise IndexError('Capítulo fuera de rango')
        chapter = chapters[chapter_index]
        href = chapter['href']
        chapter_dir = PurePosixPath(href).parent

        with zipfile.ZipFile(path, 'r') as zf:
            raw_bytes = zf.read(href)

        text = raw_bytes.decode('utf-8', errors='replace')
        # Extract body if present
        body_match = re.search(r'<body[^>]*>(.*)</body>', text, flags=re.I | re.S)
        body_html = body_match.group(1) if body_match else text
        # Strip unsafe tags
        body_html = re.sub(r'<(script|iframe|object|embed|style|link)\b[^>]*>.*?</\1>', '', body_html, flags=re.I | re.S)
        body_html = re.sub(r'<(script|iframe|object|embed|link|meta)\b[^>]*/?>', '', body_html, flags=re.I)
        body_html = re.sub(r'\son\w+\s*=\s*(["\']).*?\1', '', body_html, flags=re.I | re.S)

        def rewrite_asset(match):
            attr = match.group(1)
            quote_char = match.group(2)
            url = match.group(3).strip()
            if not url or url.startswith(('data:', 'http:', 'https:', '#', 'mailto:')):
                return match.group(0)
            clean_url = url.split('#')[0].split('?')[0]
            resolved = posixpath.normpath(str(chapter_dir / unquote(clean_url))).lstrip('./')
            asset_url = f'http://127.0.0.1:{port}/epub_asset/{ticket}/{quote(resolved)}?token={self.token}'
            return f'{attr}={quote_char}{asset_url}{quote_char}'

        body_html = re.sub(r'(\bsrc|\bhref|\bxlink:href)\s*=\s*(["\'])([^"\']+)\2', rewrite_asset, body_html, flags=re.I)
        # Convert SVG <image href="..."> where needed or keep clean HTML
        return {
            'index': chapter_index,
            'title': chapter['title'],
            'html': body_html.strip() or '<p class="epub-empty-chapter">(Página en blanco o sin texto)</p>',
        }

    def read_epub_asset(self, epub_path: Path, asset_path: str) -> tuple[bytes, str]:
        norm = posixpath.normpath(asset_path).lstrip('./')
        with zipfile.ZipFile(epub_path, 'r') as zf:
            if norm not in zf.namelist():
                # Case-insensitive fallback
                lower_map = {n.casefold(): n for n in zf.namelist()}
                norm = lower_map.get(norm.casefold(), norm)
            data = zf.read(norm)
        return data, _guess_mime(norm)

    def build_player_payload(self, path: Path, item_meta: dict) -> dict:
        port = self.ensure_started()
        drive_id = item_meta.get('drive_id', '')
        container_id = item_meta.get('container_id', '')
        ticket, entry = self.register_file(path, drive_id=drive_id, container_id=container_id)
        ext = path.suffix.casefold()
        base = f'http://127.0.0.1:{port}'
        stream_url = f'{base}/stream/{ticket}?token={self.token}'

        payload = {
            'ticket': ticket,
            'drive_id': drive_id,
            'container_id': container_id,
            'title': item_meta.get('titulo') or path.stem,
            'author': item_meta.get('autor') or '',
            'format': (item_meta.get('formato') or ext.lstrip('.')).upper() or 'ARCHIVO',
            'size': entry['size'],
            'ext': ext,
            'es_favorito': int(item_meta.get('es_favorito') or 0),
            'estado_lectura': item_meta.get('estado_lectura') or 'pendiente',
            'rating': int(item_meta.get('rating') or 0),
            'stream_url': stream_url,
        }

        if ext == '.pdf':
            info = self.inspect_pdf(ticket, path, entry['mtime_ns'])
            payload.update({
                'kind': 'pdf',
                'page_count': info['page_count'],
                'page_sizes': info['page_sizes'],
                'toc': info['toc'],
                'page_url_prefix': f'{base}/pdf/{ticket}/',
                'page_url_suffix': f'?token={self.token}',
            })
        elif ext in {'.epub', '.kepub', '.fb2'}:
            info = self.inspect_epub(entry)
            first_chapter = self.read_epub_chapter(ticket, entry, 0) if info['chapter_count'] > 0 else {'index': 0, 'title': '', 'html': ''}
            payload.update({
                'kind': 'epub',
                'chapter_count': info['chapter_count'],
                'chapters': info['chapters'],
                'initial_chapter': first_chapter,
            })
        elif ext == '.cbz':
            info = self.inspect_cbz(entry)
            payload.update({
                'kind': 'cbz',
                'page_count': info['page_count'],
                'page_url_prefix': f'{base}/cbz/{ticket}/',
                'page_url_suffix': f'?token={self.token}',
            })
        elif ext in VIDEO_EXTS:
            payload['kind'] = 'video'
        elif ext in AUDIO_EXTS:
            payload['kind'] = 'audio'
        elif ext in IMAGE_EXTS:
            payload.update({
                'kind': 'image',
                'image_url': f'{base}/image/{ticket}?token={self.token}',
            })
        elif ext in TEXT_EXTS or entry['size'] <= 512_000:
            raw = path.read_bytes()[:1_500_000]
            # Check if binary
            if b'\x00' in raw[:4096] and ext not in TEXT_EXTS:
                payload['kind'] = 'unsupported'
            else:
                try:
                    text = raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    text = raw.decode('cp1252', errors='replace')
                payload.update({
                    'kind': 'text',
                    'content': text,
                    'truncated': entry['size'] > 1_500_000,
                })
        else:
            payload['kind'] = 'unsupported'

        return payload


_PLAYER_SERVER: PlayerServer | None = None
_SERVER_INIT_LOCK = threading.Lock()


def get_player_server() -> PlayerServer:
    global _PLAYER_SERVER
    with _SERVER_INIT_LOCK:
        if _PLAYER_SERVER is None:
            _PLAYER_SERVER = PlayerServer()
        return _PLAYER_SERVER
