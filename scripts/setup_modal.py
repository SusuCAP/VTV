#!/usr/bin/env python3
"""
VTV Modal 资源一键建立脚本

用法:
    uv run python scripts/setup_modal.py          # 建立所有 Modal 资源
    uv run python scripts/setup_modal.py --check  # 只检查现有资源状态
    uv run python scripts/setup_modal.py --secret-only  # 只更新 Secret

功能:
    1. 创建 Modal Secret (vtv-prod-secrets) — 包含所有运行时凭据
    2. 创建 Modal Volumes — 模型权重存储
       - vtv-models-visual    (SAM3.1, Wan-Animate, etc.)
       - vtv-models-production (CosyVoice3, LatentSync, etc.)
    3. 验证所有资源已就绪

环境要求:
    - MODAL_DISABLE_API_PROXY=1 已设置（或系统代理已关闭）
    - Modal profile 已激活 (uv run modal profile activate <profile>)
    - .env 文件存在（从 .env.example 复制后填写）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ── 加载 .env ─────────────────────────────────────────────────────────────────
_root = Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# ── 必须在加载 .env 之后才 import modal ──────────────────────────────────────
try:
    import modal
except ImportError:
    print("✗ modal 未安装。运行: uv pip install modal")
    sys.exit(1)

# ── 颜色输出 ──────────────────────────────────────────────────────────────────
GREEN = "\033[0;32m"
RED   = "\033[0;31m"
YELLOW = "\033[1;33m"
BLUE  = "\033[0;34m"
RESET = "\033[0m"

def ok(msg: str)   -> None: print(f"{GREEN}✓{RESET} {msg}")
def err(msg: str)  -> None: print(f"{RED}✗{RESET} {msg}", file=sys.stderr)
def warn(msg: str) -> None: print(f"{YELLOW}⚠{RESET} {msg}")
def info(msg: str) -> None: print(f"{BLUE}▶{RESET} {msg}")

# ── 配置 ─────────────────────────────────────────────────────────────────────

SECRET_NAME = os.environ.get("VTV_MODAL_SECRET_NAME", "vtv-prod-secrets")

VOLUMES = {
    "vtv-models-visual":     "视觉模型权重 (SAM3.1, Wan-Animate, MatAnyone2, MoCha, VACE, LTX-2.3)",
    "vtv-models-production": "生产模型权重 (CosyVoice3, VoxCPM2, LatentSync, InfiniteTalk)",
}

# 从 .env 读取的凭据 → Modal Secret 键值对
# 所有值先从环境变量读取；未设置的将被跳过（但打印警告）
SECRET_KEYS = {
    # 对象存储
    "VTV_S3_ENDPOINT":   os.environ.get("VTV_S3_ENDPOINT", ""),
    "VTV_S3_ACCESS_KEY": os.environ.get("VTV_S3_ACCESS_KEY", ""),
    "VTV_S3_SECRET_KEY": os.environ.get("VTV_S3_SECRET_KEY", ""),
    "VTV_S3_BUCKET":     os.environ.get("VTV_S3_BUCKET", "vtv-local"),
    "VTV_S3_REGION":     os.environ.get("VTV_S3_REGION", "us-east-1"),
    # 数据库（Modal 容器一般不直连本地 DB，但留着备用）
    "VTV_DATABASE_URL":  os.environ.get("VTV_DATABASE_URL", ""),
    # 控制面鉴权
    "VTV_API_KEY":       os.environ.get("VTV_API_KEY", ""),
    # HuggingFace（pyannote 等门控模型需要）
    "VTV_HF_TOKEN":      os.environ.get("VTV_HF_TOKEN", ""),
    # 模型适配器模式（运行时注入）
    "VTV_ASR_ADAPTER_MODE":                os.environ.get("VTV_ASR_ADAPTER_MODE", "local_models"),
    "VTV_VISION_ADAPTER_MODE":             os.environ.get("VTV_VISION_ADAPTER_MODE", "qwen3_vl"),
    "VTV_SEGMENTATION_ADAPTER_MODE":       os.environ.get("VTV_SEGMENTATION_ADAPTER_MODE", "sam3"),
    "VTV_VISUAL_GENERATION_ADAPTER_MODE":
        os.environ.get("VTV_VISUAL_GENERATION_ADAPTER_MODE", "wan_animate"),
    "VTV_TTS_ADAPTER_MODE":                os.environ.get("VTV_TTS_ADAPTER_MODE", "cosyvoice3"),
    "VTV_LIPSYNC_ADAPTER_MODE":            os.environ.get("VTV_LIPSYNC_ADAPTER_MODE", "latentsync"),
    # SAM3.1
    "VTV_SAM_CHECKPOINT":  os.environ.get("VTV_SAM_CHECKPOINT", "/models/sam3/sam3.1_hq.pt"),
    "VTV_SAM_MODEL_TYPE":  os.environ.get("VTV_SAM_MODEL_TYPE", "vit_h"),
    "VTV_SAM_DEVICE":      os.environ.get("VTV_SAM_DEVICE", "cuda"),
    # Wan-Animate
    "VTV_WAN_MODEL_ID":        os.environ.get("VTV_WAN_MODEL_ID", "Wan-AI/Wan2.2-I2V-A14B-480P"),
    "VTV_WAN_DEVICE":          os.environ.get("VTV_WAN_DEVICE", "cuda"),
    "VTV_WAN_DTYPE":           os.environ.get("VTV_WAN_DTYPE", "bfloat16"),
    "VTV_WAN_STEPS":           os.environ.get("VTV_WAN_STEPS", "30"),
    "VTV_WAN_GUIDANCE_SCALE":  os.environ.get("VTV_WAN_GUIDANCE_SCALE", "5.0"),
    "VTV_WAN_MAX_FRAMES":      os.environ.get("VTV_WAN_MAX_FRAMES", "81"),
    # CosyVoice3
    "VTV_COSYVOICE_MODEL_DIR":   os.environ.get("VTV_COSYVOICE_MODEL_DIR", "/models/cosyvoice3"),
    "VTV_COSYVOICE_DEVICE":      os.environ.get("VTV_COSYVOICE_DEVICE", "cuda"),
    "VTV_COSYVOICE_SAMPLE_RATE": os.environ.get("VTV_COSYVOICE_SAMPLE_RATE", "22050"),
    # LatentSync
    "VTV_LATENTSYNC_CHECKPOINT": os.environ.get("VTV_LATENTSYNC_CHECKPOINT",
                                                  "/models/latentsync/latentsync_1.6_unet.pt"),
    "VTV_LATENTSYNC_DEVICE":     os.environ.get("VTV_LATENTSYNC_DEVICE", "cuda"),
    "VTV_LATENTSYNC_FACE_RES":   os.environ.get("VTV_LATENTSYNC_FACE_RES", "512"),
    "VTV_LATENTSYNC_STEPS":      os.environ.get("VTV_LATENTSYNC_STEPS", "20"),
    # MuseTalk（LatentSync L1 fallback）
    "VTV_MUSETALKS_CHECKPOINT":  os.environ.get("VTV_MUSETALKS_CHECKPOINT",
                                                  "/models/musetalks/musetalk_v1.5.pt"),
    # InfiniteTalk（L3）
    "VTV_INFINITETALK_MODEL_ID": os.environ.get("VTV_INFINITETALK_MODEL_ID",
                                                  "InfiniteTalk/InfiniteTalk-v1"),
    # VoxCPM2
    "VTV_VOXCPM2_ENDPOINT": os.environ.get("VTV_VOXCPM2_ENDPOINT", ""),
    "VTV_VOXCPM2_API_KEY":  os.environ.get("VTV_VOXCPM2_API_KEY", ""),
    # Fish Audio
    "VTV_FISH_AUDIO_API_KEY": os.environ.get("VTV_FISH_AUDIO_API_KEY", ""),
    "VTV_FISH_AUDIO_MODEL":   os.environ.get("VTV_FISH_AUDIO_MODEL", "fish-speech-s2-pro"),
    # Qwen3-VL
    "VTV_QWEN_VLM_ENDPOINT": os.environ.get("VTV_QWEN_VLM_ENDPOINT", ""),
    "VTV_QWEN_VLM_API_KEY":  os.environ.get("VTV_QWEN_VLM_API_KEY", ""),
    # VGGT-Ω
    "VTV_VGGT_MODEL_ID":  os.environ.get("VTV_VGGT_MODEL_ID", "facebookresearch/vggt"),
    "VTV_VGGT_DEVICE":    os.environ.get("VTV_VGGT_DEVICE", "cuda"),
    # IndexTTS2
    "VTV_INDEXTTS2_MODEL_DIR": os.environ.get("VTV_INDEXTTS2_MODEL_DIR", "/models/indextts2"),
    "VTV_INDEXTTS2_DEVICE":    os.environ.get("VTV_INDEXTTS2_DEVICE", "cuda"),
    # MatAnyone2
    "VTV_MATANYONE2_MODEL_ID": os.environ.get("VTV_MATANYONE2_MODEL_ID", "pq-yang/MatAnyone2"),
    "VTV_MATANYONE2_DEVICE":   os.environ.get("VTV_MATANYONE2_DEVICE", "cuda"),
    # 日志
    "VTV_LOG_LEVEL":     os.environ.get("VTV_LOG_LEVEL", "INFO"),
    "VTV_ENVIRONMENT":   os.environ.get("VTV_ENVIRONMENT", "production"),
}


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

def check_resources() -> None:
    """检查 Modal Secret 和 Volume 是否存在。"""
    print()
    info(f"=== 检查 Modal 资源（Secret: {SECRET_NAME}）===")
    print()

    # Secret
    try:
        modal.Secret.from_name(SECRET_NAME)
        ok(f"Secret '{SECRET_NAME}' 存在")
    except Exception:
        warn(f"Secret '{SECRET_NAME}' 不存在（运行 setup 创建）")

    # Volumes
    for vol_name, desc in VOLUMES.items():
        try:
            modal.Volume.from_name(vol_name)
            ok(f"Volume '{vol_name}' 存在  —  {desc}")
        except Exception:
            warn(f"Volume '{vol_name}' 不存在  —  {desc}")


def create_secret() -> None:
    """创建或更新 Modal Secret。"""
    info(f"创建/更新 Secret: {SECRET_NAME}")

    # 过滤掉空值并警告
    payload: dict[str, str] = {}
    missing: list[str] = []
    for k, v in SECRET_KEYS.items():
        if v:
            payload[k] = v
        else:
            missing.append(k)

    if missing:
        warn(f"以下 {len(missing)} 个键为空，将跳过（可在 .env 中填写后重新运行）:")
        for m in missing:
            print(f"     {m}")
        print()

    try:
        # modal.Secret.from_dict 在部署时创建临时 secret，不持久化
        # 持久化使用 modal CLI: modal secret create <name> KEY=VAL ...
        # 这里通过 subprocess 调用 CLI 以确保持久化
        import subprocess
        args = ["uv", "run", "modal", "secret", "create", SECRET_NAME, "--force"]
        for k, v in payload.items():
            args.append(f"{k}={v}")
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0:
            ok(f"Secret '{SECRET_NAME}' 创建成功（{len(payload)} 个键）")
        else:
            err(f"Secret 创建失败:\n{result.stderr}")
            sys.exit(1)
    except Exception as e:
        err(f"Secret 创建异常: {e}")
        sys.exit(1)


def create_volumes() -> None:
    """创建 Modal Volumes（幂等操作）。"""
    for vol_name, desc in VOLUMES.items():
        info(f"创建 Volume: {vol_name}  ({desc})")
        try:
            modal.Volume.from_name(vol_name, create_if_missing=True)
            ok(f"Volume '{vol_name}' 就绪")
        except Exception as e:
            err(f"Volume '{vol_name}' 创建失败: {e}")


def print_next_steps() -> None:
    print()
    print("=" * 54)
    print("  下一步：向 Volume 写入模型权重")
    print("=" * 54)
    print("""
