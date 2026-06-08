## ocrgrep
A grep-like OCR tool for image and video files, utilizing the fast and decently accurate [Chrome Screen AI](https://chromium.googlesource.com/chromium/src/+/refs/tags/126.0.6452.4/services/screen_ai/README.md) engine via [locro](https://github.com/sergiocorreia/clv-locro/tree/master). No indexing needed.

```
$ ocrgrep -ih 'grep-like' screenshot.png    
rep README.md in main Preview ocrgrep A grep-like OCR tool for image and video files, uti
```

```
usage: ocrgrep.py [-i] [-m NUM] [-p] [-r] [-w NUM] [-C NUM] [-F] [-h] [-t] [--include GLOB]
                  [--exclude GLOB] [--no-image] [--no-video] [--video-max-msec NUM]
                  [--video-step-msec NUM] [--help]
                  pattern files [files ...]

positional arguments:
  pattern
  files

options:
  -i, --ignore-case     ignore case distinctions in patterns and data
  -m, --max-count NUM   stop after NUM selected lines
  -p, --progress        show progress bar
  -r, --recursive       scan subfiles in directories
  -w, --workers NUM     concurrency (default: 16)
  -C, --context NUM     print NUM characters of output context (default: 40)
  -F, --fixed-strings   PATTERN is a string
  -h, --no-filename     suppress the file name prefix on output
  -t, --no-timestamp    suppress the timestamp prefix on output for videos
  --include GLOB        search only files that match GLOB (a file pattern)
  --exclude GLOB        skip files that match GLOB
  --no-image            ignore image files
  --no-video            ignore video files
  --video-max-msec NUM  stop after NUM milliseconds of video
  --video-step-msec NUM
                        scan a frame for every NUM milliseconds of video (default: 1000)
  --help                show this help message and exit
```
  
# Install
```
pip install git+https://github.com/sergiocorreia/clv-locro.git@ba53ee24ee649e39c23daee3c8e9bec946642743
locro download
pip install ocrgrep
```
