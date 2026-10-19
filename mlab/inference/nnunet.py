"""nnU-Net v2 预标注封装。

模型目录即 nnU-Net 训练结果目录，例如::

    nnUNet_results/Dataset101_Meningitis/nnUNetTrainer__nnUNetPlans__3d_fullres/
    ├── dataset.json
    ├── plans.json
    ├── fold_0/checkpoint_final.pth
    └── ...

``nnunetv2`` 与 ``torch`` 为可选依赖，只在真正推理时导入。
"""
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..core.volume import strip_suffix


@dataclass
class ModelInfo:
    folder: Path
    dataset_name: str
    configuration: str
    trainer: str
    channel_names: dict[int, str]
    labels: dict[int, str]  # 标签值 -> 名称（不含背景）
    file_ending: str
    folds: list[str]
    checkpoints: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return f"{self.dataset_name} · {self.configuration}"

    @property
    def is_2d_natural(self) -> bool:
        return self.file_ending.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def _is_model_folder(p: Path) -> bool:
    return (p / "dataset.json").is_file() and (p / "plans.json").is_file()


def find_model_folders(path: Path | str) -> list[Path]:
    """在给定目录及其下两级中查找 nnU-Net 训练结果目录。"""
    path = Path(path)
    if _is_model_folder(path):
        return [path]
    found = [p for p in sorted(path.glob("*")) if p.is_dir() and _is_model_folder(p)]
    if not found:
        found = [p for p in sorted(path.glob("*/*")) if p.is_dir() and _is_model_folder(p)]
    return found


def inspect_model(folder: Path | str) -> ModelInfo:
    folder = Path(folder)
    if not _is_model_folder(folder):
        raise ValueError(f"{folder} 不是 nnU-Net 训练结果目录（缺少 dataset.json 或 plans.json）")
    ds = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    channels = ds.get("channel_names") or ds.get("modality") or {"0": "image"}
    labels_raw = ds.get("labels", {})
    labels: dict[int, str] = {}
    for name, value in labels_raw.items():
        if isinstance(value, (list, tuple)):  # 区域训练（regions）时取第一个值
            value = value[0] if value else 0
        try:
            v = int(value)
        except (TypeError, ValueError):
            continue
        if v > 0:
            labels[v] = name
    folds = sorted((p.name.replace("fold_", "") for p in folder.glob("fold_*") if p.is_dir()),
                   key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else s))
    ckpts = sorted({c.name for c in folder.glob("fold_*/checkpoint_*.pth")},
                   key=lambda n: (n != "checkpoint_final.pth", n))
    parts = folder.name.split("__")
    trainer, configuration = (parts[0], parts[-1]) if len(parts) >= 3 else ("", folder.name)
    return ModelInfo(
        folder=folder,
        dataset_name=folder.parent.name if folder.parent.name.startswith("Dataset") else ds.get("name", folder.name),
        configuration=configuration,
        trainer=trainer,
        channel_names={int(k): str(v) for k, v in channels.items()},
        labels=labels,
        file_ending=ds.get("file_ending", ".nii.gz"),
        folds=folds,
        checkpoints=ckpts or ["checkpoint_final.pth"],
    )


def match_channels(images: list[Path], channel_names: dict[int, str]) -> list[Path] | None:
    """把病例中的序列文件匹配到模型输入通道，无法确定时返回 ``None``（交由用户手动指定）。"""
    n = len(channel_names)
    if len(images) == n == 1:
        return list(images)
    # 1) 文件名带 nnU-Net 通道后缀
    by_suffix: dict[int, Path] = {}
    for p in images:
        m = re.match(r"^.+_(\d{4})$", strip_suffix(p.name))
        if m:
            by_suffix[int(m.group(1))] = p
    if all(i in by_suffix for i in range(n)):
        return [by_suffix[i] for i in range(n)]
    # 2) 文件名包含通道名称（如 T1C / FLAIR），优先最长匹配
    chosen: list[Path] = []
    for i in range(n):
        key = re.sub(r"[^a-z0-9]", "", channel_names[i].lower())
        hits = [p for p in images if key and key in re.sub(r"[^a-z0-9]", "", strip_suffix(p.name).lower())]
        hits = [p for p in hits if p not in chosen]
        if len(hits) != 1:
            break
        chosen.append(hits[0])
    if len(chosen) == n:
        return chosen
    # 3) 数量一致时按顺序
    if len(images) == n:
        return list(images)
    return None


def nnunet_status() -> tuple[bool, str]:
    if importlib.util.find_spec("torch") is None:
        return False, "未安装 PyTorch，无法进行模型推理（pip install torch）"
    if importlib.util.find_spec("nnunetv2") is None:
        return False, "未安装 nnU-Net v2（pip install nnunetv2）"
    return True, "nnU-Net v2 可用"


def available_devices() -> list[tuple[str, str]]:
    devices = [("auto", "自动选择")]
    try:
        import torch

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                devices.append((f"cuda:{i}", f"GPU {i} · {torch.cuda.get_device_name(i)}"))
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            devices.append(("mps", "Apple MPS"))
    except Exception:  # noqa: BLE001 - torch 未安装或驱动异常
        pass
    devices.append(("cpu", "CPU"))
    return devices


@dataclass(frozen=True)
class PredictorConfig:
    folder: str
    device: str = "auto"
    folds: tuple = ("0",)
    checkpoint: str = "checkpoint_final.pth"
    use_mirroring: bool = False
    step_size: float = 0.5


class NnUNetRunner:
    """缓存已加载的 nnU-Net 预测器，在工作线程中顺序调用。"""

    def __init__(self):
        self._config: PredictorConfig | None = None
        self._predictor = None

    def _resolve_device(self, name: str):
        import torch

        if name == "auto":
            if torch.cuda.is_available():
                return torch.device("cuda", 0)
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                return torch.device("mps")
            return torch.device("cpu")
        return torch.device(name)

    def load(self, cfg: PredictorConfig, log=print):
        if self._predictor is not None and self._config == cfg:
            return self._predictor
        from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor

        device = self._resolve_device(cfg.device)
        log(f"加载模型到 {device} …")
        predictor = nnUNetPredictor(
            tile_step_size=cfg.step_size,
            use_gaussian=True,
            use_mirroring=cfg.use_mirroring,
            perform_everything_on_device=device.type == "cuda",
            device=device,
            verbose=False,
            verbose_preprocessing=False,
            allow_tqdm=False,
        )
        folds = tuple(int(f) if str(f).isdigit() else f for f in cfg.folds)
        predictor.initialize_from_trained_model_folder(cfg.folder, use_folds=folds, checkpoint_name=cfg.checkpoint)
        self._predictor, self._config = predictor, cfg
        return predictor

    def predict(self, cfg: PredictorConfig, files: list[Path], log=print) -> Path:
        """对一个病例推理，返回写出的分割文件路径（与 ``files[0]`` 同空间）。"""
        predictor = self.load(cfg, log)
        rw = predictor.plans_manager.image_reader_writer_class()
        log("读取与预处理影像 …")
        img, props = rw.read_images([str(f) for f in files])
        log("模型推理中 …")
        seg = predictor.predict_single_npy_array(img, props, None, None, False)
        ending = predictor.dataset_json.get("file_ending", ".nii.gz")
        out = Path(tempfile.mkdtemp(prefix="mlab_pred_")) / f"prediction{ending}"
        rw.write_seg(seg, str(out), props)
        return out