模型权重需要手动下载后上传到对应 Volume：

  vtv-models-visual（SAM3.1 / Wan-Animate）：
    官方地址：https://github.com/facebookresearch/sam2
    HuggingFace：Wan-AI/Wan2.2-I2V-A14B-480P

  vtv-models-production（CosyVoice3 / LatentSync）：
    官方地址：https://github.com/FunAudioLLM/CosyVoice
    官方地址：https://github.com/bytedance/LatentSync

上传命令示例（在本地下载后）：
    modal volume put vtv-models-visual /local/path/to/sam3 /models/sam3
    modal volume put vtv-models-production /local/cosyvoice3 /models/cosyvoice3

或在 Modal 函数中用 huggingface_hub.snapshot_download() 自动下载到 /models/。
""")
    print("=" * 54)
    print()


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="VTV Modal 资源一键建立脚本")
    parser.add_argument("--check",       action="store_true", help="只检查资源状态，不创建")
    parser.add_argument("--secret-only", action="store_true", help="只更新 Secret")
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════╗")
    print("║   VTV Modal 资源建立工具                   ║")
    print("╚══════════════════════════════════════════╝")

    if args.check:
        check_resources()
        return

    # Secret
    print()
    info("1/2  建立 Modal Secret")
    create_secret()

    if args.secret_only:
        ok("Secret 已更新。退出。")
        return

    # Volumes
    print()
    info("2/2  建立 Modal Volumes")
    create_volumes()

    # 最终检查
    print()
    info("=== 验证 ===")
    check_resources()

    print_next_steps()


if __name__ == "__main__":
    main()
