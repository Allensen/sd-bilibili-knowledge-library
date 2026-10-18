"""Isolated, lazy runtime setup. Standard library only until ASR is requested."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

SKILL = Path(__file__).resolve().parents[1]
MODEL_NAME = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17'
MODEL_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/' + MODEL_NAME + '.tar.bz2'
ARCHIVE_SHA = '7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e'
MODEL_SHA = 'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51'
TOKENS_SHA = 'f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc'


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def write(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def progress(phase, **data):
    print(json.dumps(dict(phase=phase, **data), ensure_ascii=False), flush=True)


@contextlib.contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('另一进程正在使用此目录，请待其完成后重试。') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def download(url, path, sha=None, headers=None, maximum=4 * 1024**3):
    """Bounded retries; atomic completion; never trust a partial download."""
    if path.exists() and path.stat().st_size and (sha is None or digest(path) == sha):
        return 'cached'
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + '.partial')
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers or {'User-Agent': 'sd-bilibili-knowledge-library/0.2'})
            with urllib.request.urlopen(req, timeout=45) as response, partial.open('wb') as f:
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > maximum:
                        raise ValueError('下载超出本任务的大小上限。')
                    f.write(block)
            if not size or (sha and digest(partial) != sha):
                raise ValueError('下载内容为空或 SHA256 校验失败。')
            partial.replace(path)
            return 'downloaded'
        except (OSError, ValueError) as exc:
            last = exc
            if attempt == 0:
                time.sleep(1)
    # Avoid printing signed URLs or cookies in ordinary error messages.
    raise RuntimeError(f'下载失败（{type(last).__name__}），请检查联网权限或代理后重试。') from None


def ensure_dependencies(root, uv):
    spec = SKILL / 'scripts' / 'requirements.lock'
    marker = root / 'dependencies.json'
    signature = dict(requirements=digest(spec), python=sys.version.split()[0])
    if read(marker) == signature:
        check = subprocess.run([sys.executable, '-c', 'import sherpa_onnx,av,soundfile,psutil; from faster_whisper.vad import get_speech_timestamps'],
                               capture_output=True, timeout=30)
        if check.returncode == 0:
            return
    progress('准备转写依赖', message='仅在需要音频识别或提取画面时安装；使用独立环境。')
    subprocess.run([str(uv), '--no-config', '--no-cache', 'pip', 'sync',
                    '--python', sys.executable, '--require-hashes', '--only-binary', ':all:', '--reinstall',
                    str(spec)], check=True, timeout=900)
    write(marker, signature)


def ensure_model(root):
    target = root / 'models' / MODEL_NAME
    model = target / 'model.int8.onnx'
    if model.exists() and digest(model) == MODEL_SHA and (target/'tokens.txt').is_file() and digest(target/'tokens.txt') == TOKENS_SHA:
        return target
    if shutil.disk_usage(root).free < 700 * 1024**2:
        raise RuntimeError('模型准备需要约 700 MiB 临时可用空间。请先释放磁盘空间。')
    progress('准备识别模型', message='下载 SenseVoice INT8，约 156 MiB 压缩包；完成后自动清理压缩包。')
    archive = root / 'downloads' / (MODEL_NAME + '.tar.bz2')
    download(MODEL_URL, archive, ARCHIVE_SHA, maximum=200 * 1024**2)
    target.mkdir(parents=True, exist_ok=True)
    # Read only exact regular files; never extract archive paths, symlinks or scripts.
    with tarfile.open(archive, 'r:bz2') as tf:
        for name in ('model.int8.onnx', 'tokens.txt', 'LICENSE'):
            member = tf.getmember(MODEL_NAME + '/' + name)
            if not member.isfile() or member.size > 300 * 1024**2:
                raise ValueError('模型归档内容不符合预期。')
            out = target / (name + '.partial')
            with tf.extractfile(member) as src, out.open('wb') as dest:
                shutil.copyfileobj(src, dest)
            out.replace(target/name)
    if digest(model) != MODEL_SHA or digest(target/'tokens.txt') != TOKENS_SHA:
        raise ValueError('模型权重校验失败。')
    write(target/'provenance.json', dict(url=MODEL_URL, archive_sha256=ARCHIVE_SHA,
                                       model_sha256=MODEL_SHA, tokens_sha256=digest(target/'tokens.txt')))
    archive.unlink()
    return target


def prepare_asr(root, uv):
    with lock(root / 'setup.lock'):
        ensure_dependencies(root, uv)
        return ensure_model(root)
