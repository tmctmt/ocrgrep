import argparse
import re
import sys
import warnings
from dataclasses import dataclass
from datetime import timedelta
from fnmatch import fnmatch
from functools import partial
from multiprocessing import Pool, cpu_count, set_start_method
from pathlib import Path

import cv2
import pymupdf
from filetype import guess
from filetype.types import DOCUMENT, IMAGE, VIDEO
from locro import ScreenAI
from PIL import Image
from tqdm import tqdm

warnings.filterwarnings('ignore', category=UserWarning, module='PIL')
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


RED = '\033[31m'
YELLOW = '\033[33m'
MAGENTA = '\033[35m'
RESET = '\033[39m'

EXTRA_DOC_EXTS = {
    'pdf', 'epub', 'mobi', 'fb2',
    'xps', 'oxps', 'cbz', 'hwpx'
}


@dataclass(frozen=True, slots=True)
class Result:
    text: str


@dataclass(frozen=True)
class VideoResult(Result):
    msec: float


@dataclass(frozen=True)
class DocumentResult(Result):
    page: int


def ocr_image(path: Path):
    try:
        image = Image.open(path)
        text = engine.ocr_pil_image(image).text
        yield Result(text)
    except (OSError, Image.UnidentifiedImageError,
            Image.DecompressionBombError):
        pass


def ocr_video(path: Path, end_ms: float | None, step_ms: float | None):
    try:
        cap = None
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened() or cap.get(cv2.CAP_PROP_FRAME_WIDTH) == 0:
            return
        last_ms: float | None = None
        while True:
            ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            if end_ms is not None and ms > end_ms:
                return
            if last_ms is not None and step_ms is not None:
                while ms - last_ms < step_ms:
                    if not cap.grab():
                        return
                    ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            ok, frame = cap.read()
            if not ok:
                return
            last_ms = ms
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            text = engine.ocr_pil_image(image).text
            yield VideoResult(text, cap.get(cv2.CAP_PROP_POS_MSEC))
    except cv2.error:
        pass
    finally:
        if cap:
            cap.release()


def ocr_document(path: Path):
    try:
        doc = None
        doc = pymupdf.open(path)
        for page_index, page in enumerate(doc):
            pix = page.get_pixmap(dpi=300)
            pil_image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            text = engine.ocr_pil_image(pil_image).text
            yield DocumentResult(text, page_index + 1)
    except RuntimeError:
        pass
    finally:
        if doc:
            doc.close()


def ocr(path: Path, args: argparse.Namespace):
    if 'engine' not in globals():
        global engine
        engine = ScreenAI()

    results: list[Result] = []

    try:
        kind = guess(path)

        if kind in IMAGE and not args.no_image:
            results.extend(ocr_image(path))

        if kind in VIDEO and not args.no_video:
            results.extend(ocr_video(path, args.video_max_msec, args.video_step_msec))

        is_document = (
            kind in DOCUMENT
            or kind and kind.extension in EXTRA_DOC_EXTS
        )
        if is_document and not args.no_document:
            results.extend(ocr_document(path))

    except (OSError, PermissionError):
        pass

    return path, results


def cli():
    p = argparse.ArgumentParser(
        description='grep-like OCR tool for images and videos.',
        epilog='example: %(prog)s -i "hello world" video.mp4 screenshot.png',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )
    p.add_argument('pattern')
    p.add_argument('files', nargs='+', type=Path)
    p.add_argument('-i', '--ignore-case', action='store_true',
                   help='ignore case distinctions in patterns and data')
    p.add_argument('-m', '--max-count', type=int, metavar='NUM',
                   help='stop scanning file after NUM matches')
    p.add_argument('-p', '--progress', action='store_true',
                   help='show progress bar')
    p.add_argument('-r', '--recursive', action='store_true',
                   help='scan subfiles in directories')
    p.add_argument('-w', '--workers', type=int, metavar='NUM',
                   default=max(1, cpu_count() // 2),
                   help='concurrency (default: %(default)s)')
    p.add_argument('-C', '--context', type=int, default=40, metavar='NUM',
                   help='print NUM characters of output context '
                        '(default: %(default)s)')
    p.add_argument('-F', '--fixed-strings', action='store_true',
                   help='PATTERN is a string')
    p.add_argument('-h', '--no-filename', action='store_true',
                   help='suppress the file name prefix on output')
    p.add_argument('-t', '--no-info', action='store_true',
                   help='suppress extra info for matches '
                        '(video timestamp, document page number)')
    p.add_argument('--include', action='append', default=[], metavar='GLOB',
                   help='search only files that match GLOB (a file pattern)')
    p.add_argument('--exclude', action='append', default=[], metavar='GLOB',
                   help='skip files that match GLOB')
    p.add_argument('--no-image', action='store_true',
                   help='skip image files')
    p.add_argument('--no-video', action='store_true',
                   help='skip video files')
    p.add_argument('--no-document', action='store_true',
                   help='skip document files')
    p.add_argument('--video-max-msec', type=int, metavar='NUM',
                   help='stop after NUM milliseconds of video')
    p.add_argument('--video-step-msec', type=int, default=1000,
                   metavar='NUM',
                   help='scan a frame for every NUM milliseconds of video '
                        '(default: %(default)s)')
    p.add_argument('--help', action='help',
                   help='show this help message and exit')

    args = p.parse_args()
    pattern = re.compile(
        re.escape(args.pattern) if args.fixed_strings else args.pattern,
        re.IGNORECASE if args.ignore_case else 0
    )

    def should_include(path: Path):
        if args.exclude and any(fnmatch(path, pat) for pat in args.exclude):
            return False
        if args.include and not any(fnmatch(path, pat) for pat in args.include):
            return False
        return True

    def iterate_files():
        for path in args.files:
            if path.is_file() and should_include(path):
                yield path
            elif path.is_dir() and args.recursive:
                for sub in path.rglob('*'):
                    if sub.is_file() and should_include(sub):
                        yield sub
            elif path.is_dir():
                print(f'ocrgrep: {path}: Is a directory', file=sys.stderr)
            else:
                print(f'ocrgrep: {path}: No such file or directory',
                      file=sys.stderr)

    set_start_method('spawn')
    with Pool(args.workers) as pool, tqdm(disable=not args.progress) as pbar:
        for path, results in pool.imap_unordered(partial(ocr, args=args), iterate_files()):
            count = 0
            for result in results:
                text = re.sub(r'\s+', r' ', result.text)
                match = pattern.search(text)
                if not match:
                    continue
                line = ''
                if not args.no_filename:
                    line += MAGENTA + str(path) + RESET + ':'
                    if not args.no_info:
                        if isinstance(result, VideoResult):
                            stamp = str(timedelta(milliseconds=result.msec)).split('.')[0]
                            line += YELLOW + stamp + RESET + ':'
                        if isinstance(result, DocumentResult):
                            line += YELLOW + str(result.page) + RESET + ':'
                start = max(0, match.start() - args.context)
                end = match.end() + args.context
                snippet = text[start:end].strip()
                highlighted = pattern.sub(lambda m: RED + m.group(0) + RESET, snippet)
                line += highlighted
                pbar.write(line)
                count += 1
                if count == args.max_count:
                    break
            pbar.update()


if __name__ == '__main__':
    cli()