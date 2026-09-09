"""运行方式：python scripts/test_miku_local_assets.py，无需启动 AstrBot 或联网。"""

import base64
import re
import unittest
from pathlib import Path

from debug_render import MockConfigManager

from src.infrastructure.reporting.templates import HTMLTemplates, local_image


class MikuLocalAssetsTests(unittest.TestCase):
    def setUp(self):
        self.templates = HTMLTemplates(MockConfigManager("HatsuneMiku"))
        self.assets = Path(__file__).resolve().parents[1] / "assets" / "HatsuneMiku"

    def test_topic_cycle_embeds_all_five_images(self):
        topics = [
            {"index": i + 1, "topic": {"topic": f"话题 {i + 1}"}} for i in range(6)
        ]
        html = self.templates.render_template("topic_item.html", topics=topics)
        images = re.findall(r'<img src="([^"]+)"', html)
        self.assertEqual(len(images), 6)
        self.assertEqual(len(set(images)), 5)
        self.assertEqual(images[0], images[5])
        for source in images:
            self.assertTrue(source.startswith("data:image/png;base64,"))
            data = base64.b64decode(source.split(",", 1)[1], validate=True)
            self.assertIn(
                data, [path.read_bytes() for path in self.assets.glob("*.png")]
            )

    def test_peak_macro_and_quality_use_local_images(self):
        env = self.templates._get_env()
        # 宏通过无 context 的 import 使用，仍须能找到 local_image 全局函数。
        peak = env.from_string(
            '{% import "inline_assets.html" as assets %}'
            "{{ assets.peak_activity_image_css() }}"
        ).render()
        self.assertIn(local_image("HatsuneMiku/retouch_2026032802083201.png"), peak)
        # 大图 Data URI 直接放 background-image，避免超长 CSS 变量被浏览器丢弃。
        self.assertIn("background-image:", peak)
        self.assertNotIn("--miku-peak-activity-image:", peak)
        quality = self.templates.render_template(
            "chat_quality_item.html", dimensions=[]
        )
        self.assertIn(local_image("HatsuneMiku/retouch_2026032810150449.png"), quality)

    def test_both_report_templates_have_no_dead_image_addresses(self):
        template_dir = Path(self.templates.base_dir) / "HatsuneMiku"
        for path in template_dir.glob("*.html"):
            with self.subTest(template=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("uploaded:", source)
                self.assertNotIn("img.heliar.top", source)

    def test_local_asset_paths_are_independent_of_working_directory(self):
        source = local_image("HatsuneMiku/retouch_2026032802083201.png")
        data = base64.b64decode(source.split(",", 1)[1], validate=True)
        self.assertEqual(
            data, (self.assets / "retouch_2026032802083201.png").read_bytes()
        )
        with self.assertRaises(ValueError):
            local_image("../metadata.yaml")
        with self.assertRaises(FileNotFoundError):
            local_image("HatsuneMiku/missing.png")


if __name__ == "__main__":
    unittest.main()
