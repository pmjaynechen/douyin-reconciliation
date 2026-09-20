"""配置中心的初始资料。

这里只保存“新建数据库时用来生成第一个版本”的种子数据。
应用运行时从 SQLite 读取正在生效的账单模板，不会反复用本文件覆盖用户配置。
"""


DEFAULT_TEMPLATE_ID = "template-douyin-core-v1"
DEFAULT_TEMPLATE_CODE = "douyin-core-five-sheets"


ORDER_HEADERS = (
    "主订单编号", "子订单编号", "支付方式", "选购商品", "货号", "商品ID", "商家编码", "商品数量",
    "商品金额", "订单提交时间", "支付完成时间", "订单完成时间", "承诺发货时间", "预约发货时间", "买家留言",
    "旗帜颜色", "商家备注", "APP渠道", "订单状态", "取消原因", "售后状态", "订单类型", "发货时间", "车型",
    "是否是以旧换新", "换新额外补贴", "换新额外补贴发放状态", "订单应付金额", "运费", "优惠总金额", "平台优惠",
    "商家优惠", "达人优惠", "商家改价", "支付优惠", "手续费", "红包抵扣", "降价类优惠", "平台实际承担优惠金额",
    "商家实际承担优惠金额", "达人实际承担优惠金额", "收件人", "收件人手机号", "省", "市", "区", "街道", "详细地址",
    "是否修改过地址", "快递信息", "序列号", "达人ID", "达人昵称", "拼团订单团编号", "商品单价是否含税", "税费",
    "鲁班落地页ID", "所属门店ID", "流量来源", "仓库ID", "仓库名称", "是否安心购", "广告渠道", "流量类型", "流量体裁",
    "流量渠道", "发货主体", "发货主体明细", "教育优惠", "预计送达时间", "是否平台仓自流转", "是否是渠道商品", "预约送达时间",
    "建议发货时间（起）", "建议发货时间（止）",
)

AFTER_SALE_HEADERS = (
    "售后单号", "订单号", "商品单号", "商品名称", "商品ID", "应付金额（元）", "商品运费（元）", "支付优惠（元）",
    "商品税费（元）", "商品发货状态", "售后类型", "退商品金额（元）", "退运费金额（元）", "退支付优惠（元）", "退税费金额（元）",
    "售后状态", "售后申请时间", "退款方式", "是否已上传退款凭证", "售后原因", "售后原因标签", "退货物流单号", "退货异常",
    "退货发货时间", "退货物流公司", "自动处理截止时间", "同意售后申请时间", "商家退款时间", "用户到账时间", "售后关闭时间",
    "商家退货地址", "商家退货联系人姓名", "商家退货联系人电话", "仲裁状态", "纠纷责任方", "是否极速退款", "是否拒签后退款",
    "发货物流单号", "发货物流状态", "换货物流单号", "退货物流状态", "售后完结时间", "订单备注", "用户售后说明", "售后备注",
    "操作人", "协商记录", "换货商品信息", "商家编码", "门店名称",
)

SETTLEMENT_HEADERS = (
    "结算时间", "订单号", "子订单号", "结算金额", "结算账户", "结算单类型", "有结算前退款", "下单时间", "商品ID", "商品数量",
    "业务类型", "订单类型", "订单总价", "商品总价", "运费", "店铺劵", "结算前退款金额", "平台补贴", "达人补贴", "抖音支付补贴",
    "抖音月付营销补贴", "用户实付", "收入合计", "平台服务费", "佣金", "渠道分成", "招商服务费", "站外推广费", "其他分成", "其他分成说明",
    "支出合计", "是否免佣", "免佣金额", "备注",
)

FUND_HEADERS = (
    "动账时间", "动帐流水号", "动账方向", "动账金额", "动账账户", "动账场景", "计费类型", "子订单号", "订单号", "售后编号",
    "下单时间", "商品ID", "订单类型", "订单实付应结", "运费实付", "实际平台补贴_运费", "实际平台补贴", "实际达人补贴",
    "实际抖音支付补贴", "实际抖音月付营销补贴", "订单退款", "平台服务费", "佣金", "渠道分成", "招商服务费", "站外推广费", "其他分成",
    "是否免佣", "免佣金额", "备注",
)


