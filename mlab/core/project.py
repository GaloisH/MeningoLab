"""项目（数据根目录）与病例管理。

目录约定::

    数据根目录/
    ├── case_001/                 # 子文件夹 = 一个病例，内含一个或多个已配准序列
    │   ├── T1C.nii.gz
    │   └── FLAIR.nii.gz
    ├── case_002_0000.nii.gz      # 或 nnU-Net 命名：同一前缀 + _0000/_0001 通道后缀
    ├── case_002_0001.nii.gz
    ├── case_003.nii.gz           # 或单个文件即一个病例
    ├── slide_01.png              # 二维图片：每张图一个病例
    ├── labels/                   # MLab 保存的标注（与原图同空间）
    └── .mlab/                    # 状态与标签配置
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .labels import LabelSet
from .volume import file_kind, strip_suffix

NNUNET_PATTERN = re.compile(r"^(?P<case>.+)_(?P<ch>\d{4})$")
MASK_HINT = re.compile(r"(^|[_\-. ])(seg|segmentation|label|labels|mask|gt)([_\-. ]|$)", re.I)
IGNORED_DIRS = {"labels", "labelsTr", "labelsTs", ".mlab"}

STATUS_TODO, STATUS_PRE, STATUS_WIP, STATUS_DONE = "todo", "pre", "wip", "done"
STATUS_TEXT = {STATUS_TODO: "未标注", STATUS_PRE: "预标注", STATUS_WIP: "标注中", STATUS_DONE: "已完成"}
STATUS_COLOR = {STATUS_TODO: "#8b95a5", STATUS_PRE: "#b48cff", STATUS_WIP: "#f0a630", STATUS_DONE: "#3fb97c"}
STATUS_ORDER = [STATUS_TODO, STATUS_PRE, STATUS_WIP, STATUS_DONE]


@dataclass
class Case:
    case_id: str
    images: list[Path]
    kind: str  # "3d" / "2d"
    channels: list[int | None] = field(default_factory=list)  # nnU-Net 通道号（若文件名带 _0000 后缀）

    @property
    def sequence_names(self) -> list[str]:
        names = []
        for p, ch in zip(self.images, self.channels):
            stem = strip_suffix(p.name)
            if ch is not None and stem.startswith(self.case_id):
                names.append(f"通道 {ch}")
            else:
                names.append(stem)
        return names


# 增强 T1 最适合观察脑膜强化，未使用 nnU-Net 命名时排在最前作为默认底图
CONTRAST_HINT = re.compile(r"t1c|t1ce|t1gd|t1\+c|t1_?post|gd|enh|增强", re.I)


def _sort_key(p: Path):
    stem = strip_suffix(p.name)
    m = NNUNET_PATTERN.match(stem)
    return (int(m["ch"]) if m else 10_000, 0 if CONTRAST_HINT.search(stem) else 1, p.name.lower())


def _group_files(files: list[Path], prefix: str = "") -> list[Case]:
    """把一个目录中的影像文件分组成病例。"""
    cases: list[Case] = []
    groups: dict[str, list[tuple[int, Path]]] = {}
    for f in sorted(files, key=lambda p: p.name.lower()):
        kind = file_kind(f)
        stem = strip_suffix(f.name)
        m = NNUNET_PATTERN.match(stem)
        if kind == "3d" and m:
            groups.setdefault(m["case"], []).append((int(m["ch"]), f))
        else:
            cases.append(Case(prefix + stem, [f], kind, [None]))  # type: ignore[arg-type]
    for cid, items in groups.items():
        items.sort()
        cases.append(Case(prefix + cid, [p for _, p in items], "3d", [c for c, _ in items]))
    return cases


def _image_files(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir()
            if p.is_file() and not p.name.startswith(".") and file_kind(p)
            and not MASK_HINT.search(strip_suffix(p.name))]


def scan_cases(root: Path) -> list[Case]:
    root = Path(root)
    cases = _group_files(_image_files(root))
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        if sub.name.startswith(".") or sub.name in IGNORED_DIRS:
            continue
        files = _image_files(sub)
        if not files:
            continue
        nifti = [f for f in files if file_kind(f) == "3d"]
        images2d = [f for f in files if file_kind(f) == "2d"]
        ids = {NNUNET_PATTERN.match(strip_suffix(f.name))["case"] for f in nifti
               if NNUNET_PATTERN.match(strip_suffix(f.name))}
        if len(ids) > 1:  # 如 nnU-Net 的 imagesTr 目录：多个病例
            cases += [c for c in _group_files(nifti) if c.kind == "3d"]
        elif nifti:  # 子文件夹即一个病例（多序列）
            nifti.sort(key=_sort_key)
            chans = [int(m["ch"]) if (m := NNUNET_PATTERN.match(strip_suffix(f.name))) else None for f in nifti]
            cases.append(Case(sub.name, nifti, "3d", chans))
        cases += [Case(f"{sub.name}_{strip_suffix(f.name)}", [f], "2d", [None]) for f in sorted(images2d)]
    seen: set[str] = set()
    unique = []
    for c in sorted(cases, key=lambda c: c.case_id.lower()):
        if c.case_id not in seen:
            seen.add(c.case_id)
            unique.append(c)
    return unique


class Project:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.meta_dir = self.root / ".mlab"
        self.labels_dir = self.root / "labels"
        self.cases: list[Case] = scan_cases(self.root)
        self._state_path = self.meta_dir / "project.json"
        self.state: dict[str, dict] = {}
        if self._state_path.exists():
            try:
                self.state = json.loads(self._state_path.read_text(encoding="utf-8")).get("cases", {})
            except (OSError, ValueError):
                self.state = {}
        for c in self.cases:  # 外部已有标签文件的病例视为“标注中”
            if c.case_id not in self.state and self.label_path(c).exists():
                self.state[c.case_id] = {"status": STATUS_WIP}

    # ------------------------------------------------------------------ 路径
    def label_path(self, case: Case) -> Path:
        ext = ".png" if case.kind == "2d" else ".nii.gz"
        return self.labels_dir / f"{case.case_id}{ext}"

    def labelset_path(self) -> Path:
        return self.meta_dir / "labels.json"

    def load_labelset(self) -> LabelSet:
        p = self.labelset_path()
        if p.exists():
            try:
                return LabelSet.load(p)
            except (OSError, ValueError, KeyError):
                pass
        ls = LabelSet.default()
        self.save_labelset(ls)
        return ls

    def save_labelset(self, ls: LabelSet) -> None:
        try:
            ls.save(self.labelset_path())
        except OSError:
            pass  # 只读目录：仅在内存中使用

    # ------------------------------------------------------------------ 状态
    def status(self, case: Case) -> str:
        return self.state.get(case.case_id, {}).get("status", STATUS_TODO)

    def set_status(self, case: Case, status: str, **extra) -> None:
        entry = self.state.setdefault(case.case_id, {})
        entry.update(status=status, updated=time.strftime("%Y-%m-%d %H:%M:%S"), **extra)
        self.save_state()

    def save_state(self) -> None:
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps({"version": 1, "cases": self.state}, ensure_ascii=False, indent=2),
                                    encoding="utf-8")

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUS_ORDER}
        for c in self.cases:
            out[self.status(c)] += 1
        return out

    def find(self, case_id: str) -> Case | None:
        return next((c for c in self.cases if c.case_id == case_id), None)
