import io
import zipfile
from xml.sax.saxutils import escape


SHEET_HEADERS = (
    ("订单明细", ("子订单编号", "主订单编号", "货号", "商品数量", "商品金额", "订单提交时间", "支付完成时间", "订单完成时间", "订单应付金额", "运费", "订单状态", "取消原因", "订单类型", "平台实际承担优惠金额", "商家实际承担优惠金额", "达人实际承担优惠金额"), 2),
    ("售后表", ("售后单号", "订单号", "商品单号", "售后类型", "售后状态", "售后申请时间", "退商品金额（元）"), 2),
    ("结算账单", ("结算时间", "订单号", "子订单号", "结算金额", "结算账户", "结算单类型", "订单总价", "商品总价", "运费", "用户实付", "平台补贴", "达人补贴", "抖音支付补贴", "抖音月付营销补贴", "收入合计", "平台服务费", "佣金", "渠道分成", "招商服务费", "站外推广费", "其他分成", "支出合计"), 3),
    ("资金账单", ("动账时间", "动帐流水号", "动账方向", "动账金额", "动账账户", "动账场景", "子订单号"), 2),
    ("成本表", ("型号", "成本价"), 2),
)


DEFAULT_ROWS = {
    "订单明细": ({"子订单编号": "1001", "主订单编号": "MAIN1", "货号": "SKU1", "商品数量": "1", "商品金额": "9.90", "订单提交时间": "2023-12-01 10:00:00", "支付完成时间": "2023-12-01 10:01:00", "订单完成时间": "2023-12-01 12:00:00", "订单应付金额": "10.00", "运费": "0.10", "订单状态": "已完成", "取消原因": "", "订单类型": "普通订单", "平台实际承担优惠金额": "0", "商家实际承担优惠金额": "0", "达人实际承担优惠金额": "0"},),
    "售后表": ({"售后单号": "AF1", "订单号": "MAIN1", "商品单号": "1001", "售后类型": "退款", "售后状态": "退款成功", "售后申请时间": "2023-12-02 10:00:00", "退商品金额（元）": "10.00"},),
    "结算账单": ({"结算时间": "2023-12-03 10:00:00", "订单号": "MAIN1", "子订单号": "1001", "结算金额": "10.00", "结算账户": "聚合账户", "结算单类型": "已结算", "订单总价": "10.00", "商品总价": "9.90", "运费": "0.10", "用户实付": "10.00", "平台补贴": "0", "达人补贴": "0", "抖音支付补贴": "0", "抖音月付营销补贴": "0", "收入合计": "10.00", "平台服务费": "0", "佣金": "0", "渠道分成": "0", "招商服务费": "0", "站外推广费": "0", "其他分成": "0", "支出合计": "0"},),
    "资金账单": ({"动账时间": "2023-12-03 10:00:00", "动帐流水号": "FUN1", "动账方向": "入账", "动账金额": "10.00", "动账账户": "聚合账户", "动账场景": "货款结算入账", "子订单号": "1001"},),
    "成本表": ({"型号": "SKU1", "成本价": "6.50"},),
}


def build_workbook_bytes(
    omit_sheet=None,
    omit_header=None,
    rows_by_sheet=None,
    sheet_name_overrides=None,
    header_overrides=None,
):
    source_rows = dict(DEFAULT_ROWS)
    if rows_by_sheet:
        source_rows.update(rows_by_sheet)
    sheets = [item for item in SHEET_HEADERS if item[0] != omit_sheet]
    workbook_sheets = []
    relationships = []
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            for index, (name, headers, data_row) in enumerate(sheets, 1):
                if omit_header and omit_header[0] == name:
                    headers = tuple(header for header in headers if header != omit_header[1])
                canonical_headers = headers
                source_name = (sheet_name_overrides or {}).get(name, name)
                source_headers = tuple(
                    (header_overrides or {}).get((name, header), header)
                    for header in canonical_headers
                )
                workbook_sheets.append(
                    '<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(
                        escape(source_name), index, index
                    )
                )
                relationships.append(
                    '<Relationship Id="rId{}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{}.xml"/>'.format(
                        index, index
                    )
                )
                rows = [_row_xml(1, source_headers)]
                if name == "结算账单":
                    rows.append(_row_xml(2, ("平台计算说明",)))
                for offset, row_values in enumerate(source_rows[name]):
                    rows.append(
                        _row_xml(
                            data_row + offset,
                            tuple(row_values.get(header) for header in canonical_headers),
                        )
                    )
                archive.writestr(
                    "xl/worksheets/sheet{}.xml".format(index),
                    '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{}</sheetData></worksheet>'.format(
                        "".join(rows)
                    ),
                )
            archive.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{}</sheets></workbook>'.format(
                    "".join(workbook_sheets)
                ),
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}</Relationships>'.format(
                    "".join(relationships)
                ),
            )
        return buffer.getvalue()


def build_operating_evidence_workbook_bytes(task_id, store_name="抖店样例店铺", period="2023-12"):
    sheets = (
        (
            "使用说明",
            {
                1: ("抖店经营利润模拟测试数据",),
                5: ("数据标识", "模拟任务编号", "模拟月份", "模拟店铺"),
                6: ("SIMULATED_FOR_PRODUCT_VALIDATION", task_id, period, store_name),
            },
        ),
        (
            "ERP成本退货",
            {
                1: ("子订单号", "SKU", "出库日期", "出库数量", "单位成本（元）", "退货入库日期", "退货入库数量", "退货单位成本（元）", "数据说明"),
                2: ("1001", "SKU1", "2023-12-01", "1", "6.50", "2023-12-03", "1", "6.50", "模拟数据"),
            },
        ),
        (
            "快递仓储费用",
            {
                1: ("子订单号", "运单号", "费用日期", "快递费（元）", "仓储费（元）", "其他履约费（元）", "费用状态", "数据说明"),
                2: ("1001", "SIM-SF-001", "2023-12-01", "1.00", "0.50", "0", "已计费", "模拟数据"),
            },
        ),
        (
            "经营费用",
            {
                1: ("费用日期", "费用类别", "金额（元）", "归属店铺", "分摊方式", "原始单号", "是否计入本期", "数据说明"),
                2: ("2023-12-31", "投流", "1.00", store_name, "店铺直接归属", "SIM-AD-001", "是", "模拟数据"),
            },
        ),
    )
    workbook_sheets = []
    relationships = []
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            for index, (name, rows) in enumerate(sheets, 1):
                workbook_sheets.append(
                    '<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(
                        escape(name), index, index
                    )
                )
                relationships.append(
                    '<Relationship Id="rId{}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{}.xml"/>'.format(
                        index, index
                    )
                )
                row_xml = "".join(_row_xml(row_number, values) for row_number, values in rows.items())
                archive.writestr(
                    "xl/worksheets/sheet{}.xml".format(index),
                    '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{}</sheetData></worksheet>'.format(row_xml),
                )
            archive.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{}</sheets></workbook>'.format("".join(workbook_sheets)),
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}</Relationships>'.format("".join(relationships)),
            )
        return buffer.getvalue()


def _row_xml(row_number, values):
    cells = []
    for index, value in enumerate(values):
        if value is None:
            continue
        reference = "{}{}".format(_column_name(index), row_number)
        cells.append(
            '<c r="{}" t="inlineStr"><is><t>{}</t></is></c>'.format(
                reference, escape(str(value))
            )
        )
    return '<row r="{}">{}</row>'.format(row_number, "".join(cells))


def _column_name(index):
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result