DEFAULT_TEMPLATE_SHEETS = (
    {
        "code": "order",
        "name": "订单明细",
        "source_name": "订单明细",
        "aliases": (),
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 2435,
        "baseline_columns": 75,
        "required_headers": ("子订单编号", "货号", "商品数量", "商品金额", "订单提交时间", "订单完成时间", "订单应付金额"),
        "headers": ORDER_HEADERS,
    },
    {
        "code": "after_sale",
        "name": "售后表",
        "source_name": "售后表",
        "aliases": (),
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 212,
        "baseline_columns": 50,
        "required_headers": ("售后单号", "订单号", "商品单号", "售后类型", "售后状态", "售后申请时间"),
        "headers": AFTER_SALE_HEADERS,
    },
    {
        "code": "settlement",
        "name": "结算账单",
        "source_name": "结算账单",
        "aliases": (),
        "header_row": 1,
        "data_start_row": 3,
        "baseline_rows": 381,
        "baseline_columns": 34,
        "required_headers": ("结算时间", "订单号", "子订单号", "结算金额", "结算账户", "结算单类型"),
        "headers": SETTLEMENT_HEADERS,
    },
    {
        "code": "fund",
        "name": "资金账单",
        "source_name": "资金账单",
        "aliases": (),
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 655,
        "baseline_columns": 30,
        "required_headers": ("动账时间", "动帐流水号", "动账方向", "动账金额", "动账账户", "动账场景", "子订单号"),
        "headers": FUND_HEADERS,
        "field_aliases": {"动帐流水号": ("动账流水号",)},
    },
    {
        "code": "cost",
        "name": "成本表",
        "source_name": "成本表",
        "aliases": (),
        "header_row": 1,
        "data_start_row": 2,
        "baseline_rows": 11,
        "baseline_columns": 2,
        "required_headers": ("型号", "成本价"),
        "headers": ("型号", "成本价"),
    },
)


RULE_CATALOG = (
    ("R01", "订单应付金额", "金额检查", "重算商品、运费和各方优惠，与平台应付金额比较。", "active", "已确认"),
    ("R02", "结算账单内部金额", "金额检查", "分别检查订单总价、收入合计、支出合计和结算金额。", "active", "已确认"),
    ("R03", "平台账户金额方向", "标准化", "入账统一为正，出账统一为负，同时保留平台原方向。", "active", "已确认"),
    ("R04", "普通结算与货款入账", "结算对账", "按子订单、业务类型、金额和账户唯一匹配。", "active", "V1.1"),
    ("R05", "结算后退款", "退款对账", "按子订单和售后单汇总相关资金，唯一组合才自动通过。", "active", "V1.1"),
    ("R06", "订单与结算勾稽", "结算对账", "比较预计商家应收与结算收入，并反查已完成未结算订单。", "active", "V1.1"),
    ("R07", "售后状态分类", "售后", "区分退款成功、售后关闭、换货成功和未知状态。", "active", "已确认"),
    ("R08", "商品成本关联", "成本", "用订单货号关联成本型号，缺少成本时停止计算。", "active", "练习数据"),
    ("R09", "其他平台收支分类", "资金分类", "识别提现和已知费用；新场景进入待分类。", "active", "练习数据"),
    ("R10", "停止自动判断", "安全控制", "重复、多候选、未知状态或必要资料不足时交给用户处理。", "active", "V1.1"),
    ("R11", "退款构成试算", "退款对账", "在净额一致后，试算顾客退款和平台补贴追回。", "trial", "课程资料"),
    ("R12", "平台账户资料完整性", "资金对账", "逐笔资金与日汇总、月汇总同时比较。", "trial", "M017模拟映射"),
    ("R13", "待结算订单分类", "结算跟踪", "按取消退款、平台限制、售后和预计日期分类。", "trial", "M018模拟映射"),
)


