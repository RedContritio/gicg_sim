"""Checked, isolated patches over executable DSL snapshots."""

from dataclasses import dataclass, asdict
import hashlib
from pathlib import Path
import shutil


@dataclass(frozen=True)
class Patch:
    path: str
    before: str
    after: str


def digest_tree(root):
    digest = hashlib.sha256()
    for p in sorted(Path(root).rglob('*')):
        if p.is_file():
            digest.update(p.relative_to(root).as_posix().encode() + b'\0' + p.read_bytes())
    return digest.hexdigest()


def apply(source, destination, patches, pool='native_latest'):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError('patch destination must be outside source tree')
    if Path(pool).name != pool or pool in ('', '.', '..'):
        raise ValueError('invalid pool name')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('patch destination must be absent or empty')
    staged = {}
    for patch in patches:
        relative = Path(patch.path)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('patch path must be relative and confined')
        if not (relative.parts[:1] == ('system',) or relative.parts[:2] == ('pools', pool)):
            raise ValueError('patch outside selected executable data')
        original = source / relative
        if source not in original.resolve().parents:
            raise ValueError('patch source escapes data root')
        text = staged.get(relative)
        if text is None:
            text = original.read_text(encoding='utf-8')
        if not patch.before or text.count(patch.before) != 1:
            raise ValueError(f'expected exactly one patch match in {relative}')
        staged[relative] = text.replace(patch.before, patch.after)
    # All match/path checks precede filesystem writes.
    shutil.copytree(source / 'system', destination / 'system')
    shutil.copytree(source / 'pools' / pool, destination / 'pools' / pool)
    for relative, text in staged.items():
        (destination / relative).write_text(text, encoding='utf-8')
    return dict(data_sha256=digest_tree(destination), pool=pool, patches=[asdict(p) for p in patches])
