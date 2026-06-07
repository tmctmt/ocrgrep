from dataclasses import dataclass
from datetime import timedelta
from fnmatch import fnmatch
from functools import partial
from multiprocessing import Pool, cpu_count, set_start_method
from pathlib import Path
import argparse
import re
import sys

from locro import ScreenAI
from tqdm import tqdm
import cv2
import filetype
import PIL

RED = '\033[31m'
YELLOW = '\033[33m'
MAGENTA = '\033[35m'
RESET = '\033[39m'

@dataclass(frozen=True)
class Result:
    path: Path
    text: str

@dataclass(frozen=True)
class VideoResult(Result):
    msec: float

def ocr(path: Path, args: argparse.Namespace):
    if 'engine' not in globals():
        global engine
        engine = ScreenAI()

    results: list[Result] = []

    if filetype.is_image(path) and not args.no_image:
        image = PIL.Image.open(path)
        text = engine.ocr_pil_image(image).text
        results.append(Result(path, text))
    
    if filetype.is_video(path) and not args.no_video:
        cap = cv2.VideoCapture(path)
        if cap.get(cv2.CAP_PROP_FRAME_COUNT) == -1:
            return results
        prev_msec = None
        while True:
            msec = cap.get(cv2.CAP_PROP_POS_MSEC)
            if args.video_max_msec and msec > args.video_max_msec:
                break
            if prev_msec and (msec - prev_msec) < args.video_step_msec:
                success = cap.grab()
                if success:
                    continue
                break
            prev_msec = msec
            success, image = cap.read()
            if not success:
                break
            image = PIL.Image.fromarray(image)
            text = engine.ocr_pil_image(image).text
            results.append(VideoResult(path, text, msec))
        cap.release()
            
    return results

def cli():
    p = argparse.ArgumentParser(
        description='grep-like OCR tool for images and videos.',
        epilog='example: %(prog)s -i "hello world" video.mp4 screenshot.png',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )
    p.add_argument('pattern')
    p.add_argument('files', nargs='+')
    p.add_argument('-i', '--ignore-case', action='store_true',
                   help='ignore case distinctions in patterns and data')
    p.add_argument('-m', '--max-count', type=int, metavar='NUM',
                   help='stop after NUM selected lines')
    p.add_argument('-p', '--progress', action='store_true',
                   help='show progress bar')
    p.add_argument('-r', '--recursive', action='store_true',
                   help='scan subfiles in directories')
    p.add_argument('-w', '--workers', type=int, default=int(cpu_count()//2), metavar='NUM',
                   help='concurrency (default: %(default)s)')
    p.add_argument('-C', '--context', type=int, default=40, metavar='NUM',
                   help='print NUM characters of output context (default: %(default)s)')
    p.add_argument('-F', '--fixed-strings', action='store_true',
                   help='PATTERN is a string')
    p.add_argument('-h', '--no-filename', action='store_true',
                   help='suppress the file name prefix on output')
    p.add_argument('-t', '--no-timestamp', action='store_true',
                   help='suppress the timestamp prefix on output for videos')
    p.add_argument('--include', action='append', default=[], metavar='GLOB',
                   help='search only files that match GLOB (a file pattern)')
    p.add_argument('--exclude', action='append', default=[], metavar='GLOB',
                   help='skip files that match GLOB')
    p.add_argument('--no-image', action='store_true',
                   help='ignore image files')
    p.add_argument('--no-video', action='store_true',
                   help='ignore video files')
    p.add_argument('--video-max-msec', type=int, metavar='NUM',
                   help='stop after NUM milliseconds of video')
    p.add_argument('--video-step-msec', type=int, default=1000, metavar='NUM',
                   help='scan a frame for every NUM milliseconds of video (default: %(default)s)')
    p.add_argument('--help', action='help',
                   help='show this help message and exit')
    
    args = p.parse_args()
    pattern = re.escape(args.pattern) if args.fixed_strings else args.pattern
    flags = re.IGNORECASE if args.ignore_case else 0

    def should_include(path: Path):
        if args.exclude and any(fnmatch(path, pat) for pat in args.exclude):
            return False
        if args.include and not any(fnmatch(path, pat) for pat in args.include):
            return False
        return True

    files = []
    for path in map(Path, args.files):
        if path.is_file() and should_include(path):
            files.append(path)
        elif path.is_dir() and args.recursive:
            files.extend(s for s in path.rglob('*') if s.is_file() and should_include(s))
        elif path.is_dir():
            print(f'ocrgrep: {path}: Is a directory', file=sys.stderr)
        else:
            print(f'ocrgrep: {path}: No such file or directory', file=sys.stderr)

    set_start_method('spawn')
    with Pool(args.workers) as pool, tqdm(total=len(files), disable=not args.progress) as pbar:
        for results in pool.imap_unordered(partial(ocr, args=args), files):
            count = 0
            for result in results:
                text = re.sub(r'\s+', r' ', result.text)
                if match := re.search(pattern, text, flags=flags):
                    line = ''
                    if not args.no_filename:
                        line += MAGENTA + str(result.path) + RESET + ':'
                    if not args.no_timestamp and isinstance(result, VideoResult):
                        line += YELLOW + str(timedelta(milliseconds=result.msec))[:-3] + RESET + ':'
                    line += re.sub(
                        pattern,
                        lambda m: RED + m.group(0) + RESET,
                        text[max(0, match.start() - args.context) : match.end() + args.context].strip(),
                        flags=flags
                    )
                    pbar.write(line)
                    count += 1
                    if count == args.max_count:
                        break
            pbar.update()

if __name__ == '__main__':
    cli()