import os
from pathlib import Path


class AppConfig:
    def __init__(self, base_dir=None, data_dir=None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent.parent)
        self.web_dir = self.base_dir / "web"
        self.data_dir = Path(data_dir or self.base_dir / "var")
        self.upload_dir = self.data_dir / "uploads"
        self.database_path = self.data_dir / "reconciliation.db"
        configured_sample = os.environ.get("DOUYIN_RECONCILIATION_SAMPLE")
        repository_sample = self.base_dir / "sample-data" / "抖店练习数据.xlsx"
        legacy_sample = self.base_dir.parent.parent / "对账文件" / "抖店练习数据.xlsx"
        if configured_sample:
            self.sample_workbook_path = Path(configured_sample)
        elif repository_sample.is_file():
            self.sample_workbook_path = repository_sample
        else:
            self.sample_workbook_path = legacy_sample

    def ensure_directories(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
