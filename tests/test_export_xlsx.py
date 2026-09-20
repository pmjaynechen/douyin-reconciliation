import io
import zipfile
import unittest
import xml.etree.ElementTree as ET

from recon_app.export_xlsx import build_xlsx


class ExportXlsxTests(unittest.TestCase):
    def test_identifier_is_text_money_is_numeric_and_date_is_sortable(self):
        content = build_xlsx(
            [("说明", "测试导出")],
            [
                {"label": "子订单号", "kind": "text", "width": 24},
                {"label": "金额", "kind": "money_cents", "width": 16},
                {"label": "动账时间", "kind": "datetime", "width": 20},
                {"label": "备注", "kind": "text", "width": 20},
            ],
            [["6923914228418287413", 128040, "2023-12-01 07:59:17", "=不执行公式"]],
        )

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            self.assertIn("xl/worksheets/sheet2.xml", names)
            result_xml = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
            styles_xml = archive.read("xl/styles.xml").decode("utf-8")
            for name in names:
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(archive.read(name))

        self.assertIn('r="A2" s="5" t="inlineStr"', result_xml)
        self.assertIn("6923914228418287413", result_xml)
        self.assertIn('r="B2" s="2"><v>1280.4</v>', result_xml)
        self.assertRegex(result_xml, r'r="C2" s="3"><v>\d+(?:\.\d+)?</v>')
        self.assertIn("=不执行公式", result_xml)
        self.assertNotIn("<f>", result_xml)
        self.assertIn('formatCode="yyyy-mm-dd hh:mm:ss"', styles_xml)
        self.assertIn('state="frozen"', result_xml)
        self.assertIn("<autoFilter", result_xml)


if __name__ == "__main__":
    unittest.main()