BASE_DATA_CATALOG = (
    {
        "code": "entity_store",
        "name": "主体与店铺",
        "purpose": "确定对账数据属于哪个主体、平台和店铺。",
        "currentMode": "建立月度任务时填写",
        "targetMode": "在配置中心维护后下拉选择",
    },
    {
        "code": "business_status",
        "name": "状态与场景映射",
        "purpose": "解释平台的结算类型、售后状态和资金场景代表什么。",
        "currentMode": "已盘点，部分仍在代码中",
        "targetMode": "未知值停止自动判断，映射生效要留版本",
    },
    {
        "code": "product_cost",
        "name": "商品与成本",
        "purpose": "维护货号、商品型号、单位成本和生效日期。",
        "currentMode": "随工作簿导入静态成本",
        "targetMode": "按生效日期取对应期间成本",
    },
    {
        "code": "fund_category",
        "name": "资金收支类目",
        "purpose": "维护平台费用、补贴、赔付、提现等分类和处理方式。",
        "currentMode": "已有候选目录，未核实项不自动分类",
        "targetMode": "一条平台值映射一个标准类目，并保留来源和生效期",
    },
)


VALUE_MAPPING_TYPES = {
    "after_sale_status": {
        "name": "售后状态",
        "recordType": "after_sale",
        "sourceField": "售后状态",
        "standards": (
            {"code": "refund_success", "name": "退款成功", "canonicalValue": "同意退款，退款成功"},
            {"code": "after_sale_closed", "name": "售后关闭", "canonicalValue": "售后关闭"},
            {"code": "exchange_success", "name": "换货成功", "canonicalValue": "换货成功"},
            {"code": "after_sale_pending", "name": "售后处理中", "canonicalValue": "售后处理中"},
        ),
    },
    "fund_scene": {
        "name": "资金场景",
        "recordType": "fund",
        "sourceField": "动账场景",
        "standards": (
            {"code": "ordinary_settlement_receipt", "name": "货款结算入账", "canonicalValue": "货款结算入账"},
            {"code": "refund_user", "name": "结算后退用户", "canonicalValue": "退款-结算后退款-退用户"},
            {"code": "refund_split_return", "name": "订单退款退分账", "canonicalValue": "退款-订单退款触发-退分账"},
            {"code": "refund_split", "name": "订单退款分账", "canonicalValue": "退款-订单退款触发-分账"},
            {"code": "refund_subsidy_return", "name": "订单退款退补贴", "canonicalValue": "退款-订单退款触发-退补贴"},
            {"code": "monthly_interest", "name": "月付联合贴息", "canonicalValue": "抖音月付与商家联合贴息活动"},
            {"code": "consumer_compensation", "name": "消费者赔付", "canonicalValue": "消费者赔付"},
            {"code": "withdrawal", "name": "平台提现", "canonicalValue": "提现"},
        ),
    },
}


DEFAULT_PLATFORM_VALUE_MAPPINGS = (
    ("after_sale_status", "同意退款，退款成功", "refund_success"),
    ("after_sale_status", "售后关闭", "after_sale_closed"),
    ("after_sale_status", "换货成功", "exchange_success"),
    ("fund_scene", "货款结算入账", "ordinary_settlement_receipt"),
    ("fund_scene", "退款-结算后退款-退用户", "refund_user"),
    ("fund_scene", "退款-订单退款触发-退分账", "refund_split_return"),
    ("fund_scene", "退款-订单退款触发-分账", "refund_split"),
    ("fund_scene", "退款-订单退款触发-退补贴", "refund_subsidy_return"),
    ("fund_scene", "抖音月付与商家联合贴息活动", "monthly_interest"),
    ("fund_scene", "消费者赔付", "consumer_compensation"),
    ("fund_scene", "提现", "withdrawal"),
)
