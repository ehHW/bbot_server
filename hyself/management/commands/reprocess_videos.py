"""
reprocess_videos
----------------
对数据库中所有未成功处理的视频 Asset 重新触发 Celery 处理任务。

用法：
    python manage.py reprocess_videos
    python manage.py reprocess_videos --status failed queued
    python manage.py reprocess_videos --all          # 含 ready（强制重走一遍）
    python manage.py reprocess_videos --asset-id 42  # 单个
    python manage.py reprocess_videos --dry-run      # 仅预览，不提交任务
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from hyself.models import Asset
from hyself.video_processing import VIDEO_PROCESSING_KEY, mark_video_processing_status


class Command(BaseCommand):
    help = "对未成功处理的视频 Asset 重新投递 Celery 转码任务"

    def add_arguments(self, parser):
        parser.add_argument(
            "--status",
            nargs="+",
            default=["failed", "queued"],
            metavar="STATUS",
            help="重新处理哪些状态的视频（默认: failed queued）",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="force_all",
            help="包含已 ready 的视频，强制全部重新处理",
        )
        parser.add_argument(
            "--asset-id",
            type=int,
            dest="asset_id",
            default=None,
            metavar="ID",
            help="只处理指定 Asset ID",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅打印将要处理的资产列表，不实际提交任务",
        )

    def handle(self, *args, **options):
        from hyself.tasks import process_video_asset_task

        force_all: bool = options["force_all"]
        target_statuses: list[str] = options["status"]
        asset_id: int | None = options["asset_id"]
        dry_run: bool = options["dry_run"]

        qs = Asset.objects.filter(
            media_type=Asset.MediaType.VIDEO,
            storage_backend=Asset.StorageBackend.LOCAL,
            deleted_at__isnull=True,
        )
        if asset_id is not None:
            qs = qs.filter(id=asset_id)

        candidates: list[Asset] = []
        for asset in qs.iterator():
            metadata = dict(asset.extra_metadata or {})
            vp = dict(metadata.get(VIDEO_PROCESSING_KEY) or {})
            current_status = str(vp.get("status") or "").strip()

            if asset_id is not None:
                # 单个模式：无论状态如何都处理
                candidates.append(asset)
            elif force_all:
                candidates.append(asset)
            elif current_status in target_statuses or current_status == "":
                # 空状态说明从未处理过
                candidates.append(asset)

        if not candidates:
            self.stdout.write(self.style.WARNING("没有找到符合条件的视频资产。"))
            return

        self.stdout.write(f"共找到 {len(candidates)} 个待处理视频资产：")
        for asset in candidates:
            metadata = dict(asset.extra_metadata or {})
            vp = dict(metadata.get(VIDEO_PROCESSING_KEY) or {})
            current_status = str(vp.get("status") or "(未处理)").strip() or "(未处理)"
            self.stdout.write(f"  [{asset.id}] {asset.original_name or '无文件名'}  status={current_status}")

        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run 模式，不提交任务。"))
            return

        queued = 0
        for asset in candidates:
            # 强制重置为 queued 再投递（跳过 queue_video_processing 内部的 ready 守卫）
            mark_video_processing_status(asset, status="queued")
            process_video_asset_task.delay(asset.id)
            queued += 1

        self.stdout.write(self.style.SUCCESS(f"已投递 {queued} 个视频处理任务到 Celery。"))
        self.stdout.write("请确保 Celery worker 正在运行，并已安装 ffmpeg / ffprobe。")
