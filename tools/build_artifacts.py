"""Immutable build generations and integrity records for POSIX hosts."""
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import uuid

def digest(path):
    with pathlib.Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

@contextlib.contextmanager
def generation(output):
    # Do not resolve the final component: it is the publication symlink.
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.parent/('.'+output.name+'.lock')
    with lock.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f'another build owns {output}') from None
        store = output.parent/('.'+output.name+'.generations')
        store.mkdir(exist_ok=True)
        path = pathlib.Path(tempfile.mkdtemp(prefix='build-', dir=store)).resolve()
        published = False
        link = output.parent/('.'+output.name+'.publish-'+uuid.uuid4().hex)
        legacy = None
        try:
            yield path
            link.symlink_to(path, target_is_directory=True)
            if output.exists() and not output.is_symlink():
                if not output.is_dir():
                    raise ValueError(f'output is not a directory: {output}')
                # One-time migration preserves every old file. Subsequent
                # builds replace only the symlink, atomically.
                legacy = store/('legacy-'+uuid.uuid4().hex)
                output.rename(legacy)
            try:
                os.replace(link, output)
            except BaseException:
                if legacy is not None:
                    legacy.rename(output)
                raise
            published = True
        finally:
            if link.is_symlink():
                link.unlink()
            if not published:
                shutil.rmtree(path)

def verify(output):
    output = pathlib.Path(output).resolve()
    info = json.loads((output/'build-info.json').read_text())
    if info.get('version') != 1:
        raise ValueError('unsupported build integrity record')
    for name, expected in info['artifacts'].items():
        target = (output/name).resolve()
        if target.parent != output or not target.is_file() or digest(target) != expected:
            raise ValueError(f'build artifact mismatch: {name}')
    actual = {p.name for p in output.iterdir() if p.suffix in ('.o', '.pcm')}
    recorded = {name for name in info['artifacts'] if pathlib.Path(name).suffix in ('.o', '.pcm')}
    if actual != recorded:
        raise ValueError('unrecorded or missing object/PCM in build generation')
    for name, expected in info['inputs'].items():
        target = pathlib.Path(name)
        if not target.is_file() or digest(target) != expected:
            raise ValueError(f'build input changed: {name}')
    return info
